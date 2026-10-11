"""Inbox, message detail, human edits of parse results, review status, ignore customer."""
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.models import (
    Customer, Message, MessageReview, ParseItem, ParseResult, Product, ProductAlias, QuickAction, User,
)
from app.models.messages import REVIEW_STATUSES
from app.models.parsing import INTENTS
from app.parser.normalize import normalize
from app.models.outbox import UNDO_SECONDS
from app.parser.rules import NEEDS_REVIEW_BELOW
from app.orders import actions
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
PAGE_SIZE = 50
HUMAN_VERSION = "human"


def flash(request: Request, text: str) -> None:
    request.session["flash"] = text


def safe_back(path: str, default: str) -> str:
    """Only allow local paths as redirect targets."""
    return path if path.startswith("/") and not path.startswith(("//", "/\\")) else default


def detail_url(message_id: int, back: str) -> str:
    return f"/messages/{message_id}?back={quote(safe_back(back, '/'), safe='')}"


def products_for_select(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).order_by(Product.active.desc(), Product.brand, Product.name)))


def inbox_query(f: dict):
    cur = aliased(ParseResult)
    q = (
        select(Message, Customer, cur, Product, MessageReview)
        .join(Customer, Customer.id == Message.customer_id)
        .outerjoin(cur, and_(cur.message_id == Message.id, cur.is_current))
        .outerjoin(Product, Product.id == cur.product_id)
        .outerjoin(MessageReview, MessageReview.message_id == Message.id)
        .where(Message.direction == "in")
    )
    if f["status"] == "new":
        q = q.where(or_(MessageReview.id.is_(None), MessageReview.status == "new"))
    elif f["status"] in REVIEW_STATUSES:
        q = q.where(MessageReview.status == f["status"])
    if f["intent"] == "requests":
        q = q.where(or_(cur.id.is_(None), cur.intent != "other"))
    elif f["intent"] in INTENTS:
        q = q.where(cur.intent == f["intent"])
    if f["product"]:
        in_items = select(ParseItem.id).where(ParseItem.parse_result_id == cur.id,
                                              ParseItem.product_id == f["product"]).exists()
        q = q.where(or_(cur.product_id == f["product"], in_items))
    if f["needs_review"]:
        q = q.where(or_(cur.id.is_(None),
                        and_(cur.method != "human", cur.confidence < NEEDS_REVIEW_BELOW)))
    if not f["show_ignored"]:
        q = q.where(Customer.ignored.is_(False))
    if f["q"]:
        q = q.where(or_(
            Message.raw_text.icontains(f["q"], autoescape=True),
            Message.normalized_text.icontains(normalize(f["q"]), autoescape=True),
            Customer.display_name.icontains(f["q"], autoescape=True),
            Customer.username.icontains(f["q"], autoescape=True),
        ))
    return q.order_by(Message.received_at.desc(), Message.id.desc())


def row_context(message, customer, result, product, review, quick_info: dict | None = None) -> dict:
    return {
        "m": message, "c": customer, "r": result, "p": product,
        "status": review.status if review else "new",
        "needs_review": result is None or (result.method != "human" and result.confidence < NEEDS_REVIEW_BELOW),
        **(quick_info or {"quick": None, "quick_action": None, "items": []}),
    }


def load_items(db: Session, result_ids: list[int]) -> dict[int, list[tuple[ParseItem, Product | None]]]:
    out: dict[int, list] = {}
    if result_ids:
        for item, product in db.execute(
                select(ParseItem, Product).outerjoin(Product, Product.id == ParseItem.product_id)
                .where(ParseItem.parse_result_id.in_(result_ids)).order_by(ParseItem.position)):
            out.setdefault(item.parse_result_id, []).append((item, product))
    return out


def quick_infos(db: Session, rows, texts: dict[str, str] | None = None) -> dict[int, dict]:
    """Per message: the one-tap action it can get (quick) or already got (quick_action)."""
    texts = texts or replies.load(db)
    made = actions.latest_actions(db, [r[0].id for r in rows])
    items = load_items(db, [r[2].id for r in rows if r[2] is not None])
    return {
        m.id: {"quick_action": made.get(m.id), "items": items.get(r.id, []) if r else [],
               "quick": None if m.id in made or c.ignored else actions.suggest(db, m, r, texts)}
        for m, c, r, *_ in rows
    }


