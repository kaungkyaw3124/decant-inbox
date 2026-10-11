"""Chats: conversation list, conversation view, replies (Custom / Price), photos on demand.

The dashboard never talks to Telegram: "Send" only adds an outbox row, and the listener
(the one process with the Telegram session) sends it. Photos are downloaded by the
listener when an admin taps "Show photo".
"""
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Customer, MediaDownload, Message, Order, OrderItem, Outbox, PaymentCheck, Product, QuickAction, User,
)
from app.models.orders import MAX_PHONES, OPEN_STATUSES
from app.models.outbox import MAX_TEXT, MEDIA_DIR
from app.orders import actions, auto, cart
from app.parser.normalize import normalize
from app.parser.rules import find_phones
from app.pricing.prices import current_prices
from app.replies import compose
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
THREAD_SIZE = 100
LIST_SIZE = 50
STUCK_AFTER = timedelta(minutes=2)
MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def get_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer


def telegram_link(customer: Customer) -> str:
    if customer.username:
        return f"https://t.me/{customer.username}"
    return f"tg://user?id={customer.external_user_id}"


def has_written(db: Session, customer_id: int) -> bool:
    return bool(db.scalar(select(exists().where(Message.customer_id == customer_id, Message.direction == "in"))))


@router.get("/chats", response_class=HTMLResponse)
def chat_list(request: Request, show_ignored: str = "", page: int = 1, db: Session = Depends(get_db)):
    page = max(page, 1)
    last = (select(Message.customer_id, func.max(Message.id).label("last_id"))
            .group_by(Message.customer_id).subquery())
    query = (select(Customer, Message).join(last, last.c.customer_id == Customer.id)
             .join(Message, Message.id == last.c.last_id)
             .order_by(Message.received_at.desc(), Message.id.desc()))
    if not show_ignored:
        query = query.where(Customer.ignored.is_(False))
    rows = db.execute(query.limit(LIST_SIZE + 1).offset((page - 1) * LIST_SIZE)).all()
    carts = dict(db.execute(select(Order.customer_id, Order.status).where(
        Order.status.in_(OPEN_STATUSES), Order.customer_id.in_([c.id for c, _ in rows]))).all())
    return templates.TemplateResponse(request, "chats.html", {
        "rows": rows[:LIST_SIZE], "show_ignored": bool(show_ignored), "page": page, "carts": carts,
        "more": len(rows) > LIST_SIZE,
    })


def thread_context(db: Session, customer: Customer) -> dict:
    messages = list(reversed(db.scalars(
        select(Message).where(Message.customer_id == customer.id)
        .order_by(Message.received_at.desc(), Message.id.desc()).limit(THREAD_SIZE)).all()))
    downloads = {d.message_id: d for d in db.scalars(select(MediaDownload).where(
        MediaDownload.message_id.in_([m.id for m in messages if m.kind == "photo"])))}
    pending = db.scalars(select(Outbox).where(
        Outbox.customer_id == customer.id, Outbox.status.not_in(("sent", "cancelled")))
        .order_by(Outbox.id)).all()
    albums = {}
    for m in messages:
        if m.grouped_id:
            albums[m.grouped_id] = albums.get(m.grouped_id, 0) + 1
    now = datetime.now(UTC)
    auto_msgs = set(db.scalars(select(Outbox.sent_message_id).join(QuickAction, QuickAction.outbox_id == Outbox.id)
                               .where(QuickAction.auto, Outbox.customer_id == customer.id)))
    auto_box = set(db.scalars(select(QuickAction.outbox_id).where(
        QuickAction.auto, QuickAction.outbox_id.in_([o.id for o in pending]))))
    return {
        "auto_msgs": auto_msgs, "auto_box": auto_box,
        "c": customer, "messages": messages, "downloads": downloads, "pending": pending, "albums": albums,
        "stuck": {o.id for o in pending if o.status == "sending" and now - o.created_at > STUCK_AFTER},
        "polling": any(o.status in ("queued", "sending") for o in pending)
                   or any(d.status == "queued" for d in downloads.values()),
    }


