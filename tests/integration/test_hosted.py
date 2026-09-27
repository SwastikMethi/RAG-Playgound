"""Hosted boundaries run against a separate database, never the local workspace."""
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import TEST_URL

pytestmark = pytest.mark.integration
ORIGIN = "https://rag.example.test"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def hosted(tmp_path):
    settings = Settings(mode="test", deployment="hosted", public_origin=ORIGIN,
        database_url=TEST_URL, artifact_root=tmp_path, master_key=Fernet.generate_key().decode(),
        turnstile_site_key="test-site", turnstile_secret_key="test-secret", min_free_bytes=0,
        _env_file=None)
    with TestClient(create_app(settings), base_url=ORIGIN, client=("test-" + uuid4().hex, 50000)) as c:
        c.headers["Origin"] = ORIGIN
        yield c


def signup(c, username=None):
    response = c.post("/api/v1/auth/register", json={
        "username": username or "u" + uuid4().hex[:16], "password": PASSWORD,
        "turnstile_token": "test-token"})
    assert response.status_code == 201, response.text
    data = response.json()
    c.headers["X-CSRF-Token"] = data["csrf_token"]
    return data


def test_hosted_requires_authentication(hosted):
    assert hosted.get("/api/v1/projects").status_code == 401
    assert hosted.get("/api/v1/runs/missing/events").status_code == 401
    assert hosted.get("/api/v1/health").status_code == 200


