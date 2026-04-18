"""github_app_credentials singleton

Stores the operator's registered GitHub App credentials. Previously these
lived in .env only, which forced a manual registration + restart on every
fresh deployment. Phase 11 (post-v1) onboarding persists them after the
manifest flow so the stack is configurable entirely from the UI.

Secrets are encrypted at rest with the same Fernet key that protects user
API keys. A CHECK constraint pins the table to a single row — one App per
deployment.

Revision ID: 7fa2d13c88e1
Revises: 6e5b2c1a77f1
Create Date: 2026-04-18 11:00:00+00:00

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "7fa2d13c88e1"
down_revision: Union[str, None] = "6e5b2c1a77f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_app_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_app_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_login", sa.String(length=255), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("private_key_pem_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_github_app_singleton"),
    )


def downgrade() -> None:
    op.drop_table("github_app_credentials")
