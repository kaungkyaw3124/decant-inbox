"""retire parse results of outgoing messages

Revision ID: 70a237588133
Revises: a8830ff00f3e
Create Date: 2026-10-11 19:20:23.185681
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '70a237588133'
down_revision: Union[str, None] = 'a8830ff00f3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Outgoing messages imported in Step 2 were parsed by the still-running old worker.
    # Only customers' messages are parsed; keep the rows as history, just not current.
    op.execute("""
        UPDATE parse_results SET is_current = false
        WHERE is_current AND message_id IN (SELECT id FROM messages WHERE direction = 'out')
    """)


def downgrade() -> None:
    pass  # nothing to restore: those results were wrong
