"""Isolate the synchronous SDK; constrain its model calls through our existing gateway."""

import asyncio
import contextlib
import hmac
import json
import secrets
import sys
import tempfile
from pathlib import Path
from importlib.metadata import version

from .contracts import canonical, digest
from .errors import Problem
from .pageindex_adapter import SDK_VERSION, normalize_tree, unavailable_reason
from .process import run_json


async def build_document(path, source, profile, gateway, root=None):
    reason = unavailable_reason()
    if reason:
        raise Problem("ADAPTER_UNAVAILABLE", reason)
    token = secrets.token_urlsafe(32)
    records, tasks, failure = [], set(), []

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        status, body = 200, {}
        try:
            async with asyncio.timeout(120):
                header = (await reader.readuntil(b"\r\n\r\n")).decode("latin1")
                lines = header.split("\r\n")
                fields = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
                fields = {k.lower(): v.strip() for k, v in fields.items()}
                if lines[0].split()[:2] != ["POST", "/v1/chat/completions"] or not hmac.compare_digest(
                    fields.get("authorization", ""), "Bearer " + token
                ):
                    raise Problem("SDK_TRANSPORT", "Unauthorized SDK transport request.")
                length = int(fields.get("content-length", "0"))
                if not 0 < length <= 4 * 1024 * 1024:
                    raise Problem("SDK_TRANSPORT", "The SDK request exceeds the input limit.")
                request = json.loads(await reader.readexactly(length))
                if failure:
                    raise failure[0]
                messages = request["messages"]
                if (
                    not isinstance(messages, list)
                    or not messages
                    or any(
                        not isinstance(m, dict)
                        or m.get("role") not in {"system", "user", "assistant"}
                        or not isinstance(m.get("content"), str)
                        for m in messages
                    )
                ):
                    raise Problem("SDK_TRANSPORT", "The SDK returned unsupported model input.")
                reply = await gateway.complete(
                    profile, messages, max_tokens=min(profile.max_output_tokens or 4096, 4096), retries=1
                )
                records.append(dict(reply["recording"], operation="tree_indexing"))
                body = dict(
                    id="indexing",
                    object="chat.completion",
                    created=0,
                    model=profile.model,
                    choices=[
                        dict(
                            index=0,
                            message=dict(role="assistant", content=reply["text"]),
                            finish_reason="stop",
                        )
                    ],
                    usage=dict(
                        prompt_tokens=reply["usage"]["input_tokens"] or 0,
                        completion_tokens=reply["usage"]["output_tokens"] or 0,
                        total_tokens=(reply["usage"]["input_tokens"] or 0)
                        + (reply["usage"]["output_tokens"] or 0),
                    ),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, Problem)
                else Problem("ADAPTER_UNAVAILABLE", "The PageIndex model transport could not complete.")
            )
            failure.append(error)
            # The pinned SDK never retries 401. Preserve the real sanitized error outside the SDK.
            status, body = (
                401,
                dict(
                    error=dict(
                        message="Indexing stopped by application gateway.", type="application_gateway_stop"
                    )
                ),
            )
        finally:
            try:
                data = canonical(body)
                writer.write(
                    f"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
                    + data
                )
                await writer.drain()
            except (ConnectionError, RuntimeError):
                pass
            writer.close()
            tasks.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=64 * 1024)
    port = server.sockets[0].getsockname()[1]
    try:
        try:
            output = await run_json(
                ["-m", "rag_runtime.pageindex_build"],
                timeout=600,
                root=root,
                input_data=dict(
                    path=str(path),
                    model=profile.model,
                    base_url=f"http://127.0.0.1:{port}/v1",
                    key=token,
                    page_count=len(source["segments"]),
                ),
            )
        except Problem:
            if failure:
                raise failure[0]
            raise
        if failure:
            raise failure[0]
    finally:
        server.close()
        await server.wait_closed()
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return dict(
        document_id=source["source_id"],
        source=source,
        nodes=normalize_tree(output["tree"], len(source["segments"])),
        description=output["description"][:2000],
        sdk_version=SDK_VERSION,
        sdk_document_id=output["document_id"],
        page_hashes=output["page_hashes"],
        recordings=records,
    )


def sdk_index(request, root=None):
    """Only public SDK methods; stdout belongs exclusively to the JSON process boundary."""
    reason = unavailable_reason()
    if reason:
        raise Problem("ADAPTER_UNAVAILABLE", reason)
    from pageindex import PageIndexClient

    with tempfile.TemporaryDirectory(prefix="pageindex-", dir=root) as tmp:
        pdf = Path(tmp) / "source.pdf"
        pdf.write_bytes(Path(request["path"]).read_bytes())
        client = PageIndexClient(
            index=dict(
                model="openai/" + request["model"],
                backend=dict(api_base=request["base_url"], api_key=request["key"], max_retries=0, timeout=90),
                storage_path=str(Path(tmp) / "index"),
            )
        )
        submitted = client.submit_document(str(pdf), wait=True)
        document_id = submitted["doc_id"]
        tree = client.get_tree(document_id, node_summary=True, include_text=False)
        metadata = client.get_document(document_id)
        pages = client.get_page_content(document_id, f"1-{request['page_count']}")
        if tree.get("status") != "completed" or sorted(p["page_index"] for p in pages) != list(
            range(1, request["page_count"] + 1)
        ):
            raise Problem(
                "ADAPTER_UNAVAILABLE", "PageIndex did not provide a complete original-page mapping."
            )
        return dict(
            document_id=document_id,
            tree=tree["result"],
            description=metadata.get("description") or "",
            page_hashes=[dict(page=p["page_index"], sha256=digest(p["markdown"].encode())) for p in pages],
            sdk_version=version("pageindex"),
        )


if __name__ == "__main__":
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = sdk_index(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[1]).parent)
        print(json.dumps(result))
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, Problem)
            else Problem(
                "ADAPTER_UNAVAILABLE",
                "PageIndex indexing failed. Check the pinned dependency and model profile.",
            )
        )
        print(json.dumps(dict(error=error.public())))
        sys.exit(1)
