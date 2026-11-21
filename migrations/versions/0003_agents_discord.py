"""Agents: agent_run table, and 'discord' as a platform (channels the user's own bot is invited to).

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

OLD = ("telegram", "x", "facebook", "tiktok", "youtube", "news", "mirror", "official", "restricted", "reddit")
NEW = OLD + ("discord",)


def _platforms(values: tuple) -> None:
    for table in ("source", "signal"):
        op.drop_constraint(f"ck_{table}_platform", table, type_="check")
        op.create_check_constraint(f"ck_{table}_platform", table, f"platform IN {values}")


def upgrade() -> None:
    _platforms(NEW)
    op.create_table(
        "agent_run",
        sa.Column("run_id", sa.String, primary_key=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("topic", sa.Text),
        sa.Column("source_ids", ARRAY(sa.String)),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("origin", sa.String, nullable=False, server_default="agents-page"),
        sa.Column("stats", JSONB),
        sa.Column("signal_ids", ARRAY(sa.String)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_run_created_at", "agent_run", ["created_at"])


def downgrade() -> None:
    op.drop_table("agent_run")
    op.execute("DELETE FROM signal WHERE platform = 'discord'")
    op.execute("DELETE FROM source WHERE platform = 'discord'")
    _platforms(OLD)
