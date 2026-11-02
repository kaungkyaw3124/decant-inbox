"""v5.0 two-step login, log out everywhere, known devices

docs/SPEC-v5.0-go-live-pack.md G3: users.totp_secret (authenticator app, base32; NULL = 2-step off),
totp_recovery (sha256 of the 10 one-time recovery codes), session_epoch (bumped by "log out everywhere"),
known_devices (hashes of IP + browser, for the new-login alert).

Revision ID: e2b6c8d4a015
Revises: d7e4a1b9c3f2
Create Date: 2026-11-02 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e2b6c8d4a015'
down_revision: Union[str, None] = 'd7e4a1b9c3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(64)))
    op.add_column("users", sa.Column("totp_recovery", postgresql.JSONB(), server_default="[]", nullable=False))
    op.add_column("users", sa.Column("session_epoch", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("known_devices", postgresql.JSONB(), server_default="[]", nullable=False))


def downgrade() -> None:
    for column in ("known_devices", "session_epoch", "totp_recovery", "totp_secret"):
        op.drop_column("users", column)
