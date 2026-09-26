"""Owner-controlled profiles; credentials never enter portable configuration."""

import os
import asyncio
import json
import time
import hashlib
import math
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
import httpx
from pydantic import BaseModel, ConfigDict, Field

from .contracts import digest
from .errors import Problem
from .chunking import token_count, lexical_tokens
from .vectors import check_vectors


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    model: str
    operations: list[Literal["generation", "embedding", "tree_selection", "tree_indexing", "reranking"]]
    base_url: str = ""
    api_key_env: str = ""
    kind: Literal["openai", "fixture"] = "openai"
    max_input_tokens: int = Field(8192, ge=256)
    max_output_tokens: int | None = Field(None, ge=64)
    dimensions: int | None = Field(None, ge=1, le=65536)
    tokenizer: str | None = None
    supports_temperature: bool = True
    supports_seed: bool = False
    revision: str = "1"

    @property
    def key(self):
        return os.environ.get(self.api_key_env, "")

    @property
    def unavailable_reason(self):
        if self.kind == "fixture":
            return None
        if not self.key:
            return "Configure the server-side credential for this profile."
        if "embedding" in self.operations and (not self.dimensions or not self.tokenizer):
            return "Embedding dimensions and a compatible tokenizer must be configured."
        if {"generation", "tree_selection", "tree_indexing"}.intersection(self.operations) and (
            not self.max_output_tokens or not self.tokenizer
        ):
            return "Generation token limits and a compatible tokenizer must be configured."
        return None

    def public(self):
        return dict(
            id=self.id,
            label=self.label,
            models=[self.model],
            operations=self.operations,
            available=self.unavailable_reason is None,
            unavailable_reason=self.unavailable_reason,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            dimensions=self.dimensions,
        )

    def fingerprint(self):
        return digest(self.model_dump(exclude={"api_key_env", "label"}))


def load_profiles(settings):
    if settings.mode in {"fixture", "test"}:
        return {
            p.id: p
            for p in [
                Profile(
                    id="fixture-answer",
                    label="Fixture answer (synthetic)",
                    model="fixture-answer-v1",
                    kind="fixture",
                    operations=["generation", "tree_selection"],
                    max_output_tokens=4096,
                    tokenizer="cl100k_base",
                ),
                Profile(
                    id="fixture-embedding",
                    label="Fixture embeddings (synthetic)",
                    model="fixture-embedding-v1",
                    kind="fixture",
                    operations=["embedding"],
                    dimensions=64,
                    tokenizer="cl100k_base",
                ),
            ]
        }
    path = Path(settings.profiles_path)
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    profiles = {}
    for raw in (data or {}).get("profiles", []):
        profile = Profile.model_validate(raw)
        url = urlsplit(profile.base_url)
        if profile.kind != "openai" or url.scheme not in {"https", "http"} or not url.hostname:
            raise Problem(
                "VALIDATION_ERROR", "Live profiles require an explicit compatible provider endpoint."
            )
        if (
            url.username
            or url.password
            or url.query
            or url.fragment
            or url.hostname not in settings.provider_host_allowlist
        ):
            raise Problem(
                "VALIDATION_ERROR",
                "Provider endpoint must match the owner allowlist and contain no credentials.",
            )
        if url.hostname in {"169.254.169.254", "100.100.100.200", "metadata.google.internal"}:
            raise Problem("VALIDATION_ERROR", "Metadata service endpoints are not permitted.")
        if profile.id in profiles:
            raise Problem("VALIDATION_ERROR", "Provider profile identifiers must be unique.")
        profiles[profile.id] = profile
    return profiles


def empty_usage():
    return dict(
        input_tokens=None,
        output_tokens=None,
        embedding_tokens=None,
        estimated_cost_usd=None,
        accounting="unavailable",
        price_revision=None,
    )


def add_usage(total, usage):
    for key in ("input_tokens", "output_tokens", "embedding_tokens"):
        if usage[key] is not None:
            total[key] = (total[key] or 0) + usage[key]
    modes = {total["accounting"], usage["accounting"]}
    total["accounting"] = (
        "partial"
        if "partial" in modes
        else "estimated"
        if "estimated" in modes
        else "reported"
        if modes == {"reported"} or total["accounting"] == "unavailable" and usage["accounting"] == "reported"
        else "partial"
        if "reported" in modes
        else "unavailable"
    )


def provider_error(exc):
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    if status in {401, 403}:
        return Problem("PROVIDER_AUTH", "The model provider rejected its server-side credentials.", 502)
    retryable = status in {429, 500, 502, 503, 504} or isinstance(exc, httpx.TransportError)
    return Problem("PROVIDER_FAILED", "The model provider could not complete the request.", 502, retryable)


