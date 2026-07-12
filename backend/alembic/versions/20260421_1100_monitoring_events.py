"""monitoring_ingest_tokens + monitoring_events

Generic-provider production/runtime error ingestion, closing the
"monitoring integration is missing" gap. Provider-agnostic on purpose
(Sentry, Datadog, custom) — per-repo static opaque token auth, same
shape as the feedback widget's ``X-Bugsift-App-Key``, since each
provider signs its own webhooks differently and a static bearer token
is the lowest common denominator all of them support.

Revision ID: f3c4d5e6a7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-04-21 11:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bugsift.db.types import JSONB

revision: str = "f3c4d5e6a7b8"
down_revision: Union[str, None] = "f2b3c4d5e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitoring_ingest_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "repo_id", sa.Integer, sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column(
            "created_by_user_id", sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "monitoring_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id", sa.Integer, sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "ingest_token_id", sa.Integer,
            sa.ForeignKey("monitoring_ingest_tokens.id", ondelete="SET NULL"), nullable=True,
        ),
        # "sentry" | "datadog" | "custom" | ...
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("file_paths_json", JSONB, nullable=True),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload_json", JSONB, nullable=True),
        sa.Column(
            "correlated_card_id", sa.Integer,
            sa.ForeignKey("triage_cards.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("ingest_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False, index=True,
        ),
        sa.UniqueConstraint(
            "repo_id", "provider", "external_event_id", name="uq_monitoring_event_external_id"
        ),
    )
    op.create_index(
        "ix_monitoring_events_repo_created", "monitoring_events", ["repo_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_monitoring_events_repo_created", table_name="monitoring_events")
    op.drop_table("monitoring_events")
    op.drop_table("monitoring_ingest_tokens")
