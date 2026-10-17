"""v4.13 order_start

docs/SPEC-v4.13-hotfix.md Q2: intent order_start ("I want to order" without a product) and the quick
action kind order_start (the "which product?" reply).

Revision ID: 7d2a5e8f1b36
Revises: 3c71d0a9e214
Create Date: 2026-10-18 03:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7d2a5e8f1b36'
down_revision: Union[str, None] = '3c71d0a9e214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INTENTS = ("buy", "ask_stock", "ask_price", "other", "unknown", "remove", "confirm", "done", "address",
           "ask_delivery", "cancel_order", "greeting", "previous_item", "change_info", "payment_sent", "modify_cart")
QUICK = ("price", "cart_add", "cart_remove", "cart_list", "confirm", "address", "contact", "not_stocked",
         "delivery", "cancel_order", "faq", "greeting", "teach", "choose_previous", "change_info", "hold", "locked",
         "cart_change", "choose_product")
CHECKS = (("parse_results", "intent", INTENTS), ("quick_actions", "kind", QUICK))


def _set(new: bool) -> None:
    for table, column, old in CHECKS:
        allowed = old + (("order_start",) if new else ())
        op.drop_constraint(column, table, type_="check")
        op.create_check_constraint(column, table, f"{column} IN {allowed}")


def upgrade() -> None:
    _set(new=True)


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM parse_results WHERE intent = 'order_start') "
            "OR EXISTS (SELECT 1 FROM quick_actions WHERE kind = 'order_start')")).scalar():
        raise RuntimeError("v4.13 data exists; restore a pre-upgrade backup instead of downgrading")
    _set(new=False)
