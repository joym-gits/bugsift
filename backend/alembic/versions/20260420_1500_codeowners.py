"""repos.codeowners_text + triage_cards.suggested_assignees_json

Revision ID: 7c4e9d2b5f1a
Revises: 6b3d5e7f9c2a
Create Date: 2026-04-20 15:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c4e9d2b5f1a"
down_revision: Union[str, None] = "6b3d5e7f9c2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repos", sa.Column("codeowners_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "repos",
        sa.Column(
            "codeowners_fetched_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "triage_cards",
        sa.Column("suggested_assignees_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_cards", "suggested_assignees_json")
    op.drop_column("repos", "codeowners_fetched_at")
    op.drop_column("repos", "codeowners_text")
