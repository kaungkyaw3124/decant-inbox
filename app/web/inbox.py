"""Inbox, message detail, human edits of parse results, review status, ignore customer."""
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.models import Customer, Message, MessageReview, ParseResult, Product, ProductAlias, User
from app.models.messages import REVIEW_STATUSES
from app.models.parsing import INTENTS
from app.parser.normalize import normalize
from app.parser.rules import NEEDS_REVIEW_BELOW
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
        q = q.where(cur.product_id == f["product"])
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


def row_context(message, customer, result, product, review) -> dict:
    return {
        "m": message, "c": customer, "r": result, "p": product,
        "status": review.status if review else "new",
        "needs_review": result is None or (result.method != "human" and result.confidence < NEEDS_REVIEW_BELOW),
    }


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
    params = {k: v for k, v in request.query_params.items() if k != "page"}

    def page_url(n: int) -> str:
        return "/?" + urlencode({**params, "page": n})

    return templates.TemplateResponse(request, "inbox.html", {
        "rows": [row_context(*r) for r in rows[:PAGE_SIZE]], "f": f,
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
    return templates.TemplateResponse(request, "message.html", {
        "m": message, "c": db.get(Customer, message.customer_id),
        "r": current[0], "p": current[1], "history": history,
        "review": review, "reviewer": reviewer, "status": review.status if review else "new",
        "intents": INTENTS, "statuses": REVIEW_STATUSES, "products": products_for_select(db),
        "back": safe_back(back, "/"), "needs_review_below": NEEDS_REVIEW_BELOW,
    })


@router.post("/messages/{message_id}/parse")
def edit_parse(
    request: Request, message_id: int,
    intent: str = Form(...), product_id: str = Form(""), size_ml: str = Form(""),
    quantity: str = Form("1"), alias: str = Form(""), back: str = Form("/"),
    db: Session = Depends(get_db),
):
    get_message(db, message_id)
    if intent not in INTENTS:
        raise HTTPException(400, "Unknown intent")
    pid = int(product_id) if product_id.isdigit() else None
    if pid is not None and db.get(Product, pid) is None:
        raise HTTPException(400, "Unknown product")
    size = int(size_ml) if size_ml.strip().isdigit() and 0 < int(size_ml) < 1000 else None
    qty = int(quantity) if quantity.strip().isdigit() and 0 < int(quantity) < 100 else 1

    db.execute(update(ParseResult).where(ParseResult.message_id == message_id, ParseResult.is_current)
               .values(is_current=False))
    db.flush()
    db.add(ParseResult(message_id=message_id, intent=intent, product_id=pid, size_ml=size,
                       quantity=qty, confidence=1.0, method="human",
                       parser_version=HUMAN_VERSION, is_current=True))
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
    values = {"message_id": message_id, "status": status, "reviewed_by": user.id,
              "reviewed_at": datetime.now(UTC)}
    if note is not None:
        values["note"] = note.strip() or None
    stmt = insert(MessageReview).values(**values)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["message_id"], set_={k: v for k, v in values.items() if k != "message_id"}
    ))
    db.commit()


@router.post("/messages/{message_id}/review")
def review_message(
    request: Request, message_id: int, status: str = Form(...), note: str | None = Form(None),
    back: str = Form("/"), db: Session = Depends(get_db), user: User = Depends(current_user),
):
    get_message(db, message_id)
    set_review(db, message_id, status, note, user)
    if request.headers.get("hx-request"):  # inbox quick button: re-render just this row
        row = db.execute(inbox_query({
            "status": "all", "intent": "all", "product": None, "needs_review": False,
            "show_ignored": True, "q": "",
        }).where(Message.id == message_id)).one()
        return templates.TemplateResponse(request, "_row.html", row_context(*row))
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
