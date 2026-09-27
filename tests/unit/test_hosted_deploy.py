import asyncio
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from deploy import backup


def test_aws_api_origin_is_private_and_uncached():
    template = (Path(__file__).parents[2] / "infra/aws/template.yaml").read_text()
    assert "AuthType: AWS_IAM" in template
    assert "InvokeMode: RESPONSE_STREAM" in template
    assert "OriginAccessControlOriginType: lambda" in template
    assert "PathPattern: /api/*" in template
    assert "CachePolicyId: 4135ea2d-6df8-44a3-9df3-4b5a84be39ad" in template
    assert "OriginRequestPolicyId: b689b0a8-53d0-40ab-baf2-68738e2966ac" in template
    assert "LoggingConfig: {LogGroup: !Ref ApiLogs}" in template
    assert "ReservedConcurrentExecutions: 10" not in template
    assert "account concurrency quota is 10" in template


def test_lambda_image_publish_disables_oci_attestations():
    script = (Path(__file__).parents[2] / "infra/aws/publish-api.sh").read_text()
    assert "--platform linux/arm64" in script
    assert "--provenance=false" in script
    assert "--sbom=false" in script


def test_aws_deploy_passes_immutable_image_tags_explicitly():
    script = (Path(__file__).parents[2] / "infra/aws/deploy.sh").read_text()
    assert '--parameter-overrides ApiImageTag="$api_image_tag" WorkerImageTag="$worker_image_tag"' in script


def test_aws_wake_controller_serializes_and_recovers_workers():
    template = (Path(__file__).parents[2] / "infra/aws/template.yaml").read_text()
    assert "FifoQueue: true" in template
    assert "Type: AWS::Lambda::EventSourceMapping" in template
    assert "ScheduleExpression: rate(1 hour)" in template
    assert "detail-type: ['ECS Task State Change']" in template
    assert "clientToken=token" in template
    assert '"assignPublicIp": "ENABLED"' in template
    assert "{Name: RAG_MIN_FREE_BYTES, Value: '0'}" in template


def test_hosted_worker_exits_after_idle_timeout(monkeypatch):
    from workers import main

    class IdleWorker:
        settings = SimpleNamespace(worker_idle_seconds=60, worker_max_seconds=7200)

        async def run_once(self):
            return False

    ticks = iter([0, 61])
    monkeypatch.setattr(main, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    asyncio.run(main.serve(IdleWorker()))


def test_qdrant_cloud_key_stays_server_side(monkeypatch):
    from rag_runtime import vectors

    captured = {}
    monkeypatch.setattr(vectors, "QdrantClient", lambda **kwargs: captured.update(kwargs))
    vectors.VectorStore("https://example.qdrant.io", api_key="secret")
    assert captured == {"url": "https://example.qdrant.io", "api_key": "secret", "timeout": 20}


def test_hosted_rate_limit_uses_cloudfront_viewer_address():
    from app.auth import client_address

    request = SimpleNamespace(
        headers={"cloudfront-viewer-address": "[2001:db8::7]:443"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_address(request, hosted=True) == "2001:db8::7"


def test_lambda_loads_only_string_secret_settings():
    from app.lambda_entry import load_deployment_secret

    class Secrets:
        def get_secret_value(self, **_kwargs):
            return {"SecretString": '{"RAG_DATABASE_URL":"postgresql://db","IGNORED":"value"}'}

    environment = {}
    load_deployment_secret("secret-arn", Secrets(), environment)
    assert environment == {"RAG_DATABASE_URL": "postgresql://db"}


def test_committed_job_wake_uses_fifo_identity():
    from app.database import publish_wakes

    class Sqs:
        def __init__(self):
            self.calls = []

        def send_message(self, **kwargs):
            self.calls.append(kwargs)

    client = Sqs()
    publish_wakes(SimpleNamespace(wake_queue_url="https://sqs.example/wake.fifo"), ["job-1"], client)
    assert client.calls == [{
        "QueueUrl": "https://sqs.example/wake.fifo",
        "MessageBody": '{"job_id":"job-1"}',
        "MessageGroupId": "worker",
        "MessageDeduplicationId": "job-1",
    }]


def test_external_artifact_storage_does_not_check_lambda_temp_disk(monkeypatch):
    from app.quotas import disk_space

    monkeypatch.setattr("app.quotas.shutil.disk_usage", lambda _path: (_ for _ in ()).throw(AssertionError()))
    store = SimpleNamespace(artifacts=object(), settings=SimpleNamespace(min_free_bytes=20 * 1024**3))
    disk_space(store)


def test_bad_hosted_settings_do_not_echo_secret_inputs():
    from app.settings import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as caught:
        Settings(deployment="hosted", public_origin="http://wrong.example", master_key="private-master-value",
                 turnstile_secret_key="private-turnstile-value", _env_file=None)
    assert "input_value" not in str(caught.value)


def test_backup_only_prunes_owned_successful_snapshots():
    base = {"volume-id": "volume-a", "freeform-tags": backup.TAG, "lifecycle-state": "AVAILABLE", "time-created": "2026-09-27"}
    rows = [dict(base, id="owned"), dict(base, id="foreign", **{"volume-id": "volume-b"}),
            dict(base, id="untagged", **{"freeform-tags": {}}),
            dict(base, id="pending", **{"freeform-tags": {"rag-playground": "pending-v1"}})]
    assert [row["id"] for row in backup.owned_backups(rows, "volume-a")] == ["owned"]


def test_failed_backup_restarts_without_certifying_or_deleting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    monkeypatch.setattr(backup, "DATA", tmp_path / "data", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / ".env.production").write_text("OCI_DATA_VOLUME_ID=ocid1.volume.test\nOCI_COMPARTMENT_ID=ocid1.compartment.test\n")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/profiles.yaml").write_text("profiles: []")
    commands = []
    def run(command, **kwargs):
        commands.append(command)
    monkeypatch.setattr(backup.subprocess, "run", run)
    monkeypatch.setattr(backup.subprocess, "check_output", lambda *args, **kwargs: "commit")
    monkeypatch.setattr(backup.os, "sync", lambda: None)
    def oci(*args):
        commands.append(list(args))
        if "create" in args:
            assert 'pending-v1' in args[args.index("--freeform-tags")+1]
            raise subprocess.CalledProcessError(1, "oci")
        return []
    monkeypatch.setattr(backup, "oci", oci)
    with pytest.raises(subprocess.CalledProcessError):
        backup.backup()
    assert commands[-1][1:] == ["up", "-d"]
    assert not any("delete" in command or "update" in command for command in commands)