def _price_items(request: Request) -> list[compose.PriceItem]:
    items = []
    for n in range(1, compose.MAX_PRICE_ITEMS + 1):
        pid, size = request.query_params.get(f"p{n}", ""), request.query_params.get(f"s{n}", "all")
        if pid.isdigit() and (size in ("all", "full") or (size.isdigit() and 0 < int(size) < 1000)):
            items.append(compose.PriceItem(int(pid), size))
    return items


@router.get("/chats/{customer_id}", response_class=HTMLResponse)
def chat(request: Request, customer_id: int, db: Session = Depends(get_db)):
    customer = get_customer(db, customer_id)
    mode = request.query_params.get("compose", "custom")
    texts = replies.load(db)
    greet = compose.needs_greeting(db, customer_id)
    result = compose.Composed()
    items: list[compose.PriceItem] = []
    if mode == "price":
        made = "make" in request.query_params
        items = _price_items(request) if made else compose.recent_requests(db, customer_id)
        if made:
            result = compose.price_reply(db, items, texts)
            if not items:
                result.problems.append("Choose at least one product.")
        result.text = compose.with_greeting(result.text, texts, greet)
    elif mode in ("cart", "ask_address", "ask_phone", "payment_info"):
        order = cart.open_cart(db, customer_id)
        if order is None or cart.view(db, order).empty:
            result.problems.append("The cart is empty.")
        elif mode == "cart":
            result.text = cart.cart_text(db, order, texts)
        elif mode in ("ask_address", "ask_phone"):
            result.text = texts[mode]
        else:
            result.problems = cart.payment_problems(db, order, customer)
            result.text = "" if result.problems else cart.payment_text(db, order, texts)
        result.text = compose.with_greeting(result.text, texts, greet)
    else:
        mode = "custom"
        result.text = texts["greeting"] + "\n" if greet else ""
    products = db.scalars(select(Product).where(Product.active).order_by(Product.brand, Product.name)).all()
    sizes = sorted({p.size_ml for ps in current_prices(db).values() for p in ps if p.size_ml})
    return templates.TemplateResponse(request, "chat.html", {
        **thread_context(db, customer), **cart_context(db, customer, texts), "mode": mode, "result": result,
        "greet": greet, "tab": request.query_params.get("tab", "chat"),
        "items": items + [compose.PriceItem(0, "all")] * (compose.MAX_PRICE_ITEMS - len(items)),
        "products": products, "sizes": sizes, "can_send": has_written(db, customer_id),
        "key": secrets.token_urlsafe(16), "tg_link": telegram_link(customer), "max_text": MAX_TEXT,
        "paused_until": auto.paused_until(db, customer),
    })


def next_step(db: Session, customer: Customer, order, view) -> dict | None:
    """The one highlighted button for this conversation: list -> confirm -> phone ->
    address -> payment info (the system decides what to ask next, phone first)."""
    if order is None or view.empty:
        return None
    url = f"/chats/{customer.id}"
    if order.status == "cart":
        if order.list_sent_at is None or order.updated_at > order.list_sent_at:
            return {"label": "Send cart list", "href": f"{url}?compose=cart#reply"}
        return {"label": "Customer agreed: mark confirmed", "post": f"{url}/cart/confirm"}
    if order.status == "confirmed":
        missing = cart.missing_contact(order)
        if missing and cart.has_saved_contact(db, order, customer):
            return {"label": "Same phone & address as last time", "post": f"{url}/cart/same-contact"}
        if "phone" in missing:
            return {"label": "Ask for phone", "href": f"{url}?compose=ask_phone#reply"}
        if "address" in missing:
            return {"label": "Ask for address", "href": f"{url}?compose=ask_address#reply"}
        if not cart.payment_problems(db, order, customer):
            return {"label": "Send payment info", "href": f"{url}?compose=payment_info#reply"}
        return None  # red rows in the cart explain what to fix
    if order.status == "waiting_payment":
        return {"label": "Waiting for the payment screenshot", "wait": True}
    if order.status == "photo_received":
        return {"label": "Check the payment screenshot", "href": "/payments"}
    return None


