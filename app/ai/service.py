"""When to ask the AI, the ai_calls bookkeeping, and AUTO mode (docs/SPEC-v4.6-ai.md S1, S3, S4).

Runs in the parser worker, AFTER the rules, only for messages the rules are not certain about
(and never for photos, payments or messages an approved learned pattern handles). One call per
message at most; every call (or skipped call) leaves one ai_calls row.

  OFF     nothing is called
  SHADOW  the checked result pre-fills the teaching card (hints.py); a person decides
  AUTO    certain enough -> a parse result method="ai" and the normal auto engine continues
          (same safety rules); otherwise SHADOW behaviour
Logs only ids, counts and error kinds, never message text or the key.
"""
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.ai import checker, prompt, providers
from app.ai import settings as ai_settings
from app.ai.providers import AIError
from app.ai.types import AIResult
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AICall, AuditLog, Customer, Message, ParseItem, ParseResult, UnknownRequest
from app.parser.normalize import normalize

log = logging.getLogger("ai")
WINDOW = timedelta(hours=24)  # only fresh messages (never history imports or old re-parses)
UNSURE_MATCHES = ("fuzzy", "multiple", "ambiguous", "partial", "context", "none")
PRODUCT_INTENTS = ("buy", "ask_price", "ask_stock", "remove")
# AUTO may act on these (cancel_order only with an open cart; previous_item only when the history has it)
AUTO_INTENTS = ("buy", "ask_price", "ask_stock", "remove", "cancel_order", "confirm", "address", "greeting",
                "ask_delivery", "previous_item", "change_info")
NOT_IN_LIST_AUTO = 0.9
NOT_IN_LIST_HINT = 0.85
CALL_KINDS = ("shadow", "accepted", "corrected", "auto", "rejected", "error", "unused")  # = a request was made


# ---------- one request ----------

@dataclass
class Understood:
    result: AIResult | None  # None = no usable answer
    problems: list[str] = field(default_factory=list)  # checker / error kind
    error: str | None = None  # AIError kind
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    raw: dict | None = None

    @property
    def cost(self) -> float:
        return providers.cost_usd(self.input_tokens, self.cached_tokens, self.output_tokens)


def understand(provider, catalog: prompt.Catalog, ctx: prompt.Context, model: str, reasoning: str) -> Understood:
    """Ask once and check the answer. Never raises for provider problems."""
    try:
        reply = provider.understand(prompt.static_part(catalog), prompt.schema(catalog), prompt.dynamic_part(ctx),
                                    model, reasoning)
    except AIError as exc:
        return Understood(None, [exc.kind], exc.kind)
    except Exception as exc:  # an SDK surprise must not stop the worker
        log.warning("AI provider failed: %s", type(exc).__name__)
        return Understood(None, ["other"], "other")
    out = Understood(None, [], None, reply.input_tokens, reply.cached_tokens, reply.output_tokens, reply.latency_ms,
                     reply.data)
    result, problems = checker.parse(reply.data)
    if result is not None:
        problems = checker.check(result, catalog, ctx.message)
    if problems:
        out.problems = problems
        return out
    if result.intent != "question" and result.draft_answer:
        result = AIResult(result.intent, result.items, result.learn, result.confidence, result.reason, None)
    out.result = result
    return out


# ---------- when ----------

def _items(session: Session, result: ParseResult) -> list[ParseItem]:
    return list(session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                                .order_by(ParseItem.position)))


