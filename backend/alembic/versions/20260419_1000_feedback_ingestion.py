"""feedback ingestion: apps + reports tables for the widget SDK

Revision ID: a1b8d2f4c6e7
Revises: 9c3d4f8a1b2e
Create Date: 2026-04-19 10:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b8d2f4c6e7"
down_revision: Union[str, None] = "9c3d4f8a1b2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_apps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("allowed_origins_json", sa.JSON(), nullable=True),
        sa.Column(
            "default_repo_id",
            sa.Integer(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_feedback_apps_user_id", "feedback_apps", ["user_id"], unique=False
    )
    op.create_index(
        "ix_feedback_apps_public_key", "feedback_apps", ["public_key"], unique=True
    )

    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "app_id",
            sa.Integer(),
            sa.ForeignKey("feedback_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("triage_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("app_version", sa.String(length=120), nullable=True),
        sa.Column("console_log", sa.Text(), nullable=True),
        sa.Column("screenshot_url", sa.Text(), nullable=True),
        sa.Column("reporter_hash", sa.String(length=64), nullable=True),
        sa.Column("client_meta_json", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("ingest_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_feedback_reports_app_id", "feedback_reports", ["app_id"], unique=False
    )
    op.create_index(
        "ix_feedback_reports_card_id", "feedback_reports", ["card_id"], unique=False
    )
    op.create_index(
        "ix_feedback_reports_reporter_hash",
        "feedback_reports",
        ["reporter_hash"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_reports_content_hash",
        "feedback_reports",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_reports_app_created",
        "feedback_reports",
        ["app_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_reports_app_created", table_name="feedback_reports")
    op.drop_index("ix_feedback_reports_content_hash", table_name="feedback_reports")
    op.drop_index("ix_feedback_reports_reporter_hash", table_name="feedback_reports")
    op.drop_index("ix_feedback_reports_card_id", table_name="feedback_reports")
    op.drop_index("ix_feedback_reports_app_id", table_name="feedback_reports")
    op.drop_table("feedback_reports")
    op.drop_index("ix_feedback_apps_public_key", table_name="feedback_apps")
    op.drop_index("ix_feedback_apps_user_id", table_name="feedback_apps")
    op.drop_table("feedback_apps")
