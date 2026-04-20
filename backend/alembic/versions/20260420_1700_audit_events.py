"""audit_events — append-only record of security/ops-relevant actions

Revision ID: 9e6a1b4c2d8f
Revises: 8d5f0c3a1e7b
Create Date: 2026-04-20 17:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "9e6a1b4c2d8f"
down_revision: Union[str, None] = "8d5f0c3a1e7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "actor_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # actor_login is denormalised so a deleted user still shows "who"
        # in the audit trail. For system events (e.g. webhook processing)
        # this is "system".
        sa.Column("actor_login", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False, index=True),
        sa.Column("target_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("target_id", sa.String(length=64), nullable=True, index=True),
        sa.Column("summary", sa.String(length=256), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.Column("request_ua", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )
    # Composite index for the common "who did what recently" query.
    op.create_index(
        "ix_audit_actor_created",
        "audit_events",
        ["actor_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_actor_created", table_name="audit_events")
    op.drop_table("audit_events")
