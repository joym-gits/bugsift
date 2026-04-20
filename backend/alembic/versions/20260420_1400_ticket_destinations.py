"""ticket_destinations + generic ticket linkage on triage_cards

Revision ID: 6b3d5e7f9c2a
Revises: 5a8b2c4d6e1f
Create Date: 2026-04-20 14:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "6b3d5e7f9c2a"
down_revision: Union[str, None] = "5a8b2c4d6e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_destinations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("auth_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column(
            "config_json",
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
        sa.UniqueConstraint("user_id", "name", name="uq_ticket_dest_name"),
    )
    op.create_index(
        "ix_ticket_destinations_user_id",
        "ticket_destinations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ticket_destinations_provider",
        "ticket_destinations",
        ["provider"],
        unique=False,
    )

    op.add_column(
        "feedback_apps",
        sa.Column(
            "ticket_destination_id",
            sa.Integer(),
            sa.ForeignKey("ticket_destinations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.add_column(
        "triage_cards",
        sa.Column("ticket_provider", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "triage_cards",
        sa.Column("ticket_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "triage_cards",
        sa.Column("ticket_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_cards", "ticket_url")
    op.drop_column("triage_cards", "ticket_key")
    op.drop_column("triage_cards", "ticket_provider")
    op.drop_column("feedback_apps", "ticket_destination_id")
    op.drop_index(
        "ix_ticket_destinations_provider", table_name="ticket_destinations"
    )
    op.drop_index(
        "ix_ticket_destinations_user_id", table_name="ticket_destinations"
    )
    op.drop_table("ticket_destinations")
