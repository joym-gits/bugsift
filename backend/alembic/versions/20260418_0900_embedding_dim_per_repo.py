"""embedding dim per repo

Phase 6. Per-repo embedding dimension so users can pick OpenAI (1536),
Google / Ollama (768), or Voyage (1024, future). Until a repo is indexed
embedding_model/dim are NULL.

The existing ``embedding vector(1536)`` column on ``code_chunks`` and
``issue_embeddings`` is renamed to ``embedding_1536`` and made nullable. A
second column ``embedding_768 vector(768)`` is added. A CHECK constraint
enforces that exactly one of the two is populated per row.

Revision ID: 6e5b2c1a77f1
Revises: 6ab0cf25a729
Create Date: 2026-04-18 09:00:00+00:00

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "6e5b2c1a77f1"
down_revision: Union[str, None] = "6ab0cf25a729"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("repos", sa.Column("embedding_model", sa.String(length=128), nullable=True))
    op.add_column("repos", sa.Column("embedding_dim", sa.Integer(), nullable=True))

    for table in ("code_chunks", "issue_embeddings"):
        # Drop the ivfflat index from phase 2 before altering the column.
        if table == "code_chunks":
            op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding")
        else:
            op.execute("DROP INDEX IF EXISTS ix_issue_embeddings_embedding")

        op.alter_column(table, "embedding", new_column_name="embedding_1536", nullable=True)
        op.add_column(table, sa.Column("embedding_768", Vector(768), nullable=True))

        op.create_check_constraint(
            f"ck_{table}_embedding_xor",
            table,
            "((embedding_1536 IS NOT NULL)::int + (embedding_768 IS NOT NULL)::int) = 1",
        )

        op.execute(
            f"CREATE INDEX ix_{table}_embedding_1536 ON {table} "
            "USING ivfflat (embedding_1536 vector_cosine_ops) WITH (lists = 100) "
            "WHERE embedding_1536 IS NOT NULL"
        )
        op.execute(
            f"CREATE INDEX ix_{table}_embedding_768 ON {table} "
            "USING ivfflat (embedding_768 vector_cosine_ops) WITH (lists = 100) "
            "WHERE embedding_768 IS NOT NULL"
        )


def downgrade() -> None:
    for table in ("code_chunks", "issue_embeddings"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_1536")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_768")
        op.drop_constraint(f"ck_{table}_embedding_xor", table, type_="check")
        op.drop_column(table, "embedding_768")
        op.alter_column(table, "embedding_1536", new_column_name="embedding", nullable=False)
        if table == "code_chunks":
            op.execute(
                "CREATE INDEX ix_code_chunks_embedding ON code_chunks "
                "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
            )
        else:
            op.execute(
                "CREATE INDEX ix_issue_embeddings_embedding ON issue_embeddings "
                "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
            )

    op.drop_column("repos", "embedding_dim")
    op.drop_column("repos", "embedding_model")
