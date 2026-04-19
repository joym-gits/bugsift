"""feedback_apps.target_branch + repo_analyses table

Revision ID: d4f8b1c2e3a7
Revises: c3d7a9b1e2f5
Create Date: 2026-04-19 13:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f8b1c2e3a7"
down_revision: Union[str, None] = "c3d7a9b1e2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feedback_apps",
        sa.Column("target_branch", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "repo_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "repo_id",
            sa.Integer(),
            sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("structured_json", sa.JSON(), nullable=True),
        sa.Column("mermaid_src", sa.Text(), nullable=True),
        sa.Column("overrides_json", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("repo_id", "branch", name="uq_repo_analysis_branch"),
    )
    op.create_index(
        "ix_repo_analyses_repo_id", "repo_analyses", ["repo_id"], unique=False
    )
    op.create_index(
        "ix_repo_analyses_status", "repo_analyses", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_repo_analyses_status", table_name="repo_analyses")
    op.drop_index("ix_repo_analyses_repo_id", table_name="repo_analyses")
    op.drop_table("repo_analyses")
    op.drop_column("feedback_apps", "target_branch")