def rules_unsure(session: Session, message: Message, result: ParseResult) -> str | None:
    """Why the rules are not certain about this message (None = certain, no AI needed).
    Messages an approved learned pattern handles are certain (match "learned"); pending ones are
    one-tap 📘 suggestions already, so no AI either."""
    from app.orders import previous, unknown  # late imports: orders -> parser
    from app.replies import faq

    if message.direction != "in" or message.kind != "text" or not (message.raw_text or "").strip():
        return None
    if result.method != "rules":
        return None
    if faq.for_message(session, message, result) is not None:
        return None  # an FAQ answers it
    items = _items(session, result)
    if result.intent in ("other", "unknown"):
        return f"intent {result.intent}"
    if result.intent == "previous_item" and not items and not previous.candidates(session, message):
        return "previous item not in history"
    if result.intent in PRODUCT_INTENTS and not items:
        return "no product"
    answered = unknown.not_stocked_texts(session, message.id)
    for item in items:
        if item.unknown_text and normalize(item.unknown_text) not in answered:
            return "unknown product"
        if item.match in UNSURE_MATCHES or item.from_context:
            return f"match {item.match}"
    return None


def _day_start(now: datetime) -> datetime:
    tz = ZoneInfo(get_settings().timezone)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def calls_today(session: Session, now: datetime) -> int:
    return session.scalar(select(func.count()).select_from(AICall).where(
        AICall.created_at >= _day_start(now), AICall.decision.in_(CALL_KINDS))) or 0


def cost_this_month(session: Session, now: datetime) -> float:
    start = _day_start(now).replace(day=1)
    return float(session.scalar(select(func.coalesce(func.sum(AICall.cost_usd), 0)).where(
        AICall.created_at >= start)) or 0)


_not_needed: dict[int, int] = {}  # message id -> parse result id the rules were sure about (this process)


def candidates(session: Session, now: datetime, limit: int = 20) -> list[int]:
    """Fresh, parsed, unhandled customer text messages the rules are unsure about and that have no
    ai_calls row yet (oldest first). A message found "no AI needed" is remembered with its parse
    result, so the worker (polling every second) checks it again only when it is re-parsed."""
    from app.learning import cards  # late import

    asked = exists().where(AICall.message_id == Message.id)
    rows = session.execute(
        select(Message.id, ParseResult.id).join(ParseResult, (ParseResult.message_id == Message.id)
                                                & ParseResult.is_current)
        .join(Customer, Customer.id == Message.customer_id)
        .where(Message.direction == "in", Message.kind == "text", Message.received_at >= now - WINDOW,
               ParseResult.method == "rules", Customer.ignored.is_(False), ~asked)
        .order_by(Message.received_at, Message.id)).all()
    live = {mid for mid, _ in rows}
    for mid in [m for m in _not_needed if m not in live]:
        del _not_needed[mid]  # too old / asked / re-parsed by a person: forget
    found = []
    for message_id, result_id in rows:
        if _not_needed.get(message_id) == result_id:
            continue
        message, result = session.get(Message, message_id), session.get(ParseResult, result_id)
        if cards.handled(session, message) or not rules_unsure(session, message, result):
            _not_needed[message_id] = result_id
            continue
        found.append(message_id)
        if len(found) >= limit:
            break
    return found


def waiting_for_ai(session: Session, message: Message, result: ParseResult) -> bool:
    """AUTO mode: the auto engine waits for the AI's answer on this message (see auto.decide, which
    calls this only in AUTO mode)."""
    if result.method != "rules" or providers.get() is None:
        return False
    if session.scalar(select(exists().where(AICall.message_id == message.id))):
        return False
    if datetime.now(UTC) - message.received_at > WINDOW:
        return False
    from app.learning import cards  # late import

    if cards.handled(session, message):
        return False
    return rules_unsure(session, message, result) is not None


# ---------- the worker step ----------

def _record(session: Session, message_id: int, model: str, mode: str, decision: str, got: Understood | None,
            error: str | None = None) -> AICall:
    call = AICall(message_id=message_id, model=model, mode=mode, decision=decision, ok=bool(got and got.result),
                  error=(error or (", ".join(got.problems) if got and got.problems else None) or None),
                  result_json=got.result.to_json() if got and got.result else None)
    if got is not None:
        call.input_tokens, call.cached_tokens, call.output_tokens = got.input_tokens, got.cached_tokens, \
            got.output_tokens
        call.cost_usd, call.latency_ms = got.cost, got.latency_ms
    if call.error:
        call.error = call.error[:255]
    session.add(call)
    session.flush()
    return call


