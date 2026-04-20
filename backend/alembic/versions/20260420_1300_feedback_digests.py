"""feedback_digests table for weekly trend summaries

Revision ID: 5a8b2c4d6e1f
Revises: 4f9c1e7b3d2a
Create Date: 2026-04-20 13:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "5a8b2c4d6e1f"
down_revision: Union[str, None] = "4f9c1e7b3d2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_digests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "app_id",
            sa.Integer(),
            sa.ForeignKey("feedback_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "previous_report_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("clusters_json", sa.JSON(), nullable=True),
        sa.Column("top_files_json", sa.JSON(), nullable=True),
        sa.Column("severity_breakdown_json", sa.JSON(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("app_id", "period_start", name="uq_digest_period"),
    )
    op.create_index(
        "ix_feedback_digests_app_id",
        "feedback_digests",
        ["app_id"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_digests_period_start",
        "feedback_digests",
        ["period_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feedback_digests_period_start", table_name="feedback_digests"
    )
    op.drop_index("ix_feedback_digests_app_id", table_name="feedback_digests")
    op.drop_table("feedback_digests")
