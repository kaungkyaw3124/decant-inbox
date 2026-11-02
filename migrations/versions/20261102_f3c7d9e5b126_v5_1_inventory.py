"""v5.1 inventory: bottles, vials, stock moves

docs/SPEC-v5.1-inventory.md: stock in ml. New tables only (v1 tables unchanged); empty = the shop keeps using the
manual in_stock flag of the price list until it adds bottles.

Revision ID: f3c7d9e5b126
Revises: e2b6c8d4a015
Create Date: 2026-11-02 22:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f3c7d9e5b126'
down_revision: Union[str, None] = 'e2b6c8d4a015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bottles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False, index=True),
        sa.Column("size_ml", sa.Integer(), nullable=False),
        sa.Column("remaining_ml", sa.Numeric(7, 2), nullable=False),
        sa.Column("cost_mmk", sa.Integer()),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('sealed', 'open', 'empty')", name=op.f("ck_bottles_status")),
        sa.CheckConstraint("remaining_ml >= 0", name=op.f("ck_bottles_remaining_not_negative")),
    )
    op.create_table(
        "vials",
        sa.Column("size_ml", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("cost_each_mmk", sa.Integer()),
        sa.CheckConstraint("count >= 0", name=op.f("ck_vials_count_not_negative")),
    )
    op.create_table(
        "stock_moves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), index=True),
        sa.Column("bottle_id", sa.Integer(), sa.ForeignKey("bottles.id")),
        sa.Column("vial_size", sa.Integer()),
        sa.Column("ml_change", sa.Numeric(7, 2), nullable=False, server_default="0"),
        sa.Column("count_change", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('purchase', 'decant', 'adjust', 'return', 'waste')", name=op.f("ck_stock_moves_kind")),
    )


def downgrade() -> None:
    op.drop_table("stock_moves")
    op.drop_table("vials")
    op.drop_table("bottles")
