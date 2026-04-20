"""triage_cards.pii_redacted_json — counts of PII scrubbed pre-LLM

Revision ID: a7f3d8e0c5b9
Revises: 9e6a1b4c2d8f
Create Date: 2026-04-20 18:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7f3d8e0c5b9"
down_revision: Union[str, None] = "9e6a1b4c2d8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "triage_cards",
        sa.Column("pii_redacted_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_cards", "pii_redacted_json")
