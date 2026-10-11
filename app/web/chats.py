"""Chats: conversation list, conversation view, replies (Custom / Price), photos on demand.

The dashboard never talks to Telegram: "Send" only adds an outbox row, and the listener
(the one process with the Telegram session) sends it. Photos are downloaded by the
listener when an admin taps "Show photo".
"""
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AuditLog, Customer, MediaDownload, Message, Outbox, Product, User
from app.models.outbox import MAX_TEXT, MEDIA_DIR
from app.pricing.prices import current_prices
from app.replies import compose
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash, upsert_review

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
    return templates.TemplateResponse(request, "chats.html", {
        "rows": rows[:LIST_SIZE], "show_ignored": bool(show_ignored), "page": page,
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
    return {
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
    else:
        mode = "custom"
        result.text = texts["greeting"] + "\n" if greet else ""
    products = db.scalars(select(Product).where(Product.active).order_by(Product.brand, Product.name)).all()
    sizes = sorted({p.size_ml for ps in current_prices(db).values() for p in ps if p.size_ml})
    return templates.TemplateResponse(request, "chat.html", {
        **thread_context(db, customer), "mode": mode, "result": result, "greet": greet,
        "items": items + [compose.PriceItem(0, "all")] * (compose.MAX_PRICE_ITEMS - len(items)),
        "products": products, "sizes": sizes, "can_send": has_written(db, customer_id),
        "key": secrets.token_urlsafe(16), "tg_link": telegram_link(customer), "max_text": MAX_TEXT,
    })


@router.get("/chats/{customer_id}/thread", response_class=HTMLResponse)
def thread(request: Request, customer_id: int, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "_thread.html", thread_context(db, get_customer(db, customer_id)))


@router.post("/chats/{customer_id}/send")
def send(request: Request, customer_id: int, text: str = Form(""), reply_kind: str = Form("custom"),
         key: str = Form(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_customer(db, customer_id)
    text = text.replace("\r\n", "\n").strip()
    if reply_kind not in ("custom", "price"):
        raise HTTPException(400, "Unknown reply kind")
    if not has_written(db, customer_id):
        raise HTTPException(400, "This customer has never messaged us; we never message first.")
    if not text or len(text) > MAX_TEXT:
        flash(request, f"Not sent: the message must be 1-{MAX_TEXT} characters.")
        return RedirectResponse(f"/chats/{customer_id}?compose={reply_kind}", status_code=303)
    outbox_id = db.scalar(insert(Outbox).values(
        customer_id=customer_id, text=text, reply_kind=reply_kind, status="queued",
        idempotency_key=key[:64], created_by=user.id,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(Outbox.id))
    if outbox_id is None:
        flash(request, "Already queued (sent twice by mistake?).")
    else:
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
    row.status = "cancelled"
    if row.source_message_id:  # a one-tap reply: same as Undo, restore the message status
        upsert_review(db, row.source_message_id, row.previous_review_status or "new", None, user)
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