class Gateway:
    def __init__(self, generation_concurrency=4, embedding_concurrency=4, transport=None):
        self.generation_concurrency = generation_concurrency
        self.embedding_concurrency = embedding_concurrency
        self.transport = transport
        self._semaphores = {}

    def semaphore(self, profile, operation):
        key = (
            id(asyncio.get_running_loop()),
            profile.id,
            "embedding" if operation == "embedding" else "model",
        )
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(
                self.embedding_concurrency if operation == "embedding" else self.generation_concurrency
            )
        return self._semaphores[key]

    async def complete(self, profile, messages, *, max_tokens=512, json_mode=False, retries=0):
        """Bounded non-streaming model boundary for selection and SDK indexing."""
        if profile.unavailable_reason:
            raise Problem("MISSING_CREDENTIALS", profile.unavailable_reason)
        if profile.kind == "fixture":
            raise Problem(
                "ADAPTER_UNAVAILABLE",
                "Tree indexing and selection require a configured model; no synthetic tree is substituted.",
            )
        max_tokens = min(max_tokens, profile.max_output_tokens or 512)
        if (
            token_count(json.dumps(messages, ensure_ascii=False), profile.tokenizer) + max_tokens + 64
            > profile.max_input_tokens
        ):
            raise Problem(
                "MODEL_INPUT_LIMIT", "The tree selection or indexing prompt exceeds this model's input limit."
            )
        payload = dict(model=profile.model, messages=messages, stream=False, max_tokens=max_tokens)
        if profile.supports_temperature:
            payload["temperature"] = 0
        if json_mode:
            payload["response_format"] = dict(type="json_object")
        wait = 0
        for attempt in range(retries + 1):
            began = time.monotonic()
            async with self.semaphore(profile, "model"):
                wait += (time.monotonic() - began) * 1000
                try:
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        timeout=httpx.Timeout(90, connect=10),
                        follow_redirects=False,
                        trust_env=False,
                    ) as client:
                        response = await client.post(
                            profile.base_url.rstrip("/") + "/chat/completions",
                            headers={"Authorization": f"Bearer {profile.key}"},
                            json=payload,
                        )
                        response.raise_for_status()
                        if len(response.content) > 1024 * 1024:
                            raise Problem(
                                "PROVIDER_OUTPUT_LIMIT", "The model response exceeded the output limit."
                            )
                        body = response.json()
                    value = body["choices"][0]["message"]["content"]
                    if not isinstance(value, str) or body["choices"][0].get("finish_reason") != "stop":
                        raise Problem(
                            "MODEL_OUTPUT_INVALID",
                            "The model did not return a complete selection or summary.",
                        )
                    counts = body.get("usage") or {}
                    usage = dict(
                        empty_usage(),
                        input_tokens=counts.get("prompt_tokens"),
                        output_tokens=counts.get("completion_tokens"),
                        accounting="reported"
                        if counts.get("prompt_tokens") is not None
                        and counts.get("completion_tokens") is not None
                        else "unavailable",
                    )
                    return dict(
                        text=value,
                        usage=usage,
                        wait_ms=wait,
                        recording=dict(
                            operation="completion",
                            model=profile.model,
                            input_sha256=digest(messages),
                            text=value,
                            usage=usage,
                            attempts=attempt + 1,
                        ),
                    )
                except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                    error = provider_error(exc)
                    if attempt == retries or not error.retryable:
                        raise error from None
            await asyncio.sleep(0.25)

    async def embed(self, profile, inputs):
        if profile.unavailable_reason:
            raise Problem("MISSING_CREDENTIALS", profile.unavailable_reason)
        counts = [token_count(text, profile.tokenizer) for text in inputs]
        if any(count > profile.max_input_tokens for count in counts):
            raise Problem(
                "EMBEDDING_INPUT_LIMIT",
                "A passage exceeds the embedding model's token limit. Choose smaller chunks.",
            )
        vectors, total_wait, reported_tokens = [], 0, 0
        reported = True
        start = 0
        while start < len(inputs):
            end, count = start, 0
            while end < len(inputs) and end - start < 32 and count + counts[end] <= profile.max_input_tokens:
                count += counts[end]
                end += 1
            batch = inputs[start:end]
            for attempt in range(2):
                began = time.monotonic()
                async with self.semaphore(profile, "embedding"):
                    total_wait += (time.monotonic() - began) * 1000
                    if profile.kind == "fixture":
                        for text in batch:
                            vector = [0.0] * profile.dimensions
                            for token in lexical_tokens(text) or [text]:
                                hash = hashlib.sha256(token.encode()).digest()
                                vector[int.from_bytes(hash[:4], "big") % profile.dimensions] += 1
                            norm = math.sqrt(sum(v * v for v in vector))
                            vectors.append([v / norm for v in vector])
                        reported = False
                        break
                    try:
                        async with httpx.AsyncClient(
                            transport=self.transport, timeout=90, follow_redirects=False, trust_env=False
                        ) as client:
                            response = await client.post(
                                profile.base_url.rstrip("/") + "/embeddings",
                                headers={"Authorization": f"Bearer {profile.key}"},
                                json=dict(model=profile.model, input=batch, encoding_format="float"),
                            )
                            response.raise_for_status()
                            body = response.json()
                            data = sorted(body["data"], key=lambda item: item["index"])
                            if [item["index"] for item in data] != list(range(len(batch))):
                                raise Problem(
                                    "EMBEDDING_COUNT", "The embedding response did not match the passages."
                                )
                            values = [item["embedding"] for item in data]
                            check_vectors(values, profile.dimensions)
                            vectors.extend(values)
                            usage = body.get("usage", {})
                            if usage.get("total_tokens") is None:
                                reported = False
                            else:
                                reported_tokens += usage["total_tokens"]
                            break
                    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                        error = provider_error(exc)
                        if attempt == 1 or not error.retryable:
                            raise error from None
                await asyncio.sleep(0.25)
            start = end
        return dict(
            vectors=vectors,
            wait_ms=total_wait,
            usage=dict(
                empty_usage(),
                embedding_tokens=reported_tokens if reported else sum(counts),
                accounting="reported" if reported else "estimated",
            ),
            recording=dict(
                operation="embedding",
                profile_fingerprint=profile.fingerprint(),
                request_sha256=digest(inputs),
                response=vectors,
            ),
        )

    async def stream(self, profile, generation, messages):
        if profile.kind != "fixture" and profile.unavailable_reason:
            raise Problem("MISSING_CREDENTIALS", profile.unavailable_reason)
        delivered = False
        for attempt in range(1, 3):
            began = time.monotonic()
            async with self.semaphore(profile, "generation"):
                yield {"wait_ms": (time.monotonic() - began) * 1000, "attempt": attempt}
                if profile.kind == "fixture":
                    # Deliberately synthetic, reachable only through explicit fixture/test profiles.
                    evidence = messages[-1]["content"].split("<evidence>", 1)[-1].split("</evidence>", 1)[0]
                    excerpt = evidence.split("\n", 3)[-1].strip()[:350]
                    answer = f"Fixture demonstration: {excerpt} [E1]"
                    for start in range(0, len(answer), 24):
                        await asyncio.sleep(0.002)
                        yield {"text": answer[start : start + 24]}
                    yield {
                        "usage": dict(
                            empty_usage(),
                            input_tokens=token_count(str(messages), profile.tokenizer),
                            output_tokens=token_count(answer, profile.tokenizer),
                            accounting="estimated",
                        )
                    }
                    return
                payload = dict(
                    model=profile.model,
                    messages=messages,
                    stream=True,
                    max_tokens=generation["max_output_tokens"],
                    stream_options={"include_usage": True},
                )
                if profile.supports_temperature:
                    payload["temperature"] = generation["temperature"]
                if generation["seed"] is not None and profile.supports_seed:
                    payload["seed"] = generation["seed"]
                try:
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        timeout=httpx.Timeout(90, connect=10),
                        follow_redirects=False,
                        trust_env=False,
                    ) as client:
                        async with client.stream(
                            "POST",
                            profile.base_url.rstrip("/") + "/chat/completions",
                            headers={"Authorization": f"Bearer {profile.key}"},
                            json=payload,
                        ) as response:
                            response.raise_for_status()
                            done = False
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    done = True
                                    break
                                item = json.loads(data)
                                if item.get("error"):
                                    raise Problem(
                                        "PROVIDER_FAILED", "The provider returned a streaming error.", 502
                                    )
                                usage = item.get("usage")
                                if usage:
                                    yield {
                                        "usage": dict(
                                            empty_usage(),
                                            input_tokens=usage.get("prompt_tokens"),
                                            output_tokens=usage.get("completion_tokens"),
                                            accounting="reported",
                                        )
                                    }
                                for choice in item.get("choices", []):
                                    value = choice.get("delta", {}).get("content")
                                    if value:
                                        if not isinstance(value, str):
                                            raise ValueError("Invalid provider content")
                                        delivered = True
                                        yield {"text": value}
                                    if choice.get("finish_reason"):
                                        done = True
                            if not done:
                                raise Problem(
                                    "PROVIDER_STREAM_INTERRUPTED",
                                    "The answer stream ended before completion.",
                                    502,
                                )
                    return
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    error = provider_error(exc)
                    if delivered or attempt == 2 or not error.retryable:
                        raise error from None
                except Problem:
                    raise
            yield {"retry": True, "attempt": attempt + 1}
            await asyncio.sleep(0.25)
