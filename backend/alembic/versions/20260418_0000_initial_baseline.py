"""initial baseline

Empty baseline so later migrations have a root to chain onto. The pgvector
extension is enabled here because Phase 2 onward will create vector columns.

Revision ID: 0000_baseline
Revises:
Create Date: 2026-04-18

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0000_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    has_vector = bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
    )
    if not has_vector:
        raise RuntimeError(
            "PostgreSQL is missing the pgvector extension. "
            "Install pgvector on the PostgreSQL server before running migrations. "
            "For local Windows installs, build/install pgvector with PGROOT set to "
            "your PostgreSQL installation directory, then rerun alembic upgrade head."
        )
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
