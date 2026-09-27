import asyncio
import json
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg import sql
from pydantic import SecretStr

from app.models import Connection
from tests.conftest import TEST_URL
from tests.integration.test_api import client as client

pytestmark = pytest.mark.integration


@pytest.fixture
def database_source(client, request):
    from sqlalchemy.engine import make_url

    url = make_url(TEST_URL)
    schema = "source_" + uuid4().hex
    role = "reader_" + uuid4().hex
    password = "private-test-password"
    relation = 'notes"; SELECT 1; --'
    admin = psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        autocommit=True,
    )
    admin.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password))
    )

    def cleanup():
        try:
            admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        finally:
            admin.close()

    request.addfinalizer(cleanup)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    admin.execute(
        sql.SQL(
            "CREATE TABLE {} (tenant int NOT NULL, id int NOT NULL, body text, optional text, hidden text, PRIMARY KEY (tenant,id))"
        ).format(sql.Identifier(schema, relation))
    )
    admin.execute(
        sql.SQL("INSERT INTO {} VALUES (1,1,%s,NULL,%s),(1,2,%s,%s,%s),(2,1,NULL,NULL,%s)").format(
            sql.Identifier(schema, relation)
        ),
        (
            "NEBULA-42 means clock drift.",
            "excluded secret",
            "Clock synchronization repairs drift.",
            "Additional instructions.",
            "excluded secret",
            "excluded secret",
        ),
    )
    admin.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role))
    )
    admin.execute(
        sql.SQL("GRANT SELECT (tenant,id,body,optional) ON {} TO {}").format(
            sql.Identifier(schema, relation), sql.Identifier(role)
        )
    )
    settings = client.app.state.settings
    settings.master_key = SecretStr(Fernet.generate_key().decode())
    settings.database_host_allowlist = ["127.0.0.1"]
    settings.database_relation_allowlist = [
        dict(
            host="127.0.0.1",
            port=url.port,
            database=url.database,
            schema=schema,
            relation=relation,
            columns=["tenant", "id", "body", "optional"],
        )
    ]
    project = client.post("/api/v1/projects", json={"name": "Frozen database text"}).json()["id"]
    body = dict(
        name="Read only source",
        host="127.0.0.1",
        port=url.port,
        database=url.database,
        username=role,
        password=password,
        ssl_mode="disable",
        allowed_schemas=[schema],
    )
    yield dict(project=project, body=body, admin=admin, schema=schema, relation=relation, password=password)


def selection(connection, source):
    return dict(
        connection_id=connection["id"],
        schema=source["schema"],
        relation=source["relation"],
        key_columns=["tenant", "id"],
        text_columns=["body", "optional"],
        updated_at_column=None,
        max_rows=10000,
        display_name="Frozen notes",
    )


def test_encrypted_scoped_snapshot_preview_and_queries_do_not_reconnect(client, database_source, monkeypatch):
    from workers.main import Worker

    d = database_source
    response = client.post(f"/api/v1/projects/{d['project']}/connections", json=d["body"])
    assert response.status_code == 201, response.text
    connection = response.json()
    assert d["password"] not in response.text
    with client.app.state.store.session() as s:
        row = s.get(Connection, connection["id"])
        assert d["password"] not in row.encrypted_secret and row.encrypted_secret
    relations = client.get(f"/api/v1/connections/{connection['id']}/relations")
    assert relations.status_code == 200, relations.text
    assert len(relations.json()["items"]) == 1
    assert "hidden" not in [c["name"] for c in relations.json()["items"][0]["columns"]]
    assert relations.json()["items"][0]["suggested_key_columns"] == ["tenant", "id"]
    request = selection(connection, d)
    preview = client.post(f"/api/v1/connections/{connection['id']}/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows"][0]["key"] == {"tenant": 1, "id": 1}
    assert "NULL" in preview.json()["rows"][0]["text"] and "excluded secret" not in preview.text
    wrong = dict(request, text_columns=["hidden"])
    assert client.post(f"/api/v1/connections/{connection['id']}/preview", json=wrong).status_code == 422
    other = client.post("/api/v1/projects", json={"name": "Other"}).json()["id"]
    assert client.post(f"/api/v1/projects/{other}/sources/postgres", json=request).status_code == 404
    captured = client.post(f"/api/v1/projects/{d['project']}/sources/postgres", json=request)
    assert captured.status_code == 202, captured.text
    source = captured.json()
    worker = Worker(client.app.state.settings)
    asyncio.run(worker.run_resource(source["id"]))
    saved = client.get("/api/v1/sources/" + source["id"]).json()
    assert saved["status"] == "ready", saved
    assert saved["metadata"]["skipped_empty_records"] == 1
    d["admin"].execute(
        sql.SQL("UPDATE {} SET body=%s WHERE tenant=1 AND id=1").format(
            sql.Identifier(d["schema"], d["relation"])
        ),
        ("Changed after capture",),
    )
    refresh = client.post(f"/api/v1/projects/{d['project']}/sources/postgres", json=request).json()
    assert refresh["id"] != source["id"]
    asyncio.run(worker.run_resource(refresh["id"]))
    assert "Changed after capture" in client.get(f"/api/v1/sources/{refresh['id']}/content").json()["content"]
    assert "clock drift" in client.get(f"/api/v1/sources/{source['id']}/content").json()["content"]
    assert (
        "snapshot.json" in client.get(f"/api/v1/sources/{source['id']}/file").headers["content-disposition"]
    )
    # The source remains useful after deleting its credentials entirely.
    assert client.delete("/api/v1/connections/" + connection["id"]).status_code == 204
    corpus = client.post(
        f"/api/v1/projects/{d['project']}/corpus-versions", json={"source_ids": [source["id"]]}
    ).json()
    cfg = client.get("/api/v1/system/capabilities").json()["items"][0]["default_config"]
    config = client.post(
        f"/api/v1/projects/{d['project']}/configurations", json={"name": "BM25", "config": cfg}
    ).json()
    bundle = client.post(
        f"/api/v1/projects/{d['project']}/preparations",
        json={"corpus_version_id": corpus["id"], "config_id": config["id"]},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    asyncio.run(worker.run_resource(bundle["id"]))
    run = client.post(
        f"/api/v1/projects/{d['project']}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json=dict(
            corpus_version_id=corpus["id"],
            question="What is NEBULA-42?",
            lanes=[dict(config_id=config["id"], bundle_id=bundle["id"])],
        ),
    ).json()
    asyncio.run(worker.run_resource(run["id"]))
    result = client.get("/api/v1/runs/" + run["id"]).json()
    assert result["status"] == "completed", result
    evidence = client.get(f"/api/v1/runs/{run['id']}/lanes/{result['lanes'][0]['id']}/evidence").json()[
        "evidence"
    ]
    assert evidence[0]["location"]["record_key"] == {"tenant": 1, "id": 1}
    assert "clock drift" in evidence[0]["excerpt"] and "Changed after capture" not in json.dumps(evidence)
    from tests.integration.test_export import export_lane

    exported, archive = export_lane(client, worker, result, include_data=True)
    assert exported["manifest"]["source_hashes"][0]["source_format"] == "postgres_snapshot"
    worker.close()


