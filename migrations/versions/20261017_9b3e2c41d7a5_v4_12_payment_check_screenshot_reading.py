"""v4.12 payment check screenshot reading

docs/SPEC-v4.12-address-payment-ai.md N3: payment_checks.ai_status / ai_error / ai_read / ai_read_at /
ai_cost_usd (the AI's reading of the screenshot, only with the owner's switch ai_screenshot ON).

Revision ID: 9b3e2c41d7a5
Revises: 5652173130df
Create Date: 2026-10-17 18:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '9b3e2c41d7a5'
down_revision: Union[str, None] = '5652173130df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payment_checks', sa.Column('ai_status', sa.String(length=12), nullable=True))
    op.add_column('payment_checks', sa.Column('ai_error', sa.String(length=64), nullable=True))
    op.add_column('payment_checks', sa.Column('ai_read', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('payment_checks', sa.Column('ai_read_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('payment_checks', sa.Column('ai_cost_usd', sa.Numeric(precision=12, scale=8), server_default='0',
                                              nullable=False))


def downgrade() -> None:
    op.drop_column('payment_checks', 'ai_cost_usd')
    op.drop_column('payment_checks', 'ai_read_at')
    op.drop_column('payment_checks', 'ai_read')
    op.drop_column('payment_checks', 'ai_error')
    op.drop_column('payment_checks', 'ai_status')
