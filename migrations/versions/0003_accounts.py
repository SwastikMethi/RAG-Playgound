"""Hosted accounts; legacy unowned projects remain local-only."""
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.execute("CREATE TABLE users (id VARCHAR(128) PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL, username VARCHAR(32) NOT NULL UNIQUE, password_hash TEXT NOT NULL, recovery_hash VARCHAR(64) NOT NULL, encrypted_openai_key TEXT)")
    op.execute("ALTER TABLE projects ADD COLUMN owner_id VARCHAR(128) REFERENCES users(id)")
    op.execute("CREATE INDEX ix_projects_owner_id ON projects(owner_id)")
    op.execute("CREATE TABLE auth_sessions (token_hash VARCHAR(64) PRIMARY KEY, user_id VARCHAR(128) NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TIMESTAMPTZ NOT NULL)")
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions(user_id)")
    op.execute("CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions(expires_at)")
    op.execute("CREATE TABLE auth_rates (bucket VARCHAR(64) PRIMARY KEY, attempts INTEGER NOT NULL, expires_at TIMESTAMPTZ NOT NULL)")
    op.execute("CREATE INDEX ix_auth_rates_expires_at ON auth_rates(expires_at)")


def downgrade():
    op.execute("DROP TABLE auth_rates")
    op.execute("DROP TABLE auth_sessions")
    op.execute("ALTER TABLE projects DROP COLUMN owner_id")
    op.execute("DROP TABLE users")