def test_keys_row_limits_read_only_policy_and_missing_master_key(client, database_source):
    d = database_source
    response = client.post(f"/api/v1/projects/{d['project']}/connections", json=d["body"])
    assert response.status_code == 201, response.text
    connection = response.json()
    request = selection(connection, d)
    response = client.post(
        f"/api/v1/connections/{connection['id']}/preview", json=dict(request, key_columns=["tenant"])
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "UNSTABLE_KEY"
    response = client.post(
        f"/api/v1/connections/{connection['id']}/preview", json=dict(request, key_columns=["optional"])
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "UNSTABLE_KEY"
    response = client.post(f"/api/v1/connections/{connection['id']}/preview", json=dict(request, max_rows=1))
    assert response.status_code == 200 and response.json()["truncated"]
    d["admin"].execute(
        sql.SQL("GRANT UPDATE ON {} TO {}").format(
            sql.Identifier(d["schema"], d["relation"]), sql.Identifier(d["body"]["username"])
        )
    )
    denied_write = client.post(f"/api/v1/connections/{connection['id']}/preview", json=request)
    assert (
        denied_write.status_code == 422 and denied_write.json()["error"]["code"] == "READ_ONLY_ROLE_REQUIRED"
    )
    client.app.state.settings.master_key = SecretStr("")
    denied = client.post(f"/api/v1/projects/{d['project']}/connections", json=d["body"])
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "MASTER_KEY_REQUIRED"


@pytest.mark.asyncio
async def test_repeatable_read_statement_deadline_and_byte_cap(client, database_source):
    from rag_runtime.postgres_source import database, capture
    from rag_runtime.errors import Problem

    d = database_source
    config = d["body"]
    async with database(config, d["password"], ["127.0.0.1"]) as conn:
        isolation = await (
            await conn.execute(
                "SELECT current_setting('transaction_isolation') AS isolation,current_setting('transaction_read_only') AS readonly"
            )
        ).fetchone()
        assert isolation == dict(isolation="repeatable read", readonly="on")
        query = sql.SQL("SELECT body FROM {} WHERE tenant=1 AND id=1").format(
            sql.Identifier(d["schema"], d["relation"])
        )
        before = await (await conn.execute(query)).fetchone()
        d["admin"].execute(
            sql.SQL("UPDATE {} SET body=%s WHERE tenant=1 AND id=1").format(
                sql.Identifier(d["schema"], d["relation"])
            ),
            ("Changed concurrently",),
        )
        assert await (await conn.execute(query)).fetchone() == before
    with pytest.raises(Problem, match="database operation"):
        async with database(config, d["password"], ["127.0.0.1"]) as conn:
            await conn.execute("SET LOCAL statement_timeout='1ms'")
            await conn.execute("SELECT pg_sleep(.1)")
    connection = {"id": "unused"}
    snapshot = await capture(
        config,
        d["password"],
        ["127.0.0.1"],
        client.app.state.settings.database_relation_allowlist,
        selection(connection, d),
        max_bytes=220,
    )
    assert snapshot["raw"]["truncated"] and len(snapshot["raw"]["rows"]) == 1
    assert "Changed concurrently" in snapshot["parsed"]["text"]
