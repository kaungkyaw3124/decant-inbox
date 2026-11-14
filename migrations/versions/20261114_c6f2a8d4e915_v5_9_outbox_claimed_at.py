"""v5.9 outbox: when a row was claimed for sending, and when it was recovered after a crash

docs/SPEC-v5.9-reliability-under-load.md B1. Two nullable columns only.

Revision ID: c6f2a8d4e915
Revises: b5e9f1a7d348
Create Date: 2026-11-14 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c6f2a8d4e915'
down_revision: Union[str, None] = 'b5e9f1a7d348'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("outbox", sa.Column("recovered_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("outbox", "recovered_at")
    op.drop_column("outbox", "claimed_at")