def row_by_id(db: Session, message_id: int) -> dict:
    row = db.execute(inbox_query({
        "status": "all", "intent": "all", "product": None, "needs_review": False,
        "show_ignored": True, "q": "",
    }).where(Message.id == message_id)).one()
    return row_context(*row, quick_infos(db, [row])[message_id])


@router.get("/", response_class=HTMLResponse)
def inbox(
    request: Request,
    status: str = "new", intent: str = "requests", product: str = "", needs_review: str = "",
    show_ignored: str = "", q: str = "", page: int = 1,
    db: Session = Depends(get_db),
):
    f = {
        "status": status, "intent": intent, "product": int(product) if product.isdigit() else None,
        "needs_review": bool(needs_review), "show_ignored": bool(show_ignored), "q": q.strip(),
    }
    page = max(page, 1)
    rows = db.execute(inbox_query(f).limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE)).all()
    infos = quick_infos(db, rows[:PAGE_SIZE])
    params = {k: v for k, v in request.query_params.items() if k != "page"}

    def page_url(n: int) -> str:
        return "/?" + urlencode({**params, "page": n})

    return templates.TemplateResponse(request, "inbox.html", {
        "rows": [row_context(*r, infos[r[0].id]) for r in rows[:PAGE_SIZE]], "f": f,
        "newer_url": page_url(page - 1) if page > 1 else None,
        "older_url": page_url(page + 1) if len(rows) > PAGE_SIZE else None,
        "back": "/?" + request.url.query if request.url.query else "/",
        "intents": INTENTS, "statuses": REVIEW_STATUSES, "products": products_for_select(db),
    })


def get_message(db: Session, message_id: int) -> Message:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(404, "Message not found")
    return message


@router.get("/messages/{message_id}", response_class=HTMLResponse)
def message_detail(request: Request, message_id: int, back: str = "/", db: Session = Depends(get_db)):
    message = get_message(db, message_id)
    history = db.execute(
        select(ParseResult, Product).outerjoin(Product, Product.id == ParseResult.product_id)
        .where(ParseResult.message_id == message_id).order_by(ParseResult.id.desc())
    ).all()
    current = next(((r, p) for r, p in history if r.is_current), (None, None))
    review = db.scalar(select(MessageReview).where(MessageReview.message_id == message_id))
    reviewer = db.get(User, review.reviewed_by) if review and review.reviewed_by else None
    customer = db.get(Customer, message.customer_id)
    info = quick_infos(db, [(message, customer, current[0])])[message_id]
    return templates.TemplateResponse(request, "message.html", {
        **info, "undo_seconds": UNDO_SECONDS,
        "m": message, "c": customer,
        "r": current[0], "p": current[1], "history": history,
        "review": review, "reviewer": reviewer, "status": review.status if review else "new",
        "intents": INTENTS, "statuses": REVIEW_STATUSES, "products": products_for_select(db),
        "back": safe_back(back, "/"), "needs_review_below": NEEDS_REVIEW_BELOW,
    })


@router.post("/messages/{message_id}/parse")
def edit_parse(
    request: Request, message_id: int,
    intent: str = Form(...), product_id: str = Form(""), size_ml: str = Form(""),
    quantity: str = Form("1"), full_bottle: str = Form(""), alias: str = Form(""), back: str = Form("/"),
    db: Session = Depends(get_db),
):
    get_message(db, message_id)
    if intent not in INTENTS:
        raise HTTPException(400, "Unknown intent")
    pid = int(product_id) if product_id.isdigit() else None
    if pid is not None and db.get(Product, pid) is None:
        raise HTTPException(400, "Unknown product")
    full = full_bottle == "1"
    size = None if full else int(size_ml) if size_ml.strip().isdigit() and 0 < int(size_ml) < 1000 else None
    qty = int(quantity) if quantity.strip().isdigit() and 0 < int(quantity) < 100 else 1

    db.execute(update(ParseResult).where(ParseResult.message_id == message_id, ParseResult.is_current)
               .values(is_current=False))
    db.flush()
    result = ParseResult(message_id=message_id, intent=intent, product_id=pid, size_ml=size,
                         quantity=qty, confidence=1.0, method="human",
                         parser_version=HUMAN_VERSION, is_current=True)
    db.add(result)
    db.flush()
    if pid is not None or size is not None or full:  # a correction is one item
        db.add(ParseItem(parse_result_id=result.id, position=0, product_id=pid, size_ml=size,
                         is_full_bottle=full, quantity=qty))
    note = "Saved."
    alias_norm = normalize(alias)
    if alias_norm and pid is not None:
        if len(alias_norm) < 2:
            note = "Saved. Alias too short, not added."
        else:
            added = db.execute(insert(ProductAlias).values(
                product_id=pid, alias_text=alias.strip(), normalized_alias=alias_norm, source="learned",
            ).on_conflict_do_nothing()).rowcount
            note = f"Saved. Alias “{alias.strip()}” added." if added else "Saved. Alias already existed."
    elif alias_norm:
        note = "Saved. Alias not added: choose a product first."
    db.commit()
    flash(request, note)
    return RedirectResponse(detail_url(message_id, back), status_code=303)