def process(message_id: int, now: datetime | None = None) -> str:
    """Ask the AI about one message (own transactions; the network call holds no DB locks)."""
    now = now or datetime.now(UTC)
    with SessionLocal() as session:
        cfg = ai_settings.load(session)
        provider = providers.get()
        message = session.get(Message, message_id)
        if cfg["mode"] == "off" or provider is None or message is None:
            return "off"
        result = session.scalar(select(ParseResult).where(ParseResult.message_id == message_id,
                                                          ParseResult.is_current))
        if result is None or session.scalar(select(exists().where(AICall.message_id == message_id))):
            return "done already"
        limit = None
        if calls_today(session, now) >= cfg["daily_cap"]:
            limit = "cap"
        elif cost_this_month(session, now) >= cfg["monthly_budget_usd"]:
            limit = "budget"
        if limit is None:
            catalog = prompt.load_catalog(session)
            ctx = prompt.build_context(session, message)
            rules_result_id = result.id
    if limit is not None:
        with SessionLocal.begin() as session:
            _record(session, message_id, cfg["model"], cfg["mode"], limit, None, f"{limit} reached")
        log.info("AI message=%s not called: %s reached", message_id, limit)
        return limit
    got = understand(provider, catalog, ctx, cfg["model"], cfg["reasoning"])
    with SessionLocal.begin() as session:
        if session.scalar(select(exists().where(AICall.message_id == message_id))):
            return "done already"
        if got.result is None:
            decision = "rejected" if got.error in (None, "bad_output") else "error"  # invalid JSON = checker
            _record(session, message_id, cfg["model"], cfg["mode"], decision, got)
            log.info("AI message=%s %s: %s", message_id, decision, ", ".join(got.problems)[:200])
            return decision
        call = _record(session, message_id, cfg["model"], cfg["mode"], "shadow", got)
        current = session.scalar(select(ParseResult).where(ParseResult.message_id == message_id,
                                                           ParseResult.is_current))
        if cfg["mode"] == "auto" and current is not None and current.id == rules_result_id:
            why_not = auto_apply(session, session.get(Message, message_id), current, got.result, call, catalog, cfg)
            if why_not is None:
                log.info("AI message=%s auto (%.2f)", message_id, got.result.confidence)
                return "auto"
            log.info("AI message=%s shadow: %s", message_id, why_not)
        else:
            log.info("AI message=%s shadow", message_id)
        return "shadow"


