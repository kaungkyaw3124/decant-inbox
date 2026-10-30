"""Auto mode switches, unknown-item resolution, and the monitoring data for the inbox."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Customer, FaqEntry, Message, MessageReview, Outbox, ParseResult, Product, QuickAction, User,
)
from app.models.outbox import UNDO_SECONDS
from app.learning import cards, patterns
from app.orders import actions, address, auto, cart, followups, payments, unknown
from app.replies import compose, faq
from app.replies import templates as replies
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db
from app.web.inbox import detail_url, flash, safe_back

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
FEED_WINDOW = timedelta(hours=24)
FAILED_WINDOW = timedelta(days=3)


@router.post("/auto-reply", dependencies=[Depends(owner_only)])
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


@router.post("/customers/{customer_id}/tester", dependencies=[Depends(owner_only)])
def customer_tester(request: Request, customer_id: int, on: str = Form(...), db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """docs/SPEC-v4.14-test-payment-code.md: the test payment code works only from a test account."""
    customer = _customer(db, customer_id)
    customer.is_tester = on == "1"
    db.add(AuditLog(user_id=user.id, action="customer.tester", details={"customer_id": customer_id,
                                                                         "is_tester": customer.is_tester}))
    db.commit()
    flash(request, "🧪 Test account: the test payment code works in this chat." if customer.is_tester
          else "Not a test account any more.")
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


@router.post("/messages/{message_id}/unknown/{position}/map", dependencies=[Depends(owner_only)])
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


@router.post("/messages/{message_id}/unknown/{position}/new", dependencies=[Depends(owner_only)])
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


# ---------- docs/SPEC-v4.12-address-payment-ai.md N1: "📍 check address" ----------

def _message(db: Session, message_id: int) -> Message:
    message = db.get(Message, message_id)
    if message is None or message.direction != "in":
        raise HTTPException(404, "Message not found")
    return message


@router.post("/messages/{message_id}/address")
def fix_address(request: Request, message_id: int, full_text: str = Form(""), back: str = Form("/"),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The admin's corrected address (same validator) -> the normal next step (payment info, ...)."""
    message = _message(db, message_id)
    back = safe_back(back, "/")
    check = address.admin_check(full_text)
    if not check.valid:
        flash(request, "Not saved: " + check.why)
        return RedirectResponse(back, status_code=303)
    texts = replies.load(db)
    result = db.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    suggestion = actions.suggest(db, message, result, texts, address_override=full_text)
    if suggestion is None:
        flash(request, "Not possible any more (already handled, or a reply is waiting to go out).")
        return RedirectResponse(back, status_code=303)
    try:
        actions.perform(db, message, suggestion.fingerprint, user, texts, address=full_text)
    except actions.Refused as exc:
        db.rollback()
        flash(request, str(exc))
        return RedirectResponse(back, status_code=303)
    db.add(AuditLog(user_id=user.id, action="address.fixed", details={"message_id": message.id}))
    db.commit()
    flash(request, "Address saved. The reply goes out in 10 s (Undo in the chat).")
    return RedirectResponse(back, status_code=303)