def cart_context(db: Session, customer: Customer, texts: dict[str, str]) -> dict:
    order = cart.open_cart(db, customer.id)
    view = cart.view(db, order) if order else None
    return {
        "order": order, "cart": view, "next_step": next_step(db, customer, order, view),
        "payment_problems": cart.payment_problems(db, order, customer) if order else [],
        "saved_phones": cart.customer_phones(db, customer.id), "max_phones": MAX_PHONES,
        "contact_hint": actions.contact_suggestion(db, customer.id, texts) if order else None,
        "pending_check": db.scalar(select(PaymentCheck).where(
            PaymentCheck.order_id == order.id, PaymentCheck.decision.in_(("pending", "several")),
            PaymentCheck.outbox_id.is_(None))) if order else None,
        "item_size": cart.item_size,
    }


@router.get("/chats/{customer_id}/thread", response_class=HTMLResponse)
def thread(request: Request, customer_id: int, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "_thread.html", thread_context(db, get_customer(db, customer_id)))


@router.post("/chats/{customer_id}/send")
def send(request: Request, customer_id: int, text: str = Form(""), reply_kind: str = Form("custom"),
         key: str = Form(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_customer(db, customer_id)
    text = text.replace("\r\n", "\n").strip()
    if reply_kind not in ("custom", "price", "cart", "ask_address", "ask_phone", "payment_info"):
        raise HTTPException(400, "Unknown reply kind")
    if not has_written(db, customer_id):
        raise HTTPException(400, "This customer has never messaged us; we never message first.")
    if not text or len(text) > MAX_TEXT:
        flash(request, f"Not sent: the message must be 1-{MAX_TEXT} characters.")
        return RedirectResponse(f"/chats/{customer_id}?compose={reply_kind}", status_code=303)
    customer = db.get(Customer, customer_id)
    order = cart.open_cart(db, customer_id, lock=True) if reply_kind in ("cart", "payment_info") else None
    if reply_kind == "payment_info":
        problems = cart.payment_problems(db, order, customer) if order else ["The cart is empty."]
        if problems:
            flash(request, "Not sent: " + " ".join(problems))
            return RedirectResponse(f"/chats/{customer_id}?compose=payment_info#reply", status_code=303)
    outbox_id = db.scalar(insert(Outbox).values(
        customer_id=customer_id, text=text, reply_kind=reply_kind, status="queued",
        idempotency_key=key[:64], created_by=user.id,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(Outbox.id))
    if outbox_id is None:
        flash(request, "Already queued (sent twice by mistake?).")
    else:
        if reply_kind == "cart" and order is not None:
            order.list_sent_at = datetime.now(UTC)
        elif reply_kind == "payment_info":
            cart.payment_info_sent(db, order)
        db.add(AuditLog(user_id=user.id, action="outbox.queue", details={
            "outbox_id": outbox_id, "customer_id": customer_id, "reply_kind": reply_kind, "chars": len(text)}))
        db.commit()
        flash(request, "Queued. It is sent within a few seconds.")
    return RedirectResponse(f"/chats/{customer_id}#bottom", status_code=303)


def _outbox_row(db: Session, customer_id: int, outbox_id: int) -> Outbox:
    row = db.get(Outbox, outbox_id)
    if row is None or row.customer_id != customer_id:
        raise HTTPException(404, "Not found")
    return row


@router.post("/chats/{customer_id}/outbox/{outbox_id}/retry")
def retry(request: Request, customer_id: int, outbox_id: int, db: Session = Depends(get_db),
          user: User = Depends(current_user)):
    row = _outbox_row(db, customer_id, outbox_id)
    if row.status != "failed":
        raise HTTPException(400, "Only failed messages can be retried")
    row.status, row.error = "queued", None
    db.add(AuditLog(user_id=user.id, action="outbox.retry", details={"outbox_id": outbox_id}))
    db.commit()
    flash(request, "Queued again.")
    return RedirectResponse(f"/chats/{customer_id}#bottom", status_code=303)


@router.post("/chats/{customer_id}/outbox/{outbox_id}/cancel")
def cancel(request: Request, customer_id: int, outbox_id: int, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    row = _outbox_row(db, customer_id, outbox_id)
    # A "sending" row that looks stuck may be closed too, after the admin checked Telegram.
    stuck = row.status == "sending" and datetime.now(UTC) - row.created_at > STUCK_AFTER
    if row.status not in ("queued", "failed") and not stuck:
        raise HTTPException(400, "Already sent or being sent")
    if row.status == "queued":
        db.refresh(row, with_for_update=True)  # wait for a listener claim in progress
        if row.status != "queued":
            flash(request, "Too late: it is being sent.")
            return RedirectResponse(f"/chats/{customer_id}#bottom", status_code=303)
    action = db.scalar(select(QuickAction).where(QuickAction.outbox_id == outbox_id, QuickAction.undone_at.is_(None)))
    if action is not None and row.status == "queued":  # a one-tap reply: same as Undo (cart too)
        actions.undo(db, action, user)
    row.status = "cancelled"
    if action is None and row.reply_kind == "payment_info":  # it never went out: still "confirmed"
        order = cart.open_cart(db, customer_id)
        if order is not None and order.status == "waiting_payment":
            order.status, order.payment_info_sent_at = "confirmed", None
    db.add(AuditLog(user_id=user.id, action="outbox.cancel", details={"outbox_id": outbox_id}))
    db.commit()
    flash(request, "Cancelled.")
    return RedirectResponse(f"/chats/{customer_id}#bottom", status_code=303)


@router.post("/messages/{message_id}/photo")
def request_photo(request: Request, message_id: int, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    message = db.get(Message, message_id)
    if message is None or message.kind != "photo":
        raise HTTPException(404, "Photo not found")
    stmt = insert(MediaDownload).values(message_id=message_id, status="queued", requested_by=user.id)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["message_id"], set_={"status": "queued", "error": None, "requested_by": user.id},
        where=MediaDownload.status == "failed"))
    db.add(AuditLog(user_id=user.id, action="media.request", details={"message_id": message_id}))
    db.commit()
    return RedirectResponse(f"/chats/{message.customer_id}#m{message_id}", status_code=303)


@router.get("/media/{message_id}")
def media(message_id: int, db: Session = Depends(get_db)):
    row = db.get(MediaDownload, message_id)
    if row is None or row.status != "done" or not row.path:
        raise HTTPException(404, "Photo not downloaded")
    path = MEDIA_DIR / Path(row.path).name
    media_type = MEDIA_TYPES.get(path.suffix)
    if media_type is None or not path.is_file():
        raise HTTPException(404, "Photo file missing")
    return FileResponse(path, media_type=media_type)


# ---------- cart panel (admin taps; nothing is sent from here) ----------

def _cart_redirect(customer_id: int) -> RedirectResponse:
    return RedirectResponse(f"/chats/{customer_id}?tab=cart#cart", status_code=303)


def _log(db: Session, user: User, action: str, **details) -> None:
    db.add(AuditLog(user_id=user.id, action=action, details=details))


@router.post("/chats/{customer_id}/cart/add")
def cart_add(request: Request, customer_id: int, product_id: int = Form(...), size: str = Form(...),
             quantity: int = Form(1), db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_customer(db, customer_id)
    if db.get(Product, product_id) is None or not (size == "full" or (size.isdigit() and 0 < int(size) < 1000)):
        raise HTTPException(400, "Choose a product and a size")
    order = cart.open_cart(db, customer_id, create=True, lock=True)
    wanted = cart.WantedItem(product_id, None if size == "full" else int(size), size == "full",
                             max(1, min(quantity, cart.MAX_QTY)))
    cart.add_items(db, order, [wanted], None)
    _log(db, user, "cart.add", order_id=order.id, product_id=product_id, size=size, quantity=wanted.quantity)
    db.commit()
    unpriced = cart.view(db, order).unpriced
    flash(request, "Added." + (f" No price yet for {', '.join(unpriced)}." if unpriced else ""))
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/items/{item_id}/remove")
def cart_remove(request: Request, customer_id: int, item_id: int, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    order = cart.open_cart(db, customer_id, lock=True)
    item = db.get(OrderItem, item_id)
    if order is None or item is None or item.order_id != order.id:
        raise HTTPException(404, "Not in the cart")
    cart.remove_item_ids(db, order, [item_id])
    _log(db, user, "cart.remove", order_id=order.id, item_id=item_id)
    db.commit()
    flash(request, "Removed.")
    return _cart_redirect(customer_id)


def _open_order(db: Session, customer_id: int):
    order = cart.open_cart(db, customer_id, lock=True)
    if order is None:
        raise HTTPException(404, "No open cart")
    return order


@router.post("/chats/{customer_id}/cart/confirm")
def cart_confirm(request: Request, customer_id: int, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    order = _open_order(db, customer_id)
    if cart.view(db, order).empty or order.status != "cart":
        raise HTTPException(400, "Nothing to confirm")
    cart.confirm(db, order)
    _log(db, user, "cart.confirm", order_id=order.id)
    db.commit()
    flash(request, "Marked confirmed.")
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/address")
def cart_address(request: Request, customer_id: int, address: str = Form(""),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    customer = get_customer(db, customer_id)
    order = _open_order(db, customer_id)
    cart.set_address(db, order, customer, address.replace("\r\n", "\n").strip()[:500] or None)
    _log(db, user, "cart.address", order_id=order.id)
    db.commit()
    flash(request, "Address saved (also for next time).")
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/phones")
def cart_phone_add(request: Request, customer_id: int, phone: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    customer = get_customer(db, customer_id)
    order = _open_order(db, customer_id)
    phones = find_phones(normalize(phone))
    if not phones:
        flash(request, "Not a Myanmar mobile number (09…).")
    elif not cart.add_phones(db, order, customer, phones[:1], None):
        flash(request, f"Already saved, or {MAX_PHONES} numbers already: remove one first.")
    else:
        _log(db, user, "cart.phone_add", order_id=order.id)
        flash(request, "Phone added.")
    db.commit()
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/phones/{position}/{move}")
def cart_phone_change(request: Request, customer_id: int, position: int, move: str,
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    """move: remove | up (make it the first number, used first on the order)."""
    customer = get_customer(db, customer_id)
    order = _open_order(db, customer_id)
    rows = cart.phone_rows(db, customer_id)
    if not 0 <= position < len(rows) or move not in ("remove", "up"):
        raise HTTPException(400, "No such phone")
    row = rows.pop(position)
    if move == "up":
        rows.insert(max(position - 1, 0), row)
    cart.set_customer_phones(db, customer, rows)
    order.phones = cart.customer_phones(db, customer_id)
    cart.touch(db, order)
    _log(db, user, f"cart.phone_{move}", order_id=order.id)
    db.commit()
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/same-contact")
def cart_same_contact(request: Request, customer_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    customer = get_customer(db, customer_id)
    order = _open_order(db, customer_id)
    if not cart.has_saved_contact(db, order, customer):
        raise HTTPException(400, "Nothing saved from last time")
    cart.use_saved_contact(db, order, customer)
    _log(db, user, "cart.same_contact", order_id=order.id)
    db.commit()
    flash(request, "Using the same phone & address as last time.")
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/refresh-prices")
def cart_refresh(request: Request, customer_id: int, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    order = _open_order(db, customer_id)
    filled = cart.refill_prices(db, order)
    _log(db, user, "cart.refresh_prices", order_id=order.id, filled=filled)
    db.commit()
    flash(request, f"{filled} price(s) filled in." if filled else "No new prices found.")
    return _cart_redirect(customer_id)


@router.post("/chats/{customer_id}/cart/cancel")
def cart_cancel(request: Request, customer_id: int, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    order = _open_order(db, customer_id)
    cart.cancel(db, order)
    _log(db, user, "cart.cancel", order_id=order.id)
    db.commit()
    flash(request, "Cart cancelled.")
    return _cart_redirect(customer_id)
