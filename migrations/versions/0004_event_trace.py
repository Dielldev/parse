"""Tracer (A12): keep each trace's seed and full result on its Event, so a trace can be reopened as it was run.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event", sa.Column("seed", JSONB))
    op.add_column("event", sa.Column("trace", JSONB))
    op.create_index("ix_event_created_at", "event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_event_created_at", "event")
    op.drop_column("event", "trace")
    op.drop_column("event", "seed")
