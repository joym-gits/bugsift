"""push_events + triage_cards.regression_suspects_json

Revision ID: e5c9d3b7f2a1
Revises: d4f8b1c2e3a7
Create Date: 2026-04-19 14:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5c9d3b7f2a1"
down_revision: Union[str, None] = "d4f8b1c2e3a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "repo_id",
            sa.Integer(),
            sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("message_first_line", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_login", sa.String(length=255), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ref", sa.String(length=255), nullable=True),
        sa.Column("touched_paths_json", sa.JSON(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.UniqueConstraint("repo_id", "commit_sha", name="uq_push_event_sha"),
    )
    op.create_index("ix_push_events_repo_id", "push_events", ["repo_id"], unique=False)
    op.create_index(
        "ix_push_events_pushed_at", "push_events", ["pushed_at"], unique=False
    )

    op.add_column(
        "triage_cards",
        sa.Column("regression_suspects_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_cards", "regression_suspects_json")
    op.drop_index("ix_push_events_pushed_at", table_name="push_events")
    op.drop_index("ix_push_events_repo_id", table_name="push_events")
    op.drop_table("push_events")
