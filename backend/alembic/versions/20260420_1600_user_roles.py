"""users.role — admin / triager / viewer for RBAC

Revision ID: 8d5f0c3a1e7b
Revises: 7c4e9d2b5f1a
Create Date: 2026-04-20 16:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "8d5f0c3a1e7b"
down_revision: Union[str, None] = "7c4e9d2b5f1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first so we can backfill deterministically, then lock
    # NOT NULL after every row has a value.
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=True),
    )
    # Existing users are the operators who stood the deployment up —
    # grant them admin; new users default to "triager" via app logic.
    op.execute("UPDATE users SET role = 'admin' WHERE role IS NULL")
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="triager",
    )


def downgrade() -> None:
    op.drop_column("users", "role")
