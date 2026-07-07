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

revision: str = "c3d7a9b1e2f5"
down_revision: Union[str, None] = "b2e9f1a8c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("feedback_reports", sa.Column("embedding_384", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback_reports", "embedding_384")
