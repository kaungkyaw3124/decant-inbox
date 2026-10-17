"""v4.13 holding reply

docs/SPEC-v4.13-hotfix.md Q1: outbox.reply_kind "holding" (the watchdog's "please wait" reply).

Revision ID: 3c71d0a9e214
Revises: 9b3e2c41d7a5
Create Date: 2026-10-18 03:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3c71d0a9e214'
down_revision: Union[str, None] = '9b3e2c41d7a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REPLY = ("custom", "price", "cart", "ask_address", "ask_phone", "contact", "payment_info", "payment",
         "delivery", "reminder", "cancel", "faq", "greeting", "choice", "hold")


def _set(allowed: tuple[str, ...]) -> None:
    op.drop_constraint("reply_kind", "outbox", type_="check")
    op.create_check_constraint("reply_kind", "outbox", f"reply_kind IN {allowed}")


def upgrade() -> None:
    _set(REPLY + ("holding",))


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM outbox WHERE reply_kind = 'holding')")).scalar():
        raise RuntimeError("v4.13 holding replies exist; restore a pre-upgrade backup instead of downgrading")
    _set(REPLY)
