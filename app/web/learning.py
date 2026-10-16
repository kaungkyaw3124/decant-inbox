"""Teaching cards (preview -> confirm), the Learning page (approve / reject / edit learned
patterns, conflicts), and "price needed" for products a staff member added from a card
(docs/SPEC-v4.md 4.2)."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import hints
from app.learning import cards, patterns
from app.models import (
    AuditLog, Customer, LearnedPattern, Message, MessageReview, Outbox, Product, ProductPrice, QuickAction,
    UnknownRequest, User,
)
from app.models.outbox import MAX_TEXT, UNDO_SECONDS
from app.orders import actions
from app.parser.service import current_result
from app.replies import templates as replies
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import detail_url, flash, get_message, products_for_select, safe_back

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
KIND_TITLES = {"nickname": "📛 Nicknames (ပစ္စည်းနာမည်)", "intent_phrase": "💬 Phrases (လုပ်ချင်တာ)",
               "not_stocked": "🚫 We don't sell (မရှိဘူး)"}
WEEK = timedelta(days=7)


def card_context(db: Session) -> dict:
    """What every teaching card needs besides the card itself."""
    return {"all_products": [p for p in products_for_select(db) if p.active], "intent_choices": cards.INTENT_CHOICES}


def _form_fields(form) -> list[tuple[str, str]]:
    return [(k, str(v)) for k, v in form.multi_items() if k not in ("csrf", "expect")]


def _card_error(request: Request, message_id: int, back: str, note: str) -> RedirectResponse:
    flash(request, note)
    return RedirectResponse(detail_url(message_id, back) + "#card", status_code=303)


@router.post("/messages/{message_id}/teach/preview", response_class=HTMLResponse)
async def teach_preview(request: Request, message_id: int, db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    """Step 1: show what ✅ will do (computed by the same code, then rolled back)."""
    form = await request.form()
    back = safe_back(str(form.get("back", "/")), "/")
    message = get_message(db, message_id)
    answers = cards.read_form(form)
    texts = replies.load(db)
    savepoint = db.begin_nested()
    try:
        applied = cards.apply(db, message, answers, user)
        suggestion = None
        if applied.result is not None and not applied.price_needed:
            suggestion = actions.suggest(db, message, applied.result, texts)
        line = cards.preview_line(db, applied, suggestion)
        draft = _draft(answers) if applied.intent == "question" else None
        if draft:
            line = "ဒီအဖြေကို ဖောက်သည်ဆီ ပို့မယ်။"
    except cards.CardError as exc:
        savepoint.rollback()
        return _card_error(request, message_id, back, str(exc))
    savepoint.rollback()
    return templates.TemplateResponse(request, "card_preview.html", {
        "m": message, "c": db.get(Customer, message.customer_id), "line": line,
        "reply": draft or (suggestion.text if suggestion else None), "learned": applied.learned, "learn": answers.learn,
        "warnings": applied.warnings, "fields": _form_fields(form), "expect": suggestion.fingerprint if suggestion else "",
        "back": back, "undo_seconds": UNDO_SECONDS})


@router.post("/messages/{message_id}/teach")
async def teach_confirm(request: Request, message_id: int, db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    """Step 2: save the answers + patterns, then the normal one-tap action (10 s Undo)."""
    form = await request.form()
    back = safe_back(str(form.get("back", "/")), "/")
    message = get_message(db, message_id)
    texts = replies.load(db)
    try:
        answers = cards.read_form(form)
        applied = cards.apply(db, message, answers, user)
        review = db.scalar(select(MessageReview.status).where(MessageReview.message_id == message.id)) or "new"
        if applied.intent == "question" and not _draft(answers):
            db.rollback()
            if hints.record(db, message.id, form, user):
                db.commit()
            return RedirectResponse(f"/chats/{message.customer_id}#reply", status_code=303)
        if applied.intent == "question":
            note = _send_draft(db, message, _draft(answers), applied, review, user)
            hints.record(db, message.id, form, user)
            db.commit()
            flash(request, note)
            return RedirectResponse(back if back != "/" else "/", status_code=303)
        suggestion = None
        if applied.result is not None and not applied.price_needed:
            suggestion = actions.suggest(db, message, applied.result, texts)
        if suggestion is not None:
            if form.get("expect") and form.get("expect") != suggestion.fingerprint:
                raise actions.Refused("The reply changed meanwhile (price, cart). Check it again.")
            action = actions.perform(db, message, suggestion.fingerprint, user, texts)
            action.undo = {**action.undo, "teach": applied.undo}
            note = f"Done. The reply goes out in {UNDO_SECONDS} s unless you undo." if action.outbox_id else "Done."
        else:
            action = QuickAction(message_id=message.id, customer_id=message.customer_id, kind="teach",
                                 undo={"teach": applied.undo, "review": review}, created_by=user.id)
            db.add(action)
            if applied.intent == "ignore":
                actions.upsert_review(db, message.id, "done", user)
                note = "Done: nothing sent."
            elif applied.price_needed:
                note = "Saved. The owner adds the price, then the list goes out by itself."
            else:
                note = "Saved. Nothing to send automatically: reply in the chat."
        db.flush()
        db.add(AuditLog(user_id=user.id, action="learning.card_confirm", details={
            "message_id": message.id, "quick_action_id": action.id, "intent": applied.intent}))
        hints.record(db, message.id, form, user)
        db.commit()
    except (cards.CardError, actions.Refused) as exc:
        db.rollback()
        return _card_error(request, message_id, back, str(exc))
    flash(request, " ".join([note, *applied.learned, *applied.warnings]))
    return RedirectResponse(back if back != "/" else "/", status_code=303)


def _draft(answers: cards.Answers) -> str:
    return answers.draft[:MAX_TEXT]


def _send_draft(db: Session, message: Message, text: str, applied: cards.Applied, review: str, user: User) -> str:
    """A question answered with the (edited) AI draft: an admin click, queued with the usual
    Undo time. Never automatic (docs/SPEC-v4.6-ai.md S3)."""
    now = datetime.now(UTC)
    box = Outbox(customer_id=message.customer_id, text=text, reply_kind="custom", status="queued",
                 idempotency_key=f"draft-{message.id}-{now.timestamp()}", created_by=user.id,
                 send_after=now + timedelta(seconds=UNDO_SECONDS), source_message_id=message.id,
                 previous_review_status=review)
    db.add(box)
    db.flush()
    action = QuickAction(message_id=message.id, customer_id=message.customer_id, kind="teach", outbox_id=box.id,
                         undo={"teach": applied.undo, "review": review}, created_by=user.id)
    db.add(action)
    actions.upsert_review(db, message.id, "done", user)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="ai.draft_sent", details={
        "message_id": message.id, "quick_action_id": action.id, "outbox_id": box.id, "chars": len(text)}))
    return f"Done. The answer goes out in {UNDO_SECONDS} s unless you undo."


# ---------- price needed ----------

@router.post("/learning/price/{request_id}", dependencies=[Depends(owner_only)])
def add_price(request: Request, request_id: int, price: str = Form(...), full_size_ml: str = Form(""),
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The owner prices a product a staff member added: the waiting list goes out by itself."""
    row = db.get(UnknownRequest, request_id)
    if row is None or row.product_id is None:
        raise HTTPException(404, "Not found")
    amount = cards._int(price, 1, 100_000_000)
    if amount is None:
        flash(request, "Type the price in ကျပ်.")
        return RedirectResponse("/", status_code=303)
    product = db.get(Product, row.product_id)
    bottle = cards._int(full_size_ml, 1, 1000)
    if bottle:
        product.full_size_ml = bottle
    db.add(ProductPrice(product_id=product.id, size_ml=None if row.is_full_bottle else row.size_ml,
                        is_full_bottle=row.is_full_bottle, price_mmk=amount, in_stock=True,
                        effective_from=datetime.now(UTC), created_by=user.id))
    db.add(AuditLog(user_id=user.id, action="learning.price", details={"product_id": product.id, "price": amount}))
    db.flush()
    message = db.get(Message, row.message_id)
    texts = replies.load(db)
    suggestion = actions.suggest(db, message, current_result(db, message.id), texts)
    note = f"Price saved for {product.name}."
    if suggestion is not None:
        try:
            actions.perform(db, message, suggestion.fingerprint, user, texts)
            note += f" The list goes out in {UNDO_SECONDS} s (Undo in the inbox)."
        except actions.Refused as exc:
            note += f" {exc}"
    db.commit()
    flash(request, note)
    return RedirectResponse("/", status_code=303)


