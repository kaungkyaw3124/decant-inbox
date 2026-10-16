"""SHADOW mode (docs/SPEC-v4.6-ai.md S3): the AI's checked answer pre-selects the teaching
card's answers ("🧠 AI suggests" + the reason). A person checks and taps ✅ (or changes
something); ai_calls.decision then becomes accepted / corrected.

The card's questions come from the rules' items (by position). AI items are paired with them:
AI items for products the rules already named for sure are set aside, the rest go to the
questions in order. Intent: when the AI's intent differs from the rules', the card asks
"what do they want?" with the AI's answer pre-selected (a question shows the AI's draft answer,
which a person edits and sends; never automatic)."""
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import NOT_IN_LIST_HINT
from app.ai.types import AIItem, AIResult
from app.models import AICall, AuditLog, Product, User

# the AI's intent -> the card's "what do they want?" answer
CARD_INTENT = {"buy": "buy", "ask_price": "ask_price", "ask_stock": "ask_stock", "remove": "remove",
               "cancel_order": "cancel_order", "ask_delivery": "ask_delivery", "previous_item": "previous_item",
               "greeting": "greeting", "question": "question", "other": "ignore"}


@dataclass
class Hint:
    call_id: int
    reason: str
    confidence: float
    products: dict[int, str] = field(default_factory=dict)  # position -> product id | "not_stocked"
    sizes: dict[int, str] = field(default_factory=dict)  # position -> "5" | "full"
    intent: str | None = None
    nicknames: dict[int, str] = field(default_factory=dict)
    phrase: str | None = None
    draft: str | None = None

    @property
    def preset(self) -> dict[str, str]:
        """The form fields the AI pre-selected (compared with what the admin sends)."""
        out = {f"p{pos}": v for pos, v in self.products.items()}
        out.update({f"size{pos}": v for pos, v in self.sizes.items()})
        if self.intent:
            out["intent"] = self.intent
        return out

    @property
    def preset_json(self) -> str:
        return json.dumps(self.preset, sort_keys=True)

    @property
    def percent(self) -> int:
        return round(self.confidence * 100)


def latest(session: Session, message_id: int) -> tuple[AICall, AIResult] | None:
    call = session.scalar(select(AICall).where(AICall.message_id == message_id, AICall.ok,
                                               AICall.decision.in_(("shadow", "accepted", "corrected"))))
    if call is None or not call.result_json:
        return None
    try:
        return call, AIResult.from_json(call.result_json)
    except (KeyError, TypeError, ValueError):
        return None


def _size_value(item: AIItem, allowed: list[int | None]) -> str | None:
    if item.is_full and None in allowed:
        return "full"
    if item.size_ml is not None and item.size_ml in allowed:
        return str(item.size_ml)
    return None


def apply(session: Session, card) -> None:
    """Fill card.ai (and adjust the card) from the message's AI answer, if there is one."""
    found = latest(session, card.message.id)
    if found is None:
        return
    call, ai = found
    from app.learning import cards  # late import: cards imports this module lazily too

    hint = Hint(call.id, ai.reason, ai.confidence)
    nick_for = {x.product_id: x.text for x in ai.learn if x.kind == "nickname"}
    not_stocked_words = [x.text for x in ai.learn if x.kind == "not_stocked"]
    rule_items = cards._items(session, card.result)
    asked = {q.position for q in card.products}
    remaining = list(ai.items)
    for item in rule_items:  # products the rules named for sure are not questions
        if item.position not in asked and item.product_id:
            same = next((a for a in remaining if a.product_id == item.product_id), None)
            if same is not None:
                remaining.remove(same)
    paired: dict[int, AIItem] = {}
    for q, item in zip(sorted(card.products, key=lambda q: q.position), remaining):
        paired[q.position] = item
        if item.product_id is not None:
            hint.products[q.position] = str(item.product_id)
            if all(p.id != item.product_id for p in q.options):
                product = session.get(Product, item.product_id)
                if product is not None and product.active:
                    q.options = [product, *q.options][:cards.MAX_OPTIONS]
            if item.product_id in nick_for:
                hint.nicknames[q.position] = nick_for[item.product_id]
        elif item.not_in_list and ai.confidence >= NOT_IN_LIST_HINT:
            hint.products[q.position] = "not_stocked"
            hint.nicknames[q.position] = next(
                (w for w in not_stocked_words if w.lower() == item.not_in_list.lower()), item.not_in_list)
    for q in card.sizes:
        item = paired.get(q.position)
        if item is None:
            rule = next((i for i in rule_items if i.position == q.position), None)
            item = next((a for a in ai.items if rule is not None and a.product_id == rule.product_id), None)
        if item is not None and (value := _size_value(item, q.sizes)):
            hint.sizes[q.position] = value
    intent = CARD_INTENT.get(ai.intent)
    if intent and (card.ask_intent or intent != card.result.intent):
        card.ask_intent = True
        hint.intent = intent
        phrases = [x.text for x in ai.learn if x.kind == "intent_phrase"]
        if phrases:
            hint.phrase = phrases[0]
        elif not card.phrase:
            names = [i.name_text or i.unknown_text or "" for i in rule_items]
            card.phrase = cards.propose_phrase(session, card.message.normalized_text, names)
    if ai.intent == "question":
        hint.draft = ai.draft_answer or ""
    card.ai = hint


def record(session: Session, message_id: int, form, user: User) -> str | None:
    """The admin confirmed a card that had AI answers: accepted (nothing changed) or corrected."""
    call_id = str(form.get("ai_call") or "")
    if not call_id.isdigit():
        return None
    call = session.get(AICall, int(call_id))
    if call is None or call.message_id != message_id or call.decision not in ("shadow", "accepted", "corrected",
                                                                               "unused"):
        return None
    try:
        preset = json.loads(str(form.get("ai_hint") or "{}"))
    except ValueError:
        preset = {}
    changed = sorted(k for k, v in preset.items() if str(form.get(_field(k, form)) or "") != v)
    if preset.get("intent") == "question" and "draft" in form:
        if " ".join(str(form.get("draft") or "").split()) != " ".join((_draft(call) or "").split()):
            changed.append("draft")
    decision = "unused" if not preset else "corrected" if changed else "accepted"
    # wrong product (docs/SPEC-v4.7-graduation.md): the AI named a product, the admin chose another one
    # (or "we don't sell it"); the AI's "we don't sell it" changed to a product is a normal correction
    wrong = any(k.startswith("p") and preset[k].isdigit() and str(form.get(_field(k, form)) or "") != preset[k]
                for k in changed if k in preset)
    session.add(AuditLog(user_id=user.id, action=f"ai.{decision}", details={
        "ai_call_id": call.id, "message_id": message_id, "changed": changed, "wrong_product": wrong}))
    if decision == "unused":
        call.decision, call.decided_by = decision, user.id
        return decision
    from app.ai import graduation  # late import: graduation -> service -> this package

    graduation.record_decision(session, call, decision, user, wrong)
    return decision


def _field(key: str, form) -> str:
    """A product answer picked with 🔍 search counts as that product."""
    if key.startswith("p") and key[1:].isdigit() and str(form.get(f"search{key[1:]}") or "").isdigit():
        return f"search{key[1:]}"
    return key


def _draft(call: AICall) -> str | None:
    return (call.result_json or {}).get("draft_answer")
