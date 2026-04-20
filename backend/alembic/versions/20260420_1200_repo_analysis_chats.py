"""repo_analysis_chats table for Q&A over the indexed code

Revision ID: 4f9c1e7b3d2a
Revises: 3d7f2a1c5e9b
Create Date: 2026-04-20 12:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "4f9c1e7b3d2a"
down_revision: Union[str, None] = "3d7f2a1c5e9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repo_analysis_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "analysis_id",
            sa.Integer(),
            sa.ForeignKey("repo_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.JSON(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_repo_analysis_chats_analysis_id",
        "repo_analysis_chats",
        ["analysis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_repo_analysis_chats_analysis_id", table_name="repo_analysis_chats"
    )
    op.drop_table("repo_analysis_chats")