# ---------- the Learning page ----------

def handled_this_week(db: Session) -> int:
    """Messages answered (one-tap or auto) with the help of learned patterns in the last 7 days."""
    return db.scalar(select(func.count()).select_from(QuickAction).where(
        QuickAction.undone_at.is_(None), QuickAction.created_at >= datetime.now(UTC) - WEEK,
        QuickAction.undo.has_key("learned")))


@router.get("/learning", response_class=HTMLResponse, dependencies=[Depends(owner_only)])
def learning_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(LearnedPattern, Product, User, Message)
                      .outerjoin(Product, Product.id == LearnedPattern.product_id)
                      .outerjoin(User, User.id == LearnedPattern.taught_by)
                      .outerjoin(Message, Message.id == LearnedPattern.source_message_id)
                      .where(LearnedPattern.status.in_(patterns.LIVE))
                      .order_by(LearnedPattern.kind, LearnedPattern.id.desc())).all()
    pending = {k: [r for r in rows if r[0].kind == k and r[0].status == "pending"] for k in KIND_TITLES}
    approved = [r for r in rows if r[0].status == "approved"]
    return templates.TemplateResponse(request, "learning.html", {
        "pending": pending, "approved": approved, "kind_titles": KIND_TITLES,
        "conflicts": patterns.conflicts(db), "handled_week": handled_this_week(db),
        "settings": patterns.settings(db), "products": [p for p in products_for_select(db) if p.active],
        "intents": [(v, label) for v, label in cards.INTENT_CHOICES if v in patterns.LEARNABLE_INTENTS],
    })


