"""llm_usage gets duration + analysis linkage; repo_analyses gets started_at

Closes the usage-tracking gap: no LLM call in the repo-analysis
pipeline previously wrote to ``llm_usage`` at all, and no call
anywhere captured elapsed time. ``analysis_id`` is an explicit join
key (rather than guessing by timestamp proximity) since one analysis
run's findings pass can produce many triage cards, so ``card_id``
alone can't attribute cost to a single run.

Revision ID: f2b3c4d5e6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-21 10:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b3c4d5e6a7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_usage", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "llm_usage",
        sa.Column(
            "analysis_id",
            sa.Integer(),
            sa.ForeignKey("repo_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_llm_usage_analysis_id", "llm_usage", ["analysis_id"])
    op.add_column(
        "repo_analyses", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("repo_analyses", "started_at")
    op.drop_index("ix_llm_usage_analysis_id", table_name="llm_usage")
    op.drop_column("llm_usage", "analysis_id")
    op.drop_column("llm_usage", "duration_ms")
