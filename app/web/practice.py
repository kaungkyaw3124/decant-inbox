"""Practice mode (/practice, docs/SPEC-v4.md 4.5): staff try teaching cards and one-tap
buttons on practice messages, with the real code, and see ✅/❌ against the right answer.

Each step runs in a sandbox: one connection, one outer transaction that is always rolled
back; the code's own commits only release savepoints (join_transaction_mode). Nothing is
visible to the listener or the worker (never committed), so nothing is saved or sent.
The score lives in the session cookie."""
import csv
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import engine
from app.learning import cards
from app.models import Customer, Message, ParseItem, ParseResult, Product, User
from app.orders import actions
from app.parser.service import current_result, load_aliases, parse_message
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.learning import card_context

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "synthetic_messages.csv"
NOT_STOCKED = "not_stocked"  # expected answer: "we don't sell it"
PRACTICE_INTENTS = ("buy", "ask_price", "ask_stock", "greeting")
# v4 examples on top of the fixture: learned words, an unknown intent phrase, a perfume we don't sell
V4_EXAMPLES = (
    ("v1", "ysl edp 5ml ယူမယ်", "buy", "Y Eau de Parfum", 5),
    ("v2", "stw intensely 5ml လေးထည့်ထားပေး", "buy", "Stronger With You Intensely", 5),
    ("v3", "liquid brun 5ml ရှိလား", "ask_stock", NOT_STOCKED, 5),
    ("v4", "sauvage edp 10ml လည်း ယူမယ်", "buy", "Sauvage Eau de Parfum", 10),
)


@dataclass(frozen=True)
class Exercise:
    key: str
    text: str
    intent: str
    product: str | None  # product name, NOT_STOCKED, or None (greeting)
    size_ml: int | None


@dataclass
class Answer:
    intent: str | None
    product: str | None
    size_ml: int | None


def _fixture() -> list[Exercise]:
    if not FIXTURE.exists():
        return []
    with FIXTURE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for row in rows:
        one_item = ";" not in (row["items"] or "") and "?" not in (row["items"] or "")
        if row["intent"] in PRACTICE_INTENTS and one_item and (row["product"] or row["intent"] == "greeting") \
                and (row["size_ml"] or row["intent"] == "greeting"):
            out.append(Exercise(row["message_id"], row["text"], row["intent"], row["product"] or None,
                                int(row["size_ml"]) if row["size_ml"] else None))
    return out


def exercises(db: Session) -> list[Exercise]:
    """Practice messages whose right answer exists in today's product list."""
    names = set(db.scalars(select(Product.name).where(Product.active)))
    items = _fixture() + [Exercise(*e) for e in V4_EXAMPLES]
    return [e for e in items if e.product is None or e.product in names
            or (e.product == NOT_STOCKED and not any(e.text.split()[0] in n.lower() for n in names))]


@contextmanager
def sandbox() -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


def _message(session: Session, exercise: Exercise) -> Message:
    """The practice customer + message, parsed by the real parser (inside the sandbox)."""
    key = f"practice-{uuid4().hex[:12]}"
    customer = Customer(channel="practice", external_user_id=key, display_name="🎓 လေ့ကျင့်ခန်း ဖောက်သည်")
    session.add(customer)
    session.flush()
    message = Message(channel="practice", external_chat_id=key, external_message_id="1", customer_id=customer.id,
                      raw_text=exercise.text, received_at=datetime.now(UTC), direction="in", kind="text")
    session.add(message)
    session.flush()
    parse_message(session, message, load_aliases(session))
    return message


def _answer(session: Session, result: ParseResult | None, not_stocked: bool = False) -> Answer:
    if result is None:
        return Answer(None, None, None)
    item = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                           .order_by(ParseItem.position)).first()
    product = session.get(Product, item.product_id) if item and item.product_id else None
    name = NOT_STOCKED if not_stocked else (product.name if product else None)
    return Answer(result.intent, name, item.size_ml if item else result.size_ml)


def right(exercise: Exercise, answer: Answer) -> bool:
    if answer.intent != exercise.intent:
        return False
    if exercise.product is not None and answer.product != exercise.product:
        return False
    return exercise.size_ml is None or answer.size_ml == exercise.size_ml


