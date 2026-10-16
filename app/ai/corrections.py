""""🧠 AI was wrong" (docs/SPEC-v4.7-graduation.md): an admin corrects a message the AI handled
in AUTO mode. The card asks again what the customer wanted (products, sizes, intent); saving it
stores a human parse result, counts the AI call as corrected (wrong product if a product
changed), counts corrections on the AI's pending patterns, and runs the safety brake. The order
itself is fixed with the normal tools (Undo while the reply waits, the cart in the chat)."""
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AICall, AuditLog, LearnedPattern, Message, ParseItem, ParseResult, User

INTENTS = ("buy", "ask_price", "ask_stock", "remove", "cancel_order", "confirm", "address", "greeting",
           "ask_delivery", "other")


@dataclass
class FixCard:
    call: AICall
    result: ParseResult
    items: list[ParseItem]


class FixError(Exception):
    pass


def card(session: Session, message: Message) -> FixCard | None:
    """The correction card, for a message whose current result came from the AI (AUTO)."""
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if result is None or result.method != "ai":
        return None
    call = session.scalar(select(AICall).where(AICall.message_id == message.id))
    if call is None or call.decision not in ("auto", "accepted"):
        return None
    items = list(session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                                 .order_by(ParseItem.position)))
    return FixCard(call, result, items)


def _size(value: str) -> tuple[int | None, bool]:
    if value == "full":
        return None, True
    return (int(value), False) if value.isdigit() and 0 < int(value) < 1000 else (None, False)


def apply(session: Session, message: Message, form, user: User) -> tuple[bool, str | None]:
    """Save the correction. Returns (wrong product?, brake reason or None)."""
    from app.ai import graduation  # late import: graduation -> service
    from app.learning import patterns

    fix = card(session, message)
    if fix is None:
        raise FixError("Nothing to correct: this message was not handled by the AI.")
    intent = str(form.get("intent") or fix.result.intent)
    if intent not in INTENTS:
        raise FixError("Choose what the customer wanted.")
    new_items, wrong = [], False
    for item in fix.items:
        answer = str(form.get(f"p{item.position}") or "")
        size, full = _size(str(form.get(f"size{item.position}") or ""))
        if answer == "not_stocked":
            pid, unknown = None, item.unknown_text or "?"
        elif answer.isdigit():
            pid, unknown = int(answer), None
        else:
            raise FixError("Choose a product (or “we don't sell it”) for every line.")
        if item.product_id is not None and pid != item.product_id:
            wrong = True  # the AI named a product, the admin chose another one / "we don't sell it"
        qty = str(form.get(f"qty{item.position}") or item.quantity)
        new_items.append(ParseItem(position=item.position, product_id=pid, size_ml=size, is_full_bottle=full,
                                   quantity=int(qty) if qty.isdigit() and 0 < int(qty) <= 20 else 1,
                                   unknown_text=unknown, from_context=False, match="human"))
    session.execute(update(ParseResult).where(ParseResult.id == fix.result.id).values(is_current=False))
    session.flush()
    first = next((i for i in new_items if i.product_id), new_items[0] if new_items else None)
    result = ParseResult(message_id=message.id, intent=intent, product_id=first.product_id if first else None,
                         size_ml=first.size_ml if first else None, quantity=first.quantity if first else 1,
                         confidence=1.0, method="human", parser_version="human", is_current=True,
                         phone=fix.result.phone, learned_ids=[])
    session.add(result)
    session.flush()
    for item in new_items:
        item.parse_result_id = result.id
        session.add(item)
    # the AI's pending patterns from this message were wrong too: they need the owner now
    chosen = {i.product_id for i in new_items}
    bad = [p.id for p in session.scalars(select(LearnedPattern).where(
        LearnedPattern.source_message_id == message.id, LearnedPattern.via_ai, LearnedPattern.status == "pending"))
           if (p.kind == "nickname" and p.product_id not in chosen) or (p.kind == "intent_phrase" and p.intent != intent)
           or (p.kind == "not_stocked" and any(i.product_id for i in new_items if i.unknown_text is None) and wrong)]
    patterns.add_corrections(session, bad, user, message.id)
    session.add(AuditLog(user_id=user.id, action="ai.wrong", details={
        "message_id": message.id, "ai_call_id": fix.call.id, "wrong_product": wrong, "intent": intent}))
    reason = graduation.record_decision(session, fix.call, "corrected", user, wrong)
    return wrong, reason
