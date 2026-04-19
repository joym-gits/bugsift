"""triage_cards gets a ``source`` discriminator + feedback linkage

Three changes to ``triage_cards`` so widget-sourced user reports can
flow through the same pipeline as GitHub issues:

- ``source`` column (``github`` | ``feedback``).
- ``feedback_report_ids_json`` + ``github_issue_number`` for cross-refs.
- ``issue_number`` becomes nullable and the old composite unique
  constraint is replaced with a partial index that applies only to
  github-sourced rows. Feedback cards can now live in the same repo
  without fighting for issue_number slots.

Revision ID: b2e9f1a8c4d6
Revises: a1b8d2f4c6e7
Create Date: 2026-04-19 11:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2e9f1a8c4d6"
down_revision: Union[str, None] = "a1b8d2f4c6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "triage_cards",
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="github",
        ),
    )
    op.create_index("ix_triage_cards_source", "triage_cards", ["source"], unique=False)

    op.add_column(
        "triage_cards", sa.Column("feedback_report_ids_json", sa.JSON(), nullable=True)
    )
    op.add_column(
        "triage_cards", sa.Column("github_issue_number", sa.Integer(), nullable=True)
    )

    op.drop_constraint("uq_repo_issue", "triage_cards", type_="unique")
    op.alter_column("triage_cards", "issue_number", nullable=True)
    # Partial unique index: only github-sourced rows must have a distinct
    # (repo_id, issue_number). Feedback rows carry NULL issue_number and
    # are unconstrained here — they're keyed on ``id`` alone.
    op.execute(
        "CREATE UNIQUE INDEX uq_repo_github_issue ON triage_cards "
        "(repo_id, issue_number) WHERE source = 'github'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_repo_github_issue")
    op.alter_column("triage_cards", "issue_number", nullable=False)
    op.create_unique_constraint(
        "uq_repo_issue", "triage_cards", ["repo_id", "issue_number"]
    )
    op.drop_column("triage_cards", "github_issue_number")
    op.drop_column("triage_cards", "feedback_report_ids_json")
    op.drop_index("ix_triage_cards_source", table_name="triage_cards")
    op.drop_column("triage_cards", "source")
