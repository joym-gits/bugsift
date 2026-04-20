"""triage_rules — operator-defined routing + SLA rules

Revision ID: b2e8f4c9a1d6
Revises: a7f3d8e0c5b9
Create Date: 2026-04-20 19:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bugsift.db.types import JSONB

revision: str = "b2e8f4c9a1d6"
down_revision: Union[str, None] = "a7f3d8e0c5b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "triage_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        # Lower priority number runs earlier. 100 is the default; rules
        # are matched in priority ASC, id ASC order so operators can
        # reorder deterministically.
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("match_json", JSONB, nullable=False),
        sa.Column("action_json", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_triage_rules_user_priority",
        "triage_rules",
        ["user_id", "priority", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_triage_rules_user_priority", table_name="triage_rules")
    op.drop_table("triage_rules")
