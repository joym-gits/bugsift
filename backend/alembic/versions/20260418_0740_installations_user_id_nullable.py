"""installations.user_id nullable

Webhooks can create an installation row before the authenticated install
callback links it to a dashboard user. user_id must be nullable so the
webhook path doesn't trip the FK.

Revision ID: 6ab0cf25a729
Revises: a7023fe9dcf1
Create Date: 2026-04-18 07:40:42.549084+00:00

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "6ab0cf25a729"
down_revision: Union[str, None] = "a7023fe9dcf1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "installations", "user_id", existing_type=sa.INTEGER(), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "installations", "user_id", existing_type=sa.INTEGER(), nullable=False
    )