@router.post("/messages/{message_id}/address/ask")
def ask_full_address(request: Request, message_id: int, back: str = Form("/"), db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    """"Please send the full address" (template address_invalid_note); nothing is saved."""
    message = _message(db, message_id)
    now = datetime.now(UTC)
    texts = replies.load(db)
    body = compose.with_greeting(texts["address_invalid_note"], texts,
                                 compose.needs_greeting(db, message.customer_id, now))
    db.add(Outbox(customer_id=message.customer_id, text=body, reply_kind="ask_address", status="queued",
                  idempotency_key=f"address-ask-{message.id}-{now.timestamp()}", created_by=user.id,
                  send_after=now + timedelta(seconds=UNDO_SECONDS), source_message_id=message.id))
    actions.upsert_review(db, message.id, "done", user)
    db.add(AuditLog(user_id=user.id, action="address.ask_full", details={"message_id": message.id}))
    db.commit()
    flash(request, "Asked for the full address. It goes out in 10 s (Cancel in the chat).")
    return RedirectResponse(safe_back(back, "/"), status_code=303)


# ---------- monitoring ----------

def needs_you(db: Session, now: datetime | None = None, owner: bool = True) -> dict:
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
    teach = cards.to_teach(db, now)
    taught_ids = {m.id for m, _ in teach}
    unknown_msgs = [m for m in unknown_msgs if m.id not in taught_ids]  # their card asks about them
    customers = {c.id: c for c in db.scalars(select(Customer).where(
        Customer.id.in_([m.customer_id for m in unknown_msgs] + [m.customer_id for m, _ in teach])))}
    to_check = payments.to_check(db)
    from app.ai import screens  # docs/SPEC-v4.12 N3: "⚠️ n" from the screenshot reader on the payment line

    payment_warnings = {check.id: len(screens.warnings(db, check, order, cart.view(db, order).total))
                        for check, order, _ in to_check if check.ai_read}
    cancels = followups.cancel_requests(db, now)
    unpaid = [(d, why) for d in followups.due(db, now) if (why := followups.blocked(db, d.customer, now))]
    address_checks = address.to_check(db, now)  # docs/SPEC-v4.12-address-payment-ai.md N1
    checking = {m.id for m, *_ in address_checks}
    from app.orders import holding  # docs/SPEC-v4.13-hotfix.md Q1

    waiting = holding.waiting(db, now)
    waiting_customers = {c.id for c, _, _ in waiting}
    unanswered = [r for r in followups.unanswered(db, now) if r.customer.id not in waiting_customers]
    for row in unanswered:
        row.message_ids = [mid for mid in row.message_ids if mid not in checking]
    unanswered = [r for r in unanswered if r.message_ids]
    teach = [(m, card) for m, card in teach if m.id not in checking]
    cards_by_id = dict(teach)
    for row in unanswered:  # the teaching card of an unanswered message goes on its row
        mid = next((mid for mid in reversed(row.message_ids) if mid in cards_by_id), None)
        if mid is not None:
            row.card = (db.get(Message, mid), cards_by_id[mid])
    on_rows = {row.card[0].id for row in unanswered if row.card}
    teach = [(m, card) for m, card in teach if m.id not in on_rows]
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
    price_needed = cards.price_needed(db)
    to_approve = patterns.pending_count(db) if owner else 0  # approving is the owner's job (4.4)
    conflicts = patterns.conflicts(db) if owner else []
    from app.ai import report as ai_report  # late import: ai -> orders -> this module's imports

    ai_notices = ai_report.notices(db, now)  # docs/SPEC-v4.6-ai.md S5: errors, no credit, limits
    from app.orders import testpay  # docs/SPEC-v4.14: owner only, the last 24 h

    test_notes = ([("⚠️ someone sent the test payment code — change TEST_PAY_CODE", c, at)
                   for c, at in testpay.notes(db, "test_code.non_tester", now - timedelta(hours=24))]
                  + [("🧪 test code but no order waiting for payment", c, at)
                     for c, at in testpay.notes(db, "test_code.no_order", now - timedelta(hours=24))]) if owner else []
    from app.orders import change  # docs/SPEC-v4.8-change-info.md

    changed_paid = change.changed_after_payment(db)
    from app.orders import steps  # docs/SPEC-v4.10-interruptions.md

    requests = steps.open_requests(db)
    change_sent = change.requests_for_sent_orders(db, now)
    # docs/SPEC-v4.11-ai-first.md L7: > 24 h old and the customer wrote again since -> "Older (n)"
    latest_in = dict(db.execute(select(Message.customer_id, func.max(Message.received_at)).where(
        Message.direction == "in").group_by(Message.customer_id)).all())

    def old(at: datetime, customer_id: int) -> bool:
        return at < now - OLDER_AFTER and latest_in.get(customer_id, at) > at

    unknown_rows = [(m, customers[m.customer_id], unknown.open_unknowns(db, m)) for m in unknown_msgs]
    teach_rows = [(m, customers[m.customer_id], card) for m, card in teach]
    older = {
        "teach": [r for r in teach_rows if old(r[0].received_at, r[0].customer_id)],
        "unknown": [r for r in unknown_rows if old(r[0].received_at, r[0].customer_id)],
        "unanswered": [r for r in unanswered if old(r.last_at, r.customer.id)],
        "faq_hints": [r for r in hints if old(r[0].received_at, r[0].customer_id)],
    }
    moved = {id(r) for rows in older.values() for r in rows}
    teach_rows = [r for r in teach_rows if id(r) not in moved]
    unknown_rows = [r for r in unknown_rows if id(r) not in moved]
    unanswered = [r for r in unanswered if id(r) not in moved]
    hints = [r for r in hints if id(r) not in moved]
    teach, unknown_msgs = [(m, card) for m, _, card in teach_rows], [m for m, _, _ in unknown_rows]
    older_rows: dict[int, tuple] = {}  # message id -> (link, customer, text, time): each message once
    for m, c, *_ in older["teach"] + older["unknown"] + older["faq_hints"]:
        older_rows.setdefault(m.id, (f"/messages/{m.id}", c, m.raw_text or "", m.received_at))
    for r in older["unanswered"]:
        for mid in r.message_ids:
            older_rows.setdefault(mid, (f"/chats/{r.customer.id}#bottom", r.customer, r.last_text, r.last_at))
    older_ids = sorted(older_rows)
    return {"faq_hints": hints, "payments": to_check, "cancels": cancels, "unpaid": unpaid, "unanswered": unanswered,
            "unknown": unknown_rows, "teach": teach_rows,
            "older": [older_rows[i] for i in older_ids], "older_ids": older_ids, "older_count": len(older_ids),
            "dismissed": recent_dismiss(db, now),
            "price_needed": price_needed, "to_approve": to_approve, "conflicts": conflicts,
            "failed": failed, "paused": paused, "auto_cancelled": followups.auto_cancelled(db, now),
            "ai_notices": ai_notices, "test_notes": test_notes, "changed_paid": changed_paid, "change_sent": change_sent, "requests": requests,
            "address_checks": address_checks, "payment_warnings": payment_warnings, "waiting": waiting,
            "count": len(waiting) + len(address_checks) + len(ai_notices) + len(test_notes) + len(changed_paid) + len(change_sent) + len(requests) + len(to_check) + len(cancels) + len(unpaid) + len(unknown_msgs) + len(unanswered)
                     + len(hints) + len(failed) + len(paused) + len(teach) + len(price_needed)
                     + (1 if to_approve else 0) + len(conflicts)}


OLDER_AFTER = timedelta(hours=24)
DISMISS_UNDO = timedelta(seconds=60)


def recent_dismiss(db: Session, now: datetime) -> AuditLog | None:
    """The last "Dismiss all older" of the last 60 s that was not undone (its Undo button)."""
    row = db.scalar(select(AuditLog).where(AuditLog.action == "needs_you.dismiss_older",
                                           AuditLog.created_at >= now - DISMISS_UNDO).order_by(AuditLog.id.desc())
                    .limit(1))
    if row is None or db.scalar(select(exists().where(AuditLog.action == "needs_you.dismiss_undo",
                                                      AuditLog.details["dismiss_id"].as_integer() == row.id))):
        return None
    return row


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


@router.post("/needs-you/dismiss-older")
async def dismiss_older(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """docs/SPEC-v4.11-ai-first.md L7: "Dismiss all older" = those messages marked done (Undo for 60 s).
    Payments are never in Older."""
    form = await request.form()
    ids = sorted({int(v) for v in form.getlist("message_id") if str(v).isdigit()})
    if not ids:
        raise HTTPException(400, "Nothing to dismiss")
    previous = {str(mid): status for mid, status in db.execute(
        select(MessageReview.message_id, MessageReview.status).where(MessageReview.message_id.in_(ids)))}
    followups.clear(db, ids, "done", user)
    db.add(AuditLog(user_id=user.id, action="needs_you.dismiss_older", details={
        "message_ids": ids, "previous": previous}))
    db.commit()
    flash(request, f"Dismissed {len(ids)} older messages. Undo for 60 s.")
    return RedirectResponse("/#needs-you", status_code=303)


@router.post("/needs-you/dismiss-older/{audit_id}/undo")
def dismiss_older_undo(request: Request, audit_id: int, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    row = recent_dismiss(db, datetime.now(UTC))
    if row is None or row.id != audit_id:
        flash(request, "Too late to undo.")
        return RedirectResponse("/#needs-you", status_code=303)
    previous = row.details.get("previous") or {}
    for mid in row.details["message_ids"]:
        before = previous.get(str(mid))
        if before is None:
            db.execute(delete(MessageReview).where(MessageReview.message_id == mid))
        else:
            db.execute(update(MessageReview).where(MessageReview.message_id == mid).values(status=before))
    db.add(AuditLog(user_id=user.id, action="needs_you.dismiss_undo", details={"dismiss_id": row.id}))
    db.commit()
    flash(request, "Undone: the older messages are back.")
    return RedirectResponse("/#needs-you", status_code=303)
