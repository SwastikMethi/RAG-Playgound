"""Opt-in smoke using only a generated fictional PDF, real providers and the real worker."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app.main import create_app
from app.settings import Settings
from workers.main import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model-calls", action="store_true")
    args = parser.parse_args()
    if not args.allow_model_calls:
        parser.error("Pass --allow-model-calls to use configured credentials for bounded, billable checks.")
    settings = Settings()
    if settings.mode != "live":
        parser.error("RAG_MODE must be live. Fixture responses cannot pass this check.")
    output = Path(".data/release")
    output.mkdir(parents=True, exist_ok=True)
    pdf = output / "fictional-clock-guide.pdf"
    canvas = Canvas(str(pdf))
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(50, 760, "Fictional Clock Recovery Guide")
    canvas.setFont("Helvetica", 12)
    lines = [
        "This is a synthetic release-test document, not advice for a real device.",
        "NEBULA-42 means the local clock differs from the reference clock.",
        "Recovery: synchronize the system clock, then reconnect the client.",
        "If synchronization fails, check time-service access before retrying.",
        "Do not rotate credentials to fix NEBULA-42; this error concerns time.",
        "A separate SOLAR-17 error means a paused upload. Resume that upload.",
        "Record the original error and the measured time difference for support.",
    ]
    for i, line in enumerate(lines):
        canvas.drawString(50, 725 - i * 24, line)
    canvas.save()
    report = dict(date=datetime.now(timezone.utc).isoformat(), source="Generated fictional clock PDF", preparations=[], lanes=[], exports=[])

    def save():
        (output / "live-report.json").write_text(json.dumps(report, indent=2))

    with TestClient(create_app(settings)) as client:

        def request(method, path, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error", {}).get("message", "API request failed"))
            return response.json()

        def post(path, data):
            return request("POST", path, json=data, headers={"Idempotency-Key": str(uuid4())})

        worker = Worker(settings)
        report["profiles"] = {p.id: p.model for p in worker.profiles.values()}
        project = post("/projects", {"name": "Live release check · fictional clock guide"})
        report["project_id"] = project["id"]
        root = "/projects/" + project["id"]
        source = request("POST", root + "/sources/upload", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
        try:
            asyncio.run(worker.run_resource(source["id"]))
            source = request("GET", "/sources/" + source["id"])
            report["source_status"] = source["status"]
            if source["status"] != "ready":
                report["source_error"] = source["error"]
                raise RuntimeError("PDF ingestion failed")
            corpus = post(root + "/corpus-versions", {"source_ids": [source["id"]]})
            selected = []
            for capability in request("GET", "/system/capabilities")["items"]:
                config = capability["default_config"]
                if not capability["available"]:
                    report["preparations"].append(dict(technique=capability["technique"], status="unavailable", error=capability["unavailable_reason"]))
                    continue
                config["generation"]["max_output_tokens"] = 192
                saved = post(root + "/configurations", {"name": capability["display_name"], "config": config})
                bundle = post(root + "/preparations", {"config_id": saved["id"], "corpus_version_id": corpus["id"]})
                asyncio.run(worker.run_resource(bundle["id"]))
                bundle = request("GET", "/index-bundles/" + bundle["id"])
                report["preparations"].append(dict(technique=capability["technique"], status=bundle["status"], error=bundle["error"], setup_ms=bundle["preparation_ms"], reused=bundle["preparation_reused"]))
                save()
                print(json.dumps(report["preparations"][-1]), flush=True)
                if bundle["status"] == "ready":
                    selected.append(dict(config_id=saved["id"], bundle_id=bundle["id"]))
            if not selected:
                raise RuntimeError("No live pipeline could be prepared")
            run = post(root + "/runs", {"corpus_version_id": corpus["id"], "question": "What does NEBULA-42 mean, and how should I recover? Cite the supplied source.", "lanes": selected})
            report["run_id"] = run["id"]
            save()
            asyncio.run(worker.run_resource(run["id"]))
            result = request("GET", "/runs/" + run["id"])
            for lane in result["lanes"]:
                evidence = request("GET", f"/runs/{run['id']}/lanes/{lane['id']}/evidence")["evidence"]
                report["lanes"].append({k: lane[k] for k in ["id", "technique", "status", "answer", "metrics", "usage", "error"]} | dict(evidence_count=len(evidence), source_ids=sorted({e["source_id"] for e in evidence})))
            events = client.get("/api/v1/runs/" + run["id"] + "/events").text
            frames = [json.loads(line[6:]) for line in events.splitlines() if line.startswith("data: ")]
            report["stream"] = dict(ordered=[e["seq"] for e in frames] == list(range(1, len(frames) + 1)), deltas=sum(e["type"] == "answer.delta" for e in frames), modes=sorted({result["mode"]}))
            for lane in result["lanes"]:
                if lane["technique"] not in {"dense", "pageindex"} or lane["status"] != "completed":
                    continue
                export = post(f"/runs/{run['id']}/lanes/{lane['id']}/exports", {"include_data": True, "verification_mode": "live"})
                asyncio.run(worker.run_resource(export["id"]))
                export = request("GET", "/exports/" + export["id"])
                report["exports"].append(dict(technique=lane["technique"], status=export["status"], error=export["error"], verification=export["manifest"]["verification"] if export["manifest"] else None))
                if export["download_url"]:
                    (output / f"{lane['technique']}-live.zip").write_bytes(client.get(export["download_url"]).content)
                save()
            # Stop a real lane after generation starts; no synthetic provider replacement.
            cancelled = post(root + "/runs", {"corpus_version_id": corpus["id"], "question": "Explain each detail of the NEBULA-42 recovery guide in a numbered list with citations.", "lanes": [selected[0]]})

            async def cancellation():
                task = asyncio.create_task(worker.run_resource(cancelled["id"]))
                from app.models import RunEvent
                from sqlalchemy import select
                while not task.done():
                    with worker.store.session() as s:
                        started = s.scalar(select(RunEvent.seq).where(RunEvent.run_id == cancelled["id"], RunEvent.type == "stage.started", RunEvent.payload["stage"].as_string() == "generation").limit(1))
                    if started:
                        await asyncio.sleep(.1)
                        post(f"/runs/{cancelled['id']}/lanes/{cancelled['lanes'][0]['id']}/cancel", None)
                        break
                    await asyncio.sleep(.02)
                await task

            asyncio.run(cancellation())
            final = request("GET", "/runs/" + cancelled["id"])
            report["cancellation"] = dict(status=final["lanes"][0]["status"], usage=final["lanes"][0]["usage"])
            report["status"] = "passed" if len(report["lanes"]) == 6 and all(x["status"] == "completed" and x["evidence_count"] > 0 for x in report["lanes"]) and all(x["status"] == "ready" for x in report["exports"]) and report["cancellation"]["status"] == "cancelled" else "incomplete"
        except Exception as exc:
            report["status"] = "failed"
            report["failure"] = type(exc).__name__ + ": " + str(exc)
        finally:
            worker.close()
            save()
    print(json.dumps(dict(status=report["status"], report=str(output / "live-report.json")), indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
