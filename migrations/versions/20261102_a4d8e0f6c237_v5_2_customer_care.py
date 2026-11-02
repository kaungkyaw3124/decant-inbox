"""v5.2 customer care: notes, tags, opt-outs, reorder messages, feedback

docs/SPEC-v5.2-customer-care.md. New tables only.

Revision ID: a4d8e0f6c237
Revises: f3c7d9e5b126
Create Date: 2026-11-02 23:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a4d8e0f6c237'
down_revision: Union[str, None] = 'f3c7d9e5b126'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _now() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table("customer_notes", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False, index=True),
                    sa.Column("text", sa.String(500), nullable=False),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), _now())
    op.create_table("customer_tags",
                    sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), primary_key=True),
                    sa.Column("tag", sa.String(24), primary_key=True),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), _now())
    op.create_table("care_optouts",
                    sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), primary_key=True),
                    sa.Column("source", sa.String(16), nullable=False), _now())
    op.create_table("reorder_sent", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False, index=True),
                    sa.Column("outbox_id", sa.Integer(), sa.ForeignKey("outbox.id"), nullable=False),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), _now())
    op.create_table("order_feedback",
                    sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), primary_key=True),
                    sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False, index=True),
                    sa.Column("outbox_id", sa.Integer(), sa.ForeignKey("outbox.id")),
                    sa.Column("asked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("answer", sa.String(8)),
                    sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id")),
                    sa.Column("answered_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for table in ("order_feedback", "reorder_sent", "care_optouts", "customer_tags", "customer_notes"):
        op.drop_table(table)
