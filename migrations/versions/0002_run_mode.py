"""Persist fixture provenance so a later live server cannot relabel old answers."""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.execute("ALTER TABLE runs ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'live'")
    op.execute(
        "UPDATE runs SET mode='fixture' WHERE EXISTS (SELECT 1 FROM lanes WHERE lanes.run_id=runs.id AND lanes.config_snapshot->'generation'->>'model' LIKE 'fixture-%')"
    )


def downgrade():
    op.execute("ALTER TABLE runs DROP COLUMN mode")
