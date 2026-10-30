"""v4.14 test payment code

docs/SPEC-v4.14-test-payment-code.md T1: customers.is_tester, orders.is_test, payment_checks.is_test and
the test order numbers T1, T2, ... (sequence test_order_no_seq; real orders keep #1001+).

Revision ID: b4e7c2d91a03
Revises: 7d2a5e8f1b36
Create Date: 2026-10-29 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4e7c2d91a03'
down_revision: Union[str, None] = '7d2a5e8f1b36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (("customers", "is_tester"), ("orders", "is_test"), ("payment_checks", "is_test"))


def upgrade() -> None:
    for table, column in TABLES:
        op.add_column(table, sa.Column(column, sa.Boolean(), server_default=sa.false(), nullable=False))
    # test numbers share orders.order_no with real ones (#1001+), so they must stay below 1001
    op.execute("CREATE SEQUENCE test_order_no_seq START 1 MAXVALUE 1000")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM orders WHERE is_test)")).scalar():
        raise RuntimeError("v4.14 test orders exist; restore a pre-upgrade backup instead of downgrading")
    op.execute("DROP SEQUENCE test_order_no_seq")
    for table, column in TABLES:
        op.drop_column(table, column)
