"""monitoring_events gets resolved_at + resolution_status

Closes the loop: when the TriageCard a monitoring event correlated to
reaches a terminal state (approved -> "posted", or "skipped"), the
event is stamped resolved so the monitoring view shows the underlying
issue was triaged rather than looking permanently outstanding.

Revision ID: f4d5e6a7b8c9
Revises: f3c4d5e6a7b8
Create Date: 2026-04-21 12:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4d5e6a7b8c9"
down_revision: Union[str, None] = "f3c4d5e6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitoring_events", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "monitoring_events", sa.Column("resolution_status", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("monitoring_events", "resolution_status")
    op.drop_column("monitoring_events", "resolved_at")