def run_once(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    with SessionLocal() as session:
        if ai_settings.mode(session) == "off" or providers.get() is None:
            return {}
        ids = candidates(session, now)
    stats: dict[str, int] = {}
    for message_id in ids:
        try:
            outcome = process(message_id, now)
        except Exception:
            log.exception("AI step failed for message=%s", message_id)
            try:
                with SessionLocal.begin() as session:
                    if not session.scalar(select(exists().where(AICall.message_id == message_id))):
                        _record(session, message_id, "?", "?", "error", None, "internal error")
            except Exception:
                log.exception("could not record the AI failure for message=%s", message_id)
            outcome = "error"
        stats[outcome] = stats.get(outcome, 0) + 1
    if ids:
        from app.ai import graduation  # late import: graduation imports this module

        try:
            with SessionLocal.begin() as session:
                if reason := graduation.check_brake(session, now):
                    stats["brake"] = 1
                    log.warning("AI safety brake: %s", reason)
        except Exception:
            log.exception("AI brake check failed")
    return stats


# ---------- AUTO ----------

def auto_apply(session: Session, message: Message, rules: ParseResult, ai: AIResult, call: AICall,
               catalog: prompt.Catalog, cfg: dict) -> str | None:
    """Use the AI's answer as the parse result (method="ai") when it is certain enough.
    Returns None when applied, else why not (the result then stays a SHADOW hint)."""
    from app.models import Order  # late imports: orders -> parser
    from app.models.orders import OPEN_STATUSES
    from app.orders import previous

    if ai.confidence < cfg["threshold"]:
        return f"confidence {ai.confidence:.2f} below {cfg['threshold']}"
    if ai.intent not in AUTO_INTENTS:
        return f"intent {ai.intent} is never automatic"
    intent = ai.intent
    if intent == "cancel_order" and not session.scalar(select(exists().where(
            Order.customer_id == message.customer_id, Order.status.in_(OPEN_STATUSES)))):
        return "cancel without an open cart"
    if intent in PRODUCT_INTENTS + ("previous_item",) and not ai.items:
        return "no items"
    for item in ai.items:
        if item.product_id is None and not (item.not_in_list and ai.confidence >= NOT_IN_LIST_AUTO):
            return "an item without a product"
        if item.product_id is not None and intent in ("buy", "previous_item") and item.size is None:
            return "a buy without a size"
    if intent == "previous_item":
        history = {c.key for c in previous.candidates(session, message)}
        if not all((i.product_id, i.size_ml, i.is_full) in history for i in ai.items):
            return "previous item not in the history"
        intent = "buy"
    if intent not in PRODUCT_INTENTS:
        items = ()
    else:
        items = ai.items

    session.execute(update(ParseResult).where(ParseResult.id == rules.id).values(is_current=False))
    session.flush()
    first = next((i for i in items if i.product_id), None)
    result = ParseResult(message_id=message.id, intent=intent, product_id=first.product_id if first else None,
                         size_ml=first.size_ml if first else None, quantity=first.qty if first else 1,
                         confidence=round(ai.confidence, 2), method="ai", parser_version=f"ai:{call.model}"[:32],
                         is_current=True, phone=rules.phone, learned_ids=[])
    session.add(result)
    session.flush()
    for position, item in enumerate(items):
        session.add(ParseItem(parse_result_id=result.id, position=position, product_id=item.product_id,
                              size_ml=item.size_ml, is_full_bottle=item.is_full, quantity=item.qty,
                              unknown_text=item.not_in_list[:255] if item.not_in_list else None, from_context=False,
                              match="ai", name_text=None))
        if item.not_in_list:  # "we don't have it", counted in Wanted (resolved by the AI, no user)
            norm = normalize(item.not_in_list)[:255]
            if norm and not session.scalar(select(UnknownRequest.id).where(
                    UnknownRequest.message_id == message.id, UnknownRequest.normalized_text == norm)):
                session.add(UnknownRequest(message_id=message.id, customer_id=message.customer_id,
                                           text=item.not_in_list[:255], normalized_text=norm, size_ml=item.size_ml,
                                           is_full_bottle=item.is_full, resolution="not_stocked", resolved_by=None))
    taught = learn(session, ai, None, message.id)
    call.decision, call.decided_at = "auto", datetime.now(UTC)
    session.add(AuditLog(user_id=None, action="ai.auto", details={
        "message_id": message.id, "ai_call_id": call.id, "parse_result_id": result.id, "intent": intent,
        "confidence": ai.confidence, "patterns": taught}))
    session.flush()
    return None


def learn(session: Session, ai: AIResult, user, message_id: int) -> list[int]:
    """The AI's learn entries become PENDING learned patterns (via_ai). Returns their ids."""
    from app.learning import patterns

    ids = []
    for entry in ai.learn:
        taught = patterns.teach(session, entry.kind, entry.text, user, product_id=entry.product_id,
                                intent=entry.intent if entry.kind == "intent_phrase" else None,
                                message_id=message_id, via_ai=True)
        if taught.status == "saved":
            ids.append(taught.pattern.id)
    return ids
