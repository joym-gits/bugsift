"""card_corrections — operator deltas for feedback-loop learning

Revision ID: d6b1f5a8c4e9
Revises: c4a9e2f7b3d8
Create Date: 2026-04-20 20:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bugsift.db.types import JSONB

revision: str = "d6b1f5a8c4e9"
down_revision: Union[str, None] = "c4a9e2f7b3d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_corrections",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.Integer,
            sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # card_id is nullable on purpose — the card may be deleted
        # later (rerun path does this); the correction still has
        # value for future prompts.
        sa.Column(
            "card_id",
            sa.Integer,
            sa.ForeignKey("triage_cards.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # Which action produced this delta: "edit_comment", "skip",
        # "reclassify", "override_assignees", "override_labels".
        sa.Column("action", sa.String(length=32), nullable=False, index=True),
        # What the pipeline produced (classification / draft_comment /
        # suggested_assignees / proposed_labels / severity — the subset
        # that action applies to).
        sa.Column("before_json", JSONB, nullable=True),
        # What the operator chose instead.
        sa.Column("after_json", JSONB, nullable=True),
        # Small snippet of the issue title/body so future retrieval can
        # match this correction to similar-shaped future issues without
        # dereferencing the card row.
        sa.Column("issue_context", sa.Text, nullable=True),
        # Classification the card carried at correction time — used to
        # filter relevant corrections on future runs ("only feed
        # bug-classified corrections into bug classifications").
        sa.Column("classification", sa.String(length=32), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )
    # Composite: "give me the most recent N corrections for this repo
    # filtered by classification". The only query this table sees on
    # the hot path.
    op.create_index(
        "ix_card_corrections_repo_class_recent",
        "card_corrections",
        ["repo_id", "classification", "created_at"],
    )

    # Track which cards used corrections at triage time — so the UI
    # can show a "learning from N corrections" pill and the metrics
    # dashboard can chart adoption over time.
    op.add_column(
        "triage_cards",
        sa.Column("corrections_applied_count", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_cards", "corrections_applied_count")
    op.drop_index(
        "ix_card_corrections_repo_class_recent", table_name="card_corrections"
    )
    op.drop_table("card_corrections")
