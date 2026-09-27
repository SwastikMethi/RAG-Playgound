"""Catch cross-project access, duplicate job claims, and stale-owner writes."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.integration
def test_claim_is_exclusive_and_old_owner_is_fenced():
    from app.database import Store
    from app.models import Project, Job
    from rag_runtime.errors import Problem

    store = Store(
        os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground_test",
        )
    )
    with store.session() as s:
        project = Project(name="claim test")
        s.add(project)
        s.flush()
        job = Job(project_id=project.id, kind="ingest_source", resource_id="unit-source")
        s.add(job)
        s.flush()
        job_id = job.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim(job_id), range(2)))
    claimed = [x for x in claims if x]
    assert len(claimed) == 1
    with pytest.raises(Problem, match="lease"):
        store.heartbeat(job_id, "wrong-owner")
    assert store.heartbeat(job_id, claimed[0]["owner_token"])
    with store.session() as s:
        s.get(Job, job_id).status = "succeeded"
    store.engine.dispose()


def test_profile_secrets_are_not_public_and_fixture_is_explicit(tmp_path, monkeypatch):
    from app.settings import Settings
    from rag_runtime.providers import load_profiles

    monkeypatch.setenv("SOME_PRIVATE_KEY", "secret-never-returned")
    profile_file = tmp_path / "profiles.yaml"
    profile_file.write_text(
        "profiles:\n  - id: model\n    label: My model\n    model: chat\n    operations: [generation]\n    base_url: https://approved.example/v1\n    api_key_env: SOME_PRIVATE_KEY\n    max_input_tokens: 4096\n    max_output_tokens: 512\n"
    )
    settings = Settings(
        profiles_path=profile_file,
        provider_host_allowlist=["approved.example"],
        _env_file=None,
    )
    profiles = load_profiles(settings)
    assert "secret-never-returned" not in str([p.public() for p in profiles.values()])
    assert all(p.kind != "fixture" for p in profiles.values())
    assert (
        load_profiles(Settings(profiles_path=tmp_path / "missing", _env_file=None)) == {}
    )
