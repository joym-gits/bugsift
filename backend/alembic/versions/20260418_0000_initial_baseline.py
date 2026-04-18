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

revision: str = "0000_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
