"""Embedding column 768 -> 1024 for Qwen/Qwen3-Embedding-0.6B; clear NLLB translations (model switch).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE signal SET embedding = NULL")
    op.execute("ALTER TABLE signal ALTER COLUMN embedding TYPE vector(1024)")
    # Translations made earlier with NLLB are dropped so the corpus has one translation model (Qwen3-4B).
    op.execute("UPDATE signal SET text_en = NULL")


def downgrade() -> None:
    op.execute("UPDATE signal SET embedding = NULL")
    op.execute("ALTER TABLE signal ALTER COLUMN embedding TYPE vector(768)")
