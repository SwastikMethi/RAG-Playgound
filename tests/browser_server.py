"""Keep background browser workers away from Python integration-test jobs."""

import os
import uvicorn
from tests.conftest import prepare_database

prepare_database(os.environ["RAG_DATABASE_URL"])
uvicorn.run("app.main:app", host="127.0.0.1", port=8781, access_log=False)