def test_accounts_csrf_ownership_logout_and_recovery(hosted, monkeypatch):
    # Production validates Turnstile with its provider; only that external boundary is replaced.
    import app.auth as auth
    async def challenge(*args):
        return None
    monkeypatch.setattr(auth, "verify_challenge", challenge)
    first = signup(hosted)
    cookie = hosted.cookies.get("__Host-rag-session")
    response = hosted.post("/api/v1/projects", json={"name": "Private"})
    assert response.status_code == 201, response.text
    project = response.json()["id"]
    assert hosted.post("/api/v1/projects", json={"name": "CSRF"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert hosted.post("/api/v1/auth/logout").status_code == 204
    assert hosted.get("/api/v1/projects").status_code == 401

    second = signup(hosted)
    assert first["user"]["id"] != second["user"]["id"]
    assert hosted.get("/api/v1/projects").json()["items"] == []
    assert hosted.get("/api/v1/projects/" + project).status_code == 404
    assert hosted.post(f"/api/v1/projects/{project}/sources/upload", files={"file": ("a.txt", b"private")}).status_code == 404
    recovery = hosted.post("/api/v1/auth/recover", json={"username": first["user"]["username"],
        "recovery_code": first["recovery_code"], "password": PASSWORD + " changed", "turnstile_token": "test-token"})
    assert recovery.status_code == 200, recovery.text
    assert recovery.json()["recovery_code"] != first["recovery_code"]
    assert hosted.post("/api/v1/auth/recover", json={"username": first["user"]["username"],
        "recovery_code": first["recovery_code"], "password": PASSWORD, "turnstile_token": "test-token"}).status_code == 401
    hosted.cookies.clear()
    hosted.cookies.set("__Host-rag-session", cookie)
    assert hosted.get("/api/v1/projects").status_code == 401


@pytest.fixture
def account(hosted, monkeypatch):
    import app.auth as auth
    async def challenge(*args):
        return None
    monkeypatch.setattr(auth, "verify_challenge", challenge)
    return signup(hosted)


def test_quota_failure_rolls_back_files_and_metadata(hosted, account):
    from app.models import Artifact
    from sqlalchemy import select, func
    settings = hosted.app.state.settings
    settings.max_projects_per_user = 1
    project = hosted.post("/api/v1/projects", json={"name": "First"}).json()["id"]
    assert hosted.post("/api/v1/projects", json={"name": "Second"}).status_code == 429
    settings.max_upload_bytes_per_user = 5
    response = hosted.post(f"/api/v1/projects/{project}/sources/upload", files={"file": ("a.txt", b"123456")})
    assert response.status_code == 429, response.text
    assert not list(settings.artifact_root.rglob("*.partial"))
    with hosted.app.state.store.session() as s:
        assert s.scalar(select(func.count()).select_from(Artifact).where(Artifact.project_id == project)) == 0


def test_keys_are_encrypted_isolated_and_do_not_change_fingerprints(hosted, account, monkeypatch):
    from app.auth import user_profiles
    from app.models import User
    from rag_runtime.providers import Profile
    monkeypatch.setenv("HOST_SECRET", "owners-environment-key")
    profile = Profile(id="answer", label="Answer", model="example", operations=["generation"],
        api_key_env="HOST_SECRET", max_output_tokens=512, tokenizer="cl100k_base")
    key = "sk-private-user-credential"
    assert hosted.put("/api/v1/me/openai-key", json={"api_key": key}).status_code == 204
    assert hosted.get("/api/v1/me/openai-key").json() == {"configured": True}
    with hosted.app.state.store.session() as s:
        user = s.get(User, account["user"]["id"])
        assert user.password_hash.startswith("$argon2id$")
        assert key not in user.encrypted_openai_key and PASSWORD not in user.password_hash
        private = user_profiles(hosted.app.state.settings, {"answer": profile}, user)["answer"]
        assert private.key == key
        assert private.fingerprint() == profile.fingerprint()
        assert key not in private.model_dump_json() and key not in repr(private)
    other = signup(hosted)
    with hosted.app.state.store.session() as s:
        assert user_profiles(hosted.app.state.settings, {"answer": profile}, s.get(User, other["user"]["id"]))["answer"].key == ""


def test_every_saved_resource_is_private(hosted, account):
    from tests.integration.test_export import completed_lane, export_lane
    worker, run, _ = completed_lane(hosted, "bm25")
    try:
        exported, _ = export_lane(hosted, worker, run)
        project, rid, lane = run["project_id"], run["id"], run["lanes"][0]
        source = hosted.get(f"/api/v1/projects/{project}/sources").json()["items"][0]
        signup(hosted)
        paths = [f"/projects/{project}", *[f"/projects/{project}/{name}" for name in
            ["sources", "corpus-versions", "configurations", "runs", "connections"]],
            f"/sources/{source['id']}", f"/sources/{source['id']}/content", f"/sources/{source['id']}/file",
            f"/sources/{source['id']}/impact", f"/jobs/{source['job_id']}",
            f"/corpus-versions/{run['corpus_version_id']}", f"/configurations/{lane['config_id']}",
            f"/index-bundles/{lane['bundle_id']}", f"/runs/{rid}", f"/runs/{rid}/events",
            f"/runs/{rid}/lanes/{lane['id']}/evidence", f"/exports/{exported['id']}",
            f"/exports/{exported['id']}/download"]
        for path in paths:
            assert hosted.get("/api/v1" + path).status_code == 404, path
        for path in [f"/runs/{rid}/cancel", f"/runs/{rid}/lanes/{lane['id']}/cancel", f"/jobs/{source['job_id']}/cancel"]:
            assert hosted.post("/api/v1" + path).status_code == 404, path
        assert hosted.delete(f"/api/v1/sources/{source['id']}", params={"cascade": "true", "confirmation_source_id": source['id']}).status_code == 404
    finally:
        worker.close()


def test_revoked_session_stops_an_existing_stream(hosted, account):
    import asyncio
    from types import SimpleNamespace
    from sqlalchemy import delete
    from app.auth import token_hash
    from app.models import AuthSession
    from app.runs import events
    from tests.integration.test_export import completed_lane
    worker, run, _ = completed_lane(hosted, "bm25")
    token = token_hash(hosted.cookies.get("__Host-rag-session"))
    store = hosted.app.state.store
    async def disconnected():
        return False
    request = SimpleNamespace(state=SimpleNamespace(store=store.for_user(account["user"]["id"], token)),
                              is_disconnected=disconnected)
    async def check():
        response = await events(run["id"], request, after_seq=0, last_event_id=None)
        iterator = response.body_iterator
        assert "event: trace" in await anext(iterator)
        with store.session() as s:
            s.execute(delete(AuthSession).where(AuthSession.token_hash == token))
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
    try:
        asyncio.run(check())
    finally:
        worker.close()


def test_login_password_change_expiry_and_rate_limit(hosted, account):
    from datetime import timedelta
    from app.models import AuthSession
    from app.auth import token_hash
    name = account["user"]["username"]
    assert hosted.post("/api/v1/auth/logout").status_code == 204
    def login(password):
        return hosted.post("/api/v1/auth/login", json={"username":name.upper(),"password":password,"turnstile_token":"test-token"})
    assert login("wrong").status_code == 401
    response = login(PASSWORD)
    assert response.status_code == 200
    hosted.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    old_cookie = hosted.cookies.get("__Host-rag-session")
    changed = hosted.post("/api/v1/auth/password", json={"current_password":PASSWORD, "password":PASSWORD+" new"})
    assert changed.status_code == 200, changed.text
    assert old_cookie != hosted.cookies.get("__Host-rag-session")
    store = hosted.app.state.store
    with store.session() as s:
        assert s.get(AuthSession, token_hash(old_cookie)) is None
        s.get(AuthSession, token_hash(hosted.cookies.get("__Host-rag-session"))).expires_at = store.now(s)-timedelta(seconds=1)
    assert hosted.get("/api/v1/projects").status_code == 401
    assert login(PASSWORD).status_code == 401
    assert login(PASSWORD+" new").status_code == 200
    assert login("wrong").status_code == 401
    assert login("wrong").status_code == 429


def test_hosted_profiles_only_send_keys_to_openai(hosted, tmp_path, monkeypatch):
    import yaml
    from rag_runtime.errors import Problem
    from rag_runtime.providers import load_profiles
    settings = hosted.app.state.settings.model_copy(update={"mode": "live"})
    path = tmp_path / "profiles.yaml"
    settings.profiles_path = path
    settings.provider_host_allowlist = ["api.openai.com", "proxy.example.test"]
    monkeypatch.setenv("OPENAI_API_KEY", "owner-environment-secret")
    profile = dict(id="answer", label="Answer", model="example", operations=["generation"],
                   api_key_env="OPENAI_API_KEY", max_output_tokens=512, tokenizer="cl100k_base")
    for endpoint in ["http://api.openai.com/v1", "https://proxy.example.test/v1", "https://api.openai.com:8443/v1"]:
        path.write_text(yaml.safe_dump({"profiles": [dict(profile, base_url=endpoint)]}))
        with pytest.raises(Problem):
            load_profiles(settings)
    path.write_text(yaml.safe_dump({"profiles": [dict(profile, base_url="https://api.openai.com/v1")]}))
    assert load_profiles(settings)["answer"].key == ""


def test_turnstile_and_origin_fail_closed(hosted, monkeypatch):
    import app.auth as auth
    import httpx
    data = {"success": False, "error-codes": ["timeout-or-duplicate"]}
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            return httpx.Response(200, json=data, request=httpx.Request("POST", url))
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: Client())
    body = dict(username="u"+uuid4().hex[:16], password=PASSWORD, turnstile_token="used-token")
    for data in [{"success": False}, {"success": True, "hostname": "wrong.test", "action": "register"},
                 {"success": True, "hostname": "rag.example.test", "action": "login"}, []]:
        assert hosted.post("/api/v1/auth/register", json=body).status_code == 403
    data = {"success": True, "hostname": "rag.example.test", "action": "register"}
    body["username"] = "u"+uuid4().hex[:16]
    hosted.headers.pop("Origin")
    assert hosted.post("/api/v1/auth/register", json=body).status_code == 403
    hosted.headers["Origin"] = ORIGIN
    response = hosted.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie


def test_concurrent_jobs_use_their_owners_keys(hosted, account, monkeypatch):
    import asyncio
    from app.models import Job
    from workers.main import Worker
    records = []
    for key in ["sk-private-first", "sk-private-second"]:
        hosted.put("/api/v1/me/openai-key", json={"api_key": key}).raise_for_status()
        project = hosted.post("/api/v1/projects", json={"name": "Isolated job"}).json()["id"]
        with hosted.app.state.store.session() as s:
            job = Job(project_id=project, kind="compare_run", resource_id=str(uuid4()))
            s.add(job)
            s.flush()
            records.append((job.id, project, key))
        signup(hosted)
    worker = Worker(hosted.app.state.settings)
    seen = {}
    async def compare(claim):
        await asyncio.sleep(.05)  # Both claims are alive before reading their credentials.
        seen[claim["project_id"]] = {p.key for p in claim["profiles"].values()}
    monkeypatch.setattr(worker, "compare", compare)
    async def run():
        await asyncio.gather(*(worker.run_once(id) for id, _, _ in records))
    try:
        asyncio.run(run())
        assert seen == {project: {key} for _, project, key in records}
        assert all(not p.key for p in worker.profiles.values())
    finally:
        worker.close()


def test_atomic_storage_queue_vector_and_disk_limits(hosted, account, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.auth import token_hash
    from app.models import Job
    from app.quotas import reserve_vectors
    from rag_runtime.errors import Problem
    from sqlalchemy import func, select
    settings, root = hosted.app.state.settings, hosted.app.state.store
    project = hosted.post("/api/v1/projects", json={"name": "Atomic limits"}).json()["id"]
    store = root.for_user(account["user"]["id"], token_hash(hosted.cookies.get("__Host-rag-session")))
    settings.max_upload_bytes_per_user = 5
    def upload(_):
        try:
            with store.session() as s:
                store.put(s, project, "raw_source", b"1234")
            return "stored"
        except Problem as error:
            return error.code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(upload, range(2))) == ["QUOTA_EXCEEDED", "stored"]
    settings.max_queued_per_user = 1
    with store.session() as s:
        s.add(Job(project_id=project, kind="ingest_source", resource_id=str(uuid4())))
    with pytest.raises(Problem, match="Your job queue"):
        with store.session() as s:
            s.add(Job(project_id=project, kind="ingest_source", resource_id=str(uuid4())))
    # Global admission includes jobs from other accounts, while deletion remains possible.
    with store.session() as s:
        settings.max_queued_jobs = s.scalar(select(func.count()).select_from(Job).where(Job.status == "queued", Job.kind != "delete_source"))
    signup(hosted)
    other = hosted.post("/api/v1/projects", json={"name": "Global queue"}).json()["id"]
    with pytest.raises(Problem, match="The job queue"):
        with root.session() as s:
            s.add(Job(project_id=other, kind="ingest_source", resource_id=str(uuid4())))
    with root.session() as s:
        s.add(Job(project_id=other, kind="delete_source", resource_id=str(uuid4())))
    settings.max_queued_jobs, settings.max_queued_per_user = 256, 64
    settings.max_vectors_per_user = 10
    with root.session() as s:
        first = Job(project_id=project, kind="prepare_index", resource_id=str(uuid4()), status="succeeded", progress={"vector_dimensions":64})
        s.add(first)
        s.flush()
        reserve_vectors(root, s, first, 8)
    with pytest.raises(Problem, match="Your vector limit"):
        with root.session() as s:
            second = Job(project_id=project, kind="prepare_index", resource_id=str(uuid4()), status="succeeded", progress={"vector_dimensions":64})
            s.add(second)
            s.flush()
            reserve_vectors(root, s, second, 8)
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type("Usage", (), {"free": 0})())
    settings.min_free_bytes = 1
    assert hosted.post("/api/v1/projects", json={"name": "No disk"}).status_code == 503
