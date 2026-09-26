"""Use a separate database and artifact directory; never clear development data."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground_test")


@pytest.fixture(scope="session", autouse=True)
def database_schema(request):
    if not any(item.get_closest_marker("integration") for item in request.session.items):
        return
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url
    url = make_url(TEST_URL)
    assert url.database.endswith("_test"), "Integration tests require a dedicated *_test database."
    with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password,
                         dbname="postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (url.database,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))
    env = dict(os.environ, RAG_DATABASE_URL=TEST_URL,
               PYTHONPATH=str(Path("packages").resolve()) + os.pathsep + str(Path("apps/api").resolve()))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
