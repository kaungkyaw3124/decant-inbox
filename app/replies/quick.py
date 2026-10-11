"""One-tap quick replies (docs/SPEC-orders.md "One-tap quick replies").

A quick price reply is offered only when everything is certain: a customer's message
parsed as ask_price/ask_stock/buy with a known product, a known size (or none = all sizes),
confident (or corrected by a human), every price present and in stock, and nothing sent
or queued to that customer in the last 60 s. Otherwise the admin uses the chat editor.
The text is fixed when the button is shown; the server re-builds it on tap and refuses
if it changed (`fingerprint`), so what was previewed is exactly what is sent.
"""
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Message, Outbox, ParseResult
from app.parser.rules import NEEDS_REVIEW_BELOW
from app.replies import compose

# buy too, until the cart (Step 4) exists: the customer at least gets the price (spec 2026-10-12)
QUICK_INTENTS = ("ask_price", "ask_stock", "buy")
RECENT_REPLY = timedelta(seconds=60)


@dataclass(frozen=True)
class QuickReply:
    text: str
    fingerprint: str
    edit_url: str  # the same reply in the chat editor

    @property
    def preview(self) -> str:
        line = " · ".join(t for t in self.text.splitlines() if t.strip())
        return line if len(line) <= 90 else line[:89] + "…"


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def pending_quick(session: Session, message_ids: list[int]) -> dict[int, Outbox]:
    """Quick replies already made for these messages (not cancelled), newest per message."""
    if not message_ids:
        return {}
    rows = session.scalars(select(Outbox).where(
        Outbox.source_message_id.in_(message_ids), Outbox.status != "cancelled").order_by(Outbox.id))
    return {o.source_message_id: o for o in rows}


def recently_replied(session: Session, customer_id: int, now: datetime) -> bool:
    return bool(session.scalar(select(exists().where(
        Outbox.customer_id == customer_id, Outbox.status != "cancelled",
        Outbox.created_at >= now - RECENT_REPLY))))


def quick_price_reply(session: Session, message: Message, result: ParseResult | None,
                      texts: dict[str, str], now: datetime | None = None) -> QuickReply | None:
    now = now or datetime.now(UTC)
    if (message.direction != "in" or result is None or not result.is_current
            or result.intent not in QUICK_INTENTS or result.product_id is None):
        return None
    if result.method != "human" and result.confidence < NEEDS_REVIEW_BELOW:
        return None
    if pending_quick(session, [message.id]) or recently_replied(session, message.customer_id, now):
        return None
    size = str(result.size_ml) if result.size_ml else "all"
    composed = compose.price_reply(session, [compose.PriceItem(result.product_id, size)], texts)
    if composed.problems or composed.notes or not composed.text:  # missing price / out of stock
        return None
    text = compose.with_greeting(composed.text, texts, compose.needs_greeting(session, message.customer_id, now))
    edit_url = (f"/chats/{message.customer_id}?compose=price&make=1"
                f"&p1={result.product_id}&s1={size}#reply")
    return QuickReply(text, fingerprint(text), edit_url)
