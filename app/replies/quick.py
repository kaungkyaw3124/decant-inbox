"""One-tap quick replies (docs/SPEC-orders.md "One-tap quick replies").

A quick price reply is offered only when everything is certain: a customer's message
parsed as ask_price/ask_stock/buy where every item (up to 3) has a known product named in
this message (not guessed from context) and a known size (or none = all sizes, or full),
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

from app.models import Message, Outbox, ParseItem, ParseResult
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


def price_items(session: Session, result: ParseResult) -> list[compose.PriceItem] | None:
    """The result's items as price-reply items, or None if any of them is uncertain."""
    rows = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                           .order_by(ParseItem.position)).all()
    if not rows and result.product_id is not None:  # a result without item rows
        rows = [ParseItem(product_id=result.product_id, size_ml=result.size_ml, is_full_bottle=False,
                          unknown_text=None, from_context=False)]
    items: list[compose.PriceItem] = []
    for r in rows:
        if r.product_id is None or r.unknown_text or r.from_context:
            return None
        item = compose.PriceItem(r.product_id, "full" if r.is_full_bottle else str(r.size_ml) if r.size_ml else "all")
        if item not in items:
            items.append(item)
    return items if 0 < len(items) <= compose.MAX_PRICE_ITEMS else None


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
    items = price_items(session, result)
    if items is None:
        return None
    composed = compose.price_reply(session, items, texts)
    if composed.problems or composed.notes or not composed.text:  # missing price / out of stock
        return None
    text = compose.with_greeting(composed.text, texts, compose.needs_greeting(session, message.customer_id, now))
    params = "".join(f"&p{n}={i.product_id}&s{n}={i.size}" for n, i in enumerate(items, 1))
    edit_url = f"/chats/{message.customer_id}?compose=price&make=1{params}#reply"
    return QuickReply(text, fingerprint(text), edit_url)