def _score(request: Request) -> dict[str, bool]:
    return request.session.setdefault("practice", {})


def _exercise(db: Session, n: int) -> tuple[Exercise, int]:
    items = exercises(db)
    if not 1 <= n <= len(items):
        raise HTTPException(404, "Not found")
    return items[n - 1], len(items)


def _context(db: Session, request: Request, n: int, total: int, exercise: Exercise) -> dict:
    score = _score(request)
    return {"n": n, "total": total, "exercise": exercise, "right_count": sum(score.values()), "done_count": len(score),
            "not_stocked": NOT_STOCKED, **card_context(db)}


@router.get("/practice", response_class=HTMLResponse)
def practice_home(request: Request, db: Session = Depends(get_db)):
    score = _score(request)
    return templates.TemplateResponse(request, "practice.html", {
        "step": "home", "total": len(exercises(db)), "right_count": sum(score.values()), "done_count": len(score)})


@router.post("/practice/reset")
def practice_reset(request: Request):
    request.session["practice"] = {}
    return RedirectResponse("/practice/1", status_code=303)


@router.get("/practice/{n}", response_class=HTMLResponse)
def practice_step(request: Request, n: int, db: Session = Depends(get_db)):
    exercise, total = _exercise(db, n)
    with sandbox() as session:
        message = _message(session, exercise)
        card = cards.build(session, message)
        suggestion = None if card else actions.suggest(session, message, current_result(session, message.id),
                                                       replies.load(session))
        return templates.TemplateResponse(request, "practice.html", {
            "step": "question", "m": message, "card": card, "quick": suggestion,
            "app_understood": _answer(session, current_result(session, message.id)), "card_action": f"/practice/{n}", "back": f"/practice/{n}", **_context(db, request, n, total, exercise)})


@router.post("/practice/{n}", response_class=HTMLResponse)
async def practice_answer(request: Request, n: int, db: Session = Depends(get_db),
                          user: User = Depends(current_user)):
    exercise, total = _exercise(db, n)
    form = await request.form()
    choice = str(form.get("choice", "card"))
    with sandbox() as session:
        message = _message(session, exercise)
        texts = replies.load(session)
        app_answer = _answer(session, current_result(session, message.id))
        reply = None
        if choice in ("tap", "wrong"):  # one-tap button: right if the app understood it right
            app_right = right(exercise, app_answer)
            ok = app_right if choice == "tap" else not app_right
            if choice == "tap":
                suggestion = actions.suggest(session, message, current_result(session, message.id), texts)
                if suggestion is not None:
                    action = actions.perform(session, message, suggestion.fingerprint, session.get(User, user.id),
                                             texts)
                    reply = suggestion.text if action.outbox_id else None
            given = app_answer
        else:  # teaching card: the same code as the inbox card
            answers = cards.read_form(form)
            try:
                applied = cards.apply(session, message, answers, session.get(User, user.id))
            except cards.CardError as exc:
                card = cards.build(session, message)
                return templates.TemplateResponse(request, "practice.html", {
                    "step": "question", "m": message, "card": card, "quick": None, "error": str(exc),
                    "card_action": f"/practice/{n}", "back": f"/practice/{n}",
                    **_context(db, request, n, total, exercise)})
            given = _answer(session, applied.result, not_stocked=NOT_STOCKED in answers.products.values())
            if applied.result is None:
                given.intent = applied.intent
            if applied.result is not None and not applied.price_needed:
                suggestion = actions.suggest(session, message, applied.result, texts)
                if suggestion is not None:
                    actions.perform(session, message, suggestion.fingerprint, session.get(User, user.id), texts)
                    reply = suggestion.text
            ok = right(exercise, given)
            app_right = None
        score = _score(request)
        score[exercise.key] = ok
        request.session["practice"] = score
        return templates.TemplateResponse(request, "practice.html", {
            "step": "result", "ok": ok, "choice": choice, "given": given, "app_answer": app_answer,
            "app_right": app_right, "reply": reply, "m": message, **_context(db, request, n, total, exercise)})
