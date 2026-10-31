"""v4.20 delivery fee FAQ entry

docs/SPEC-v4.20-automation-goal.md A2/A6: "ပို့ခ ဘယ်လောက်လဲ" gets an automatic answer. Until the owner writes the
fee table into this FAQ entry (Settings -> FAQ), the safe default says the admin confirms the fee. Data only.

Revision ID: c5d8e1f2a904
Revises: b4e7c2d91a03
Create Date: 2026-10-31 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c5d8e1f2a904'
down_revision: Union[str, None] = 'b4e7c2d91a03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TITLE = "Delivery fee"
KEYWORDS = "ပို့ခ, ပို့ဆောင်ခ, deli fee, delivery fee, delivery charge, shipping fee, ship fee"
ANSWER = "ပို့ခကို admin က အတည်ပြုပေးပါမယ်နော်။ ပို့ခကိုတော့ ပစ္စည်းရောက်မှ ပေးရပါတယ်။"


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "INSERT INTO faq_entries (title, keywords, answer, sort_order) "
        "SELECT :t, :k, :a, coalesce(max(sort_order), 0) + 1 FROM faq_entries "
        "HAVING NOT EXISTS (SELECT 1 FROM faq_entries WHERE title = :same)"),
        {"t": TITLE, "same": TITLE, "k": KEYWORDS, "a": ANSWER})


def downgrade() -> None:  # only the untouched default; an entry the owner edited stays
    op.get_bind().execute(sa.text("DELETE FROM faq_entries WHERE title = :t AND answer = :a"), {"t": TITLE, "a": ANSWER})