def _pattern(db: Session, pattern_id: int) -> LearnedPattern:
    pattern = db.get(LearnedPattern, pattern_id)
    if pattern is None:
        raise HTTPException(404, "Not found")
    return pattern


@router.post("/learning/{pattern_id}/decide", dependencies=[Depends(owner_only)])
def decide(request: Request, pattern_id: int, status: str = Form(...), db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    pattern = _pattern(db, pattern_id)
    if status not in ("approved", "rejected"):
        raise HTTPException(400, "Unknown decision")
    patterns.decide(db, pattern, status, user)
    db.commit()
    flash(request, f"“{pattern.text}”: {'approved — used automatically from now on' if status == 'approved' else 'removed'}.")
    return RedirectResponse("/learning", status_code=303)


@router.post("/learning/{pattern_id}/edit", dependencies=[Depends(owner_only)])
def edit(request: Request, pattern_id: int, text: str = Form(...), product_id: str = Form(""),
         intent: str = Form(""), db: Session = Depends(get_db), user: User = Depends(current_user)):
    pattern = _pattern(db, pattern_id)
    try:
        patterns.edit(db, pattern, text, user, int(product_id) if product_id.isdigit() else None, intent or None)
        db.commit()
        flash(request, "Saved.")
    except ValueError as exc:
        db.rollback()
        flash(request, str(exc))
    return RedirectResponse("/learning", status_code=303)


@router.post("/learning/conflicts/{conflict_id}", dependencies=[Depends(owner_only)])
def conflict(request: Request, conflict_id: int, use_new: str = Form(...), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    row = db.get(AuditLog, conflict_id)
    if row is None or row.action != "learning.conflict":
        raise HTTPException(404, "Not found")
    note = patterns.resolve_conflict(db, row, use_new == "1", user)
    db.commit()
    flash(request, note)
    return RedirectResponse(safe_back(str(request.query_params.get("back", "/learning")), "/learning"), status_code=303)


@router.post("/settings/learning", dependencies=[Depends(owner_only)])
def learning_settings(request: Request, auto_approve_after: str = Form("3"), greeting: str = Form(""),
                      auto_not_stocked: str = Form(""), greeting_repeat_minutes: str = Form(""),
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        values = {"auto_approve_after": int(auto_approve_after) if auto_approve_after.isdigit() else -1,
                  "greeting": greeting == "1", "auto_not_stocked": auto_not_stocked == "1"}
        if greeting_repeat_minutes.strip():
            values["greeting_repeat_minutes"] = int(greeting_repeat_minutes) if greeting_repeat_minutes.isdigit() else -1
        patterns.set_settings(db, values, user)
        db.add(AuditLog(user_id=user.id, action="learning.settings", details={
            "auto_approve_after": auto_approve_after, "greeting": greeting == "1",
            "auto_not_stocked": auto_not_stocked == "1"}))
        db.commit()
        flash(request, "Learning settings saved.")
    except ValueError as exc:
        db.rollback()
        flash(request, str(exc))
    return RedirectResponse("/learning#settings", status_code=303)
