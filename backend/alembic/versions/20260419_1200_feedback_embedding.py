"""feedback_reports.embedding_384 for near-duplicate report collapsing

Revision ID: c3d7a9b1e2f5
Revises: b2e9f1a8c4d6
Create Date: 2026-04-19 12:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "c3d7a9b1e2f5"
down_revision: Union[str, None] = "b2e9f1a8c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feedback_reports", sa.Column("embedding_384", Vector(384), nullable=True)
    )
    op.execute(
        "CREATE INDEX ix_feedback_reports_embedding_384 ON feedback_reports "
        "USING ivfflat (embedding_384 vector_cosine_ops) WITH (lists = 100) "
        "WHERE embedding_384 IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_feedback_reports_embedding_384")
    op.drop_column("feedback_reports", "embedding_384")
