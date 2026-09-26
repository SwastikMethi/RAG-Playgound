import os
from alembic import context
from sqlalchemy import create_engine
from app.models import Base

url = os.environ.get("RAG_DATABASE_URL", "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground")
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
