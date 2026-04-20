"""triage_cards.sla_minutes + sla_breach_alerted_at

Revision ID: c4a9e2f7b3d8
Revises: b2e8f4c9a1d6
Create Date: 2026-04-20 19:30:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4a9e2f7b3d8"
down_revision: Union[str, None] = "b2e8f4c9a1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "triage_cards",
        sa.Column("sla_minutes", sa.Integer, nullable=True),
    )
    op.add_column(
        "triage_cards",
        sa.Column("sla_breach_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index so the SLA-watch worker's "who's breaching next"
    # scan stays cheap even as the card table grows. We only care
    # about cards that still have an unbreached SLA.
    op.create_index(
        "ix_triage_cards_pending_sla",
        "triage_cards",
        ["sla_minutes"],
        postgresql_where=sa.text(
            "status = 'pending' AND sla_minutes IS NOT NULL AND sla_breach_alerted_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_triage_cards_pending_sla", table_name="triage_cards")
    op.drop_column("triage_cards", "sla_breach_alerted_at")
    op.drop_column("triage_cards", "sla_minutes")
