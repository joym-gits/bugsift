"""triage_cards gets analysis-finding linkage + dedupe key

Adds ``finding_key``/``finding_category`` so repo-analysis findings can
materialize as ``TriageCard`` rows with ``source='analysis'``. Mirrors
the ``uq_repo_github_issue`` precedent from the source-column
migration: a partial unique index scoped to ``source='analysis'``
keeps re-running analysis on unchanged code from spamming duplicate
cards, without constraining the other two sources.

Revision ID: f1a2b3c4d5e6
Revises: d6b1f5a8c4e9
Create Date: 2026-04-21 09:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "d6b1f5a8c4e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "triage_cards", sa.Column("finding_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "triage_cards", sa.Column("finding_category", sa.String(length=32), nullable=True)
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_repo_finding_key ON triage_cards "
        "(repo_id, finding_key) WHERE source = 'analysis'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_repo_finding_key")
    op.drop_column("triage_cards", "finding_category")
    op.drop_column("triage_cards", "finding_key")
