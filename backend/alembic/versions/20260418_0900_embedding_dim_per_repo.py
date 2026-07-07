"""embedding dim per repo

Phase 6. Per-repo embedding dimension so users can pick OpenAI (1536),
Google / Ollama (768), or Voyage (1024, future). Until a repo is indexed
embedding_model/dim are NULL.

The existing embedding column on ``code_chunks`` and ``issue_embeddings``
is renamed to ``embedding_1536`` and made nullable. A second column
``embedding_768`` is added. A CHECK constraint enforces that exactly one
of the two is populated per row.

Revision ID: 6e5b2c1a77f1
Revises: 6ab0cf25a729
Create Date: 2026-04-18 09:00:00+00:00

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "6e5b2c1a77f1"
down_revision: Union[str, None] = "6ab0cf25a729"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("repos", sa.Column("embedding_model", sa.String(length=128), nullable=True))
    op.add_column("repos", sa.Column("embedding_dim", sa.Integer(), nullable=True))

    for table in ("code_chunks", "issue_embeddings"):
        op.alter_column(table, "embedding", new_column_name="embedding_1536", nullable=True)
        op.add_column(table, sa.Column("embedding_768", sa.JSON(), nullable=True))

        op.create_check_constraint(
            f"ck_{table}_embedding_xor",
            table,
            "((embedding_1536 IS NOT NULL)::int + (embedding_768 IS NOT NULL)::int) = 1",
        )

        # JSON-based embeddings do not need a special index for local development.


def downgrade() -> None:
    for table in ("code_chunks", "issue_embeddings"):
        op.drop_constraint(f"ck_{table}_embedding_xor", table, type_="check")
        op.drop_column(table, "embedding_768")
        op.alter_column(table, "embedding_1536", new_column_name="embedding", nullable=False)

    op.drop_column("repos", "embedding_dim")
    op.drop_column("repos", "embedding_model")
