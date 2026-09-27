"""Keep background browser workers away from Python integration-test jobs."""

import os
import psycopg
import uvicorn
from tests.conftest import prepare_database

prepare_database(os.environ["RAG_DATABASE_URL"])
with psycopg.connect("host=127.0.0.1 port=6544 user=rag password=local-development-only dbname=ragplayground_browser_test", autocommit=True) as db:
    if not db.execute("SELECT 1 FROM pg_roles WHERE rolname='rag_browser_reader'").fetchone():
        db.execute("CREATE ROLE rag_browser_reader LOGIN PASSWORD 'browser-fixture-only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
    db.execute("CREATE SCHEMA IF NOT EXISTS browser_fixture")
    db.execute("CREATE TABLE IF NOT EXISTS browser_fixture.notes (id integer PRIMARY KEY, body text NOT NULL)")
    db.execute("INSERT INTO browser_fixture.notes VALUES (1, 'NEBULA-42 means clock drift. Synchronize the system clock.') ON CONFLICT (id) DO NOTHING")
    db.execute("GRANT USAGE ON SCHEMA browser_fixture TO rag_browser_reader")
    db.execute("GRANT SELECT (id, body) ON browser_fixture.notes TO rag_browser_reader")
uvicorn.run("app.main:app", host="127.0.0.1", port=8781, access_log=False)
