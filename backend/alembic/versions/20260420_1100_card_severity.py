"""triage_cards.severity column

Revision ID: 3d7f2a1c5e9b
Revises: 2b4c6d8e9a1f
Create Date: 2026-04-20 11:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "3d7f2a1c5e9b"
down_revision: Union[str, None] = "2b4c6d8e9a1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "triage_cards",
        sa.Column("severity", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_triage_cards_severity",
        "triage_cards",
        ["severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_triage_cards_severity", table_name="triage_cards")
    op.drop_column("triage_cards", "severity")