def set_review(db: Session, message_id: int, status: str, note: str | None, user: User) -> None:
    if status not in REVIEW_STATUSES:
        raise HTTPException(400, "Unknown status")
    actions.upsert_review(db, message_id, status, user, note)
    db.commit()


@router.post("/messages/{message_id}/review")
def review_message(
    request: Request, message_id: int, status: str = Form(...), note: str | None = Form(None),
    back: str = Form("/"), db: Session = Depends(get_db), user: User = Depends(current_user),
):
    get_message(db, message_id)
    set_review(db, message_id, status, note, user)
    if request.headers.get("hx-request"):  # inbox quick button: re-render just this row
        return templates.TemplateResponse(request, "_row.html", row_by_id(db, message_id))
    flash(request, f"Marked {status}.")
    return RedirectResponse(detail_url(message_id, back), status_code=303)


@router.post("/customers/{customer_id}/ignored")
def ignore_customer(
    request: Request, customer_id: int, ignored: str = Form(...), back: str = Form("/"),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    customer.ignored = ignored == "1"
    db.commit()
    flash(request, "Customer ignored: their messages are hidden from the inbox."
          if customer.ignored else "Customer no longer ignored.")
    return RedirectResponse(safe_back(back, "/"), status_code=303)


@router.get("/messages/{message_id}/row", response_class=HTMLResponse)
def message_row(request: Request, message_id: int, db: Session = Depends(get_db)):
    """One inbox row (htmx refresh while a quick reply is waiting or sending)."""
    get_message(db, message_id)
    return templates.TemplateResponse(request, "_row.html", row_by_id(db, message_id))


@router.post("/messages/{message_id}/quick")
def quick_action(
    request: Request, message_id: int, expect: str = Form(...), back: str = Form("/"),
    address: str | None = Form(None), db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """One tap: do the suggested action (reply waits UNDO_SECONDS) and mark the message done.
    address: the admin's edited version of the address to save (contact actions)."""
    message = get_message(db, message_id)
    try:
        action = actions.perform(db, message, expect, user, replies.load(db), address)
        db.commit()
        note = None
    except actions.Refused as exc:
        db.rollback()
        note = str(exc)
    if request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "_row.html", {**row_by_id(db, message_id), "quick_error": note})
    flash(request, note or ("Done. The reply goes out in "
                            f"{UNDO_SECONDS} s unless you undo." if action.outbox_id else "Done."))
    if back.startswith("/chats/"):  # tapped in the cart panel
        return RedirectResponse(safe_back(back, "/") + "#cart", status_code=303)
    return RedirectResponse(detail_url(message_id, back), status_code=303)


@router.post("/quick/{action_id}/undo")
def undo_action(
    request: Request, action_id: int, back: str = Form("/"),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    action = db.scalar(select(QuickAction).where(QuickAction.id == action_id).with_for_update())
    if action is None:
        raise HTTPException(404, "Not found")
    try:
        actions.undo(db, action, user)
        db.commit()
        note = None
    except actions.Refused as exc:
        db.rollback()
        note = str(exc)
    if request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "_row.html", {**row_by_id(db, action.message_id), "quick_error": note})
    flash(request, note or "Undone.")
    return RedirectResponse(detail_url(action.message_id, back), status_code=303)
