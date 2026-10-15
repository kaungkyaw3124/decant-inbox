"""Auto mode switches, unknown-item resolution, and the monitoring data for the inbox."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Customer, FaqEntry, Message, Outbox, Product, QuickAction, User
from app.models.outbox import UNDO_SECONDS
from app.orders import auto, followups, payments, unknown
from app.replies import compose, faq
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db
from app.web.inbox import detail_url, flash, safe_back

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
FEED_WINDOW = timedelta(hours=24)
FAILED_WINDOW = timedelta(days=3)


@router.post("/auto-reply")
def switch(request: Request, on: str = Form(...), back: str = Form("/"), db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    auto.set_enabled(db, on == "1", user)
    db.add(AuditLog(user_id=user.id, action="auto.switch", details={"enabled": on == "1"}))
    db.commit()
    flash(request, "Auto-reply is ON: certain messages from now on are answered by themselves (8-20 s, "
                   "Cancel in the chat)." if on == "1" else "Auto-reply is OFF: one-tap buttons only.")
    return RedirectResponse(safe_back(back, "/"), status_code=303)


def _customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer


@router.post("/customers/{customer_id}/auto")
def customer_auto(request: Request, customer_id: int, off: str = Form(...), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    customer = _customer(db, customer_id)
    customer.auto_reply_off = off == "1"
    db.add(AuditLog(user_id=user.id, action="auto.customer", details={"customer_id": customer_id,
                                                                        "never_auto": customer.auto_reply_off}))
    db.commit()
    flash(request, "Never auto-reply to this customer." if customer.auto_reply_off
          else "Auto-reply allowed for this customer again.")
    return RedirectResponse(f"/chats/{customer_id}", status_code=303)


@router.post("/customers/{customer_id}/resume-auto")
def resume(request: Request, customer_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    customer = _customer(db, customer_id)
    customer.auto_resumed_at = datetime.now(UTC)
    db.add(AuditLog(user_id=user.id, action="auto.resume", details={"customer_id": customer_id}))
    db.commit()
    flash(request, "Auto-reply resumed for this chat.")
    return RedirectResponse(f"/chats/{customer_id}", status_code=303)


# ---------- unknown items ----------

def _unknown(db: Session, message_id: int, position: int) -> tuple[Message, unknown.Unknown]:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(404, "Message not found")
    item = next((u for u in unknown.open_unknowns(db, message) if u.position == position), None)
    if item is None:
        raise HTTPException(409, "Already resolved")
    return message, item


def _done(request: Request, message: Message, back: str, note: str) -> RedirectResponse:
    flash(request, note)
    return RedirectResponse(detail_url(message.id, back), status_code=303)


@router.post("/messages/{message_id}/unknown/{position}/map")
def map_item(request: Request, message_id: int, position: int, product_id: int = Form(...),
             back: str = Form("/"), db: Session = Depends(get_db), user: User = Depends(current_user)):
    message, item = _unknown(db, message_id, position)
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(400, "Choose a product")
    unknown.map_to_product(db, message, item, product_id, user)
    db.commit()
    return _done(request, message, back, f"“{item.text}” is now an alias of {product.name}.")


def _price(value: str) -> int | None:
    digits = "".join(c for c in value if c.isdigit())
    return int(digits) if digits and 0 < int(digits) <= 100_000_000 else None


@router.post("/messages/{message_id}/unknown/{position}/new")
async def new_item(request: Request, message_id: int, position: int, brand: str = Form(...),
                   name: str = Form(...), asked_price: str = Form(""), full_size_ml: str = Form(""),
                   in_stock: str = Form(""), back: str = Form("/"), db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    message, item = _unknown(db, message_id, position)
    brand, name = brand.strip(), name.strip()
    if not brand or not name:
        raise HTTPException(400, "Brand and name are required")
    if db.scalar(select(Product.id).where(Product.brand == brand, Product.name == name)):
        raise HTTPException(400, "That product already exists: use “It's in my list”")
    form = await request.form()
    prices: dict[int | None, int] = {}
    for size in (2, 3, 5, 10, 15, 20, 30):
        if (p := _price(str(form.get(f"p{size}", "")))) is not None:
            prices[size] = p
    if (p := _price(str(form.get("pfull", "")))) is not None:
        prices[None] = p
    asked = None if item.is_full_bottle else item.size_ml
    if (p := _price(asked_price)) is not None:
        prices[asked] = p
    if (asked not in prices) and (item.size_ml or item.is_full_bottle):
        raise HTTPException(400, "The price for the asked size is required")
    bottle = int(full_size_ml) if full_size_ml.strip().isdigit() and 0 < int(full_size_ml) <= 1000 else None
    product = unknown.new_product(db, message, item, user, brand, name, prices, bottle, in_stock == "1")
    db.commit()
    return _done(request, message, back, f"{product.name} added with {len(prices)} price(s); "
                                         f"“{item.text}” is an alias.")


@router.post("/messages/{message_id}/unknown/{position}/not-stocked")
def not_stocked(request: Request, message_id: int, position: int, back: str = Form("/"),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    message, item = _unknown(db, message_id, position)
    unknown.not_stocked(db, message, item, user)
    db.commit()
    return _done(request, message, back, f"“{item.text}”: we don't have it (the reply will say so).")


# ---------- monitoring ----------

def needs_you(db: Session, now: datetime | None = None) -> dict:
    """The "🟡 Needs you" queue: payments, cancel requests for paid orders, unknown items,
    unpaid orders the system may not remind / cancel by itself, unanswered messages, failed
    sends, paused chats with new messages. Auto-cancelled orders are shown as info."""
    now = now or datetime.now(UTC)
    unknown_msgs = unknown.messages_needing_you(db, now)
    failed = db.execute(select(Outbox, Customer).join(Customer, Customer.id == Outbox.customer_id)
                        .where(Outbox.status == "failed", Outbox.created_at >= now - FAILED_WINDOW)
                        .order_by(Outbox.id.desc())).all()
    paused = []
    for customer in db.scalars(select(Customer).where(Customer.ignored.is_(False))):
        until = auto.paused_until(db, customer, now)
        if until is None:
            continue
        hand = auto.last_hand_reply(db, customer.id, now)
        newer = db.scalar(select(Message.id).where(Message.customer_id == customer.id, Message.direction == "in",
                                                   Message.received_at > hand).limit(1))
        if newer:
            paused.append((customer, until))
    customers = {c.id: c for c in db.scalars(select(Customer).where(
        Customer.id.in_([m.customer_id for m in unknown_msgs])))}
    to_check = payments.to_check(db)
    cancels = followups.cancel_requests(db, now)
    unpaid = [(d, why) for d in followups.due(db, now) if (why := followups.blocked(db, d.customer, now))]
    unanswered = followups.unanswered(db, now)
    for row in unanswered:  # an FAQ question nobody answered yet (auto OFF): offer the one-tap answer
        for mid in reversed(row.message_ids):
            if match := faq.for_message(db, db.get(Message, mid)):
                row.faq = (mid, match)
                break
    listed = {mid for row in unanswered for mid in row.message_ids}
    hints = []
    for message, customer, match in faq.hints(db, now):  # product named, so not automatic
        if message.id in listed:  # shown on its unanswered row instead
            row = next(r for r in unanswered if message.id in r.message_ids)
            row.faq = row.faq or (message.id, match)
        else:
            hints.append((message, customer, match))
    return {"faq_hints": hints,"payments": to_check, "cancels": cancels, "unpaid": unpaid, "unanswered": unanswered,
            "unknown": [(m, customers[m.customer_id], unknown.open_unknowns(db, m)) for m in unknown_msgs],
            "failed": failed, "paused": paused, "auto_cancelled": followups.auto_cancelled(db, now),
            "count": len(to_check) + len(cancels) + len(unpaid) + len(unknown_msgs) + len(unanswered)
                     + len(hints) + len(failed) + len(paused)}


def handled_feed(db: Session, limit: int = 30) -> list:
    """"🤖 Handled automatically" (last 24 h): action, customer, its reply."""
    since = datetime.now(UTC) - FEED_WINDOW
    return db.execute(
        select(QuickAction, Customer, Outbox).join(Customer, Customer.id == QuickAction.customer_id)
        .outerjoin(Outbox, Outbox.id == QuickAction.outbox_id)
        .where(QuickAction.auto, QuickAction.created_at >= since)
        .order_by(QuickAction.id.desc()).limit(limit)).all()


# ---------- FAQ answers from "Needs you" ----------

@router.post("/messages/{message_id}/faq/{entry_id}")
def send_faq(request: Request, message_id: int, entry_id: int, back: str = Form("/"),
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Send an FAQ answer to this message's customer (10 s, Cancel in the chat)."""
    message = db.get(Message, message_id)
    entry = db.get(FaqEntry, entry_id)
    if message is None or entry is None or message.direction != "in":
        raise HTTPException(404, "Not found")
    now = datetime.now(UTC)
    texts = replies.load(db)
    body = compose.with_greeting(entry.answer, texts, compose.needs_greeting(db, message.customer_id, now))
    box = Outbox(customer_id=message.customer_id, text=body, reply_kind="faq", status="queued",
                 idempotency_key=f"faq-{message_id}-{entry_id}-{now.timestamp()}", created_by=user.id,
                 send_after=now + timedelta(seconds=UNDO_SECONDS), source_message_id=message_id)
    db.add(box)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="faq.send", details={"message_id": message_id, "faq_id": entry_id,
                                                                 "outbox_id": box.id}))
    db.commit()
    flash(request, f"FAQ “{entry.title}” goes out in {UNDO_SECONDS} s (Cancel in the chat).")
    return RedirectResponse(safe_back(back, "/"), status_code=303)


@router.post("/messages/{message_id}/faq-hint-done")
def faq_hint_done(request: Request, message_id: int, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    db.add(AuditLog(user_id=user.id, action="faq.hint_done", details={"message_id": message_id}))
    db.commit()
    return RedirectResponse("/", status_code=303)
