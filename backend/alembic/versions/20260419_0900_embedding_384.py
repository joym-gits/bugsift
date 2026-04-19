"""Add 384-dim embedding column for built-in local (fastembed) provider.

Revision ID: 9c3d4f8a1b2e
Revises: 7fa2d13c88e1
Create Date: 2026-04-19 09:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "9c3d4f8a1b2e"
down_revision: Union[str, None] = "7fa2d13c88e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("code_chunks", "issue_embeddings"):
        op.add_column(table, sa.Column("embedding_384", Vector(384), nullable=True))
        # Broaden the XOR: exactly one of the three dim columns must be populated.
        op.drop_constraint(f"ck_{table}_embedding_xor", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_embedding_xor",
            table,
            "((embedding_1536 IS NOT NULL)::int + (embedding_768 IS NOT NULL)::int "
            "+ (embedding_384 IS NOT NULL)::int) = 1",
        )
        op.execute(
            f"CREATE INDEX ix_{table}_embedding_384 ON {table} "
            "USING ivfflat (embedding_384 vector_cosine_ops) WITH (lists = 100) "
            "WHERE embedding_384 IS NOT NULL"
        )


def downgrade() -> None:
    for table in ("issue_embeddings", "code_chunks"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_384")
        op.drop_constraint(f"ck_{table}_embedding_xor", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_embedding_xor",
            table,
            "((embedding_1536 IS NOT NULL)::int + (embedding_768 IS NOT NULL)::int) = 1",
        )
        op.drop_column(table, "embedding_384")
