"""slack_destinations table for incoming-webhook notifications

Revision ID: 2b4c6d8e9a1f
Revises: e5c9d3b7f2a1
Create Date: 2026-04-20 10:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "2b4c6d8e9a1f"
down_revision: Union[str, None] = "e5c9d3b7f2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slack_destinations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("webhook_url_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("channel_hint", sa.String(length=120), nullable=True),
        sa.Column(
            "events_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_slack_dest_name"),
    )
    op.create_index(
        "ix_slack_destinations_user_id",
        "slack_destinations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_slack_destinations_user_id", table_name="slack_destinations"
    )
    op.drop_table("slack_destinations")
