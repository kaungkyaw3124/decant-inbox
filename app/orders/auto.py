"""Auto mode (docs/SPEC-orders.md Step 4c): when the system is certain, it does the
one-tap action by itself. Same code as the button (actions.suggest + actions.perform),
only without the tap; actor "auto" in audit_log, undoable until sent.

Runs in the parser worker (database only). Extra rules on top of the one-tap ones:
- global switch (app_settings "auto_reply"), default OFF; only messages that arrived
  after it was switched on;
- customer not ignored, not "never auto-reply", not paused (the owner replied by hand in
  the last 2 h, unless the admin pressed "Resume auto");
- every product named exactly (alias match), none guessed, fuzzy or unknown;
- nothing answered after the message already (by hand or otherwise);
- the customer has been quiet for a moment (Settings "Auto-reply speed", default 1 s; several
  quick messages are handled one by one, each seeing the latest state; the "reply still
  queued" rule stops double replies);
- a random delay in the outbox (default 2-3 s; Cancel in the chat);
- at most 300 auto replies a day, then one-tap again;
- at most one auto decision per incoming message (auto_runs).
Never automatic: photos, intents other/unknown (except an FAQ answer, Step 7), unknown items
(those go to "Needs you"), learned patterns not approved yet (docs/SPEC-v4.md 4.2: one-tap "📘").
AI (docs/SPEC-v4.6-ai.md): in AUTO AI mode an unsure message waits for the AI's answer; an AI
parse result (method "ai") is acted on only while the AI mode is AUTO.
"""
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import (
    AppSetting, AuditLog, AutoRun, Customer, Message, Outbox, ParseItem, ParseResult, QuickAction, User,
)
from app.learning import patterns
from app.orders import actions, cart
from app.replies import faq
from app.replies import templates as replies

log = logging.getLogger("auto")
SETTING = "auto_reply"
SPEED_SETTING = "auto_speed"
DEFAULT_SPEED = {"quiet_s": 1, "delay_min_s": 2, "delay_max_s": 3}  # ~3 s from message to reply
SPEED_LIMITS = {"quiet_s": (0, 30), "delay_min_s": (1, 60), "delay_max_s": (1, 60)}
AUTO_INTENTS = ("ask_price", "ask_stock", "buy", "remove", "done", "confirm", "address", "ask_delivery",
                "cancel_order", "greeting", "previous_item", "change_info", "payment_sent", "modify_cart")
# learned = an approved learned nickname (4.2); choice = picked by number from our list (4.3);
# ai = written by the AI in AUTO mode after our checker and the threshold (docs/SPEC-v4.6-ai.md S4)
CERTAIN_MATCHES = ("exact", "inherited", "human", "learned", "choice", "ai")
PAUSE_AFTER_HAND_REPLY = timedelta(hours=2)
LINK_GRACE = timedelta(seconds=30)  # a dashboard send is linked to its outbox row within ms
DAILY_CAP = 300
WINDOW = timedelta(hours=24)


# ---------- the switch ----------

def state(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    return row.value if row else {"enabled": False}


def enabled(session: Session) -> bool:
    return bool(state(session).get("enabled"))


def set_enabled(session: Session, on: bool, user: User | None) -> None:
    value = {"enabled": on, "since": datetime.now(UTC).isoformat()} if on else {"enabled": False}
    stmt = insert(AppSetting).values(key=SETTING, value=value, updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


def speed(session: Session) -> dict[str, int]:
    row = session.get(AppSetting, SPEED_SETTING)
    return {**DEFAULT_SPEED, **(row.value if row else {})}


def set_speed(session: Session, values: dict[str, int], user: User | None) -> None:
    """ValueError if outside the allowed ranges or min > max."""
    for key, (low, high) in SPEED_LIMITS.items():
        if not low <= values[key] <= high:
            raise ValueError(f"{key} must be {low}-{high} s")
    if values["delay_min_s"] > values["delay_max_s"]:
        raise ValueError("The shortest delay can't be longer than the longest")
    stmt = insert(AppSetting).values(key=SPEED_SETTING, value=values, updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


def since(session: Session) -> datetime | None:
    value = state(session)
    return datetime.fromisoformat(value["since"]) if value.get("enabled") and value.get("since") else None


# ---------- per customer ----------

def last_hand_reply(session: Session, customer_id: int, now: datetime) -> datetime | None:
    """Newest message we sent that did not come from the dashboard outbox (= the owner's phone)."""
    sent_by_outbox = exists().where(Outbox.sent_message_id == Message.id)
    return session.scalar(select(func.max(Message.received_at)).where(
        Message.customer_id == customer_id, Message.direction == "out", ~sent_by_outbox,
        Message.received_at <= now - LINK_GRACE))


def paused_until(session: Session, customer: Customer, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    hand = last_hand_reply(session, customer.id, now)
    if hand is None or (customer.auto_resumed_at and customer.auto_resumed_at >= hand):
        return None
    until = hand + PAUSE_AFTER_HAND_REPLY
    return until if until > now else None


def answered_by_human(session: Session, message: Message) -> bool:
    """A person replied after this message: by hand on the phone, or from the dashboard
    (editor or one-tap). Auto mode's own replies don't count."""
    by_hand = select(exists().where(
        Message.customer_id == message.customer_id, Message.direction == "out",
        Message.received_at > message.received_at, ~exists().where(Outbox.sent_message_id == Message.id)))
    by_admin = select(exists().where(
        Outbox.customer_id == message.customer_id, Outbox.created_by.is_not(None),
        Outbox.status != "cancelled", Outbox.created_at > message.received_at))
    return bool(session.scalar(by_hand) or session.scalar(by_admin))


def sent_today(session: Session, now: datetime) -> int:
    return session.scalar(select(func.count()).select_from(QuickAction).where(
        QuickAction.auto, QuickAction.outbox_id.is_not(None), QuickAction.created_at >= now - WINDOW))


# ---------- deciding ----------

def _skip(session: Session, message_id: int, reason: str) -> str:
    session.execute(insert(AutoRun).values(message_id=message_id, status="skipped", reason=reason)
                    .on_conflict_do_nothing())
    return f"skipped: {reason}"


def decide(session: Session, message: Message, now: datetime, ai_mode: str | None = None) -> str | None:
    """Handle one message. Returns what happened, or None = not yet (try again later).
    ai_mode: the AI mode (off | shadow | auto), read once per pass by run_once()."""
    customer = session.get(Customer, message.customer_id)
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if result is None:
        return None  # not parsed yet
    if customer.ignored:
        return _skip(session, message.id, "ignored customer")
    if customer.auto_reply_off:
        return _skip(session, message.id, "auto-reply off for this customer")
    if message.kind != "text":
        return _skip(session, message.id, "photo / file")
    from app.ai import service as ai, settings as ai_settings  # late import: ai -> orders

    if ai_mode is None:
        ai_mode = ai_settings.mode(session)
    if ai_mode == "auto" and ai.waiting_for_ai(session, message, result):
        return None  # AUTO AI mode: the AI looks at it first (the worker asks right before this)
    if result.method == "ai" and ai_mode != "auto":
        return _skip(session, message.id, "AI result, AI mode is not auto")
    if result.intent not in AUTO_INTENTS and faq.for_message(session, message, result) is None:
        return _skip(session, message.id, f"intent {result.intent}")
    if answered_by_human(session, message):
        return _skip(session, message.id, "already answered")
    if paused_until(session, customer, now):
        return _skip(session, message.id, "paused: owner is replying by hand")
    items = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)).all()
    open_unknown = actions.unknown.open_unknowns(session, message)
    order = cart.open_cart(session, customer.id) if open_unknown else None
    if open_unknown and not (order is not None and order.status == "photo_received"):
        if order is not None and order.status == "waiting_payment":
            hold_reply(session, message, now)  # docs/SPEC-v4.10-interruptions.md: "we'll check" once
        return None  # "Needs you": decided again once the admin resolved the items
    if patterns.not_certain(session, actions.learned_used(session, message, result)):
        return _skip(session, message.id, "learned pattern waiting for approval")
    if any(i.product_id and (i.from_context or (i.match not in CERTAIN_MATCHES and result.method != "human"))
           for i in items):
        return _skip(session, message.id, "product not named exactly")
    pace = speed(session)
    latest_in = session.scalar(select(func.max(Message.received_at)).where(
        Message.customer_id == customer.id, Message.direction == "in"))
    if now - latest_in < timedelta(seconds=pace["quiet_s"]):
        return None  # more messages may be coming: wait for the customer to finish
    if session.scalar(select(exists().where(Outbox.customer_id == customer.id,
                                            Outbox.status.in_(("queued", "sending"))))):
        return None  # a reply is still going out: decide with the newest state afterwards
    texts = replies.load(session)
    suggestion = actions.suggest(session, message, result, texts, now)
    if suggestion is None:
        return _skip(session, message.id, "no certain reply")
    if suggestion.text and sent_today(session, now) >= DAILY_CAP:
        return _skip(session, message.id, f"daily limit of {DAILY_CAP} auto replies")
    delay = timedelta(seconds=random.uniform(pace["delay_min_s"], pace["delay_max_s"]))
    try:
        action = actions.perform(session, message, suggestion.fingerprint, None, texts, delay=delay, decided_at=now)
    except actions.Refused as exc:
        return _skip(session, message.id, str(exc)[:120])
    session.add(AutoRun(message_id=message.id, status="replied", quick_action_id=action.id))
    return f"{suggestion.kind}"


def hold_reply(session: Session, message: Message, now: datetime) -> None:
    """An unknown item while waiting for payment: "စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။" once, so the customer
    knows; the teaching card stays in Needs you (no quick action: the message is not "handled")."""
    if session.scalar(select(exists().where(Outbox.source_message_id == message.id, Outbox.reply_kind == "hold"))):
        return
    if sent_today(session, now) >= DAILY_CAP:
        return
    pace = speed(session)
    if now - message.received_at < timedelta(seconds=pace["quiet_s"]):
        return
    texts = replies.load(session)
    delay = timedelta(seconds=random.uniform(pace["delay_min_s"], pace["delay_max_s"]))
    session.add(Outbox(customer_id=message.customer_id, text=texts["hold_check"], reply_kind="hold", status="queued",
                       idempotency_key=f"hold-{message.id}", created_by=None, send_after=now + delay,
                       source_message_id=message.id))
    session.add(AuditLog(user_id=None, action="auto.hold", details={"actor": "auto", "message_id": message.id}))


def candidates(session: Session, now: datetime) -> list[int]:
    start = since(session)
    if start is None:
        return []
    decided = exists().where(AutoRun.message_id == Message.id)
    handled = exists().where(and_(QuickAction.message_id == Message.id, QuickAction.undone_at.is_(None)))
    return list(session.scalars(select(Message.id).where(
        Message.direction == "in", Message.received_at >= max(start, now - WINDOW), ~decided, ~handled)
        .order_by(Message.received_at, Message.id).limit(50)))


def run_once(now: datetime | None = None) -> dict[str, int]:
    """One pass over undecided messages (each in its own transaction). Returns counts."""
    now = now or datetime.now(UTC)
    from app.ai import settings as ai_settings  # late import: ai -> orders

    with SessionLocal() as session:
        ids = candidates(session, now)
        ai_mode = ai_settings.mode(session) if ids else None
    stats: dict[str, int] = {}
    for message_id in ids:
        try:
            with SessionLocal.begin() as session:
                if not enabled(session):
                    break  # switched off meanwhile
                outcome = decide(session, session.get(Message, message_id), now, ai_mode)
        except Exception:
            log.exception("auto decision failed for message=%s", message_id)
            continue
        if outcome:
            key = "replied" if not outcome.startswith("skipped") else "skipped"
            stats[key] = stats.get(key, 0) + 1
            log.info("auto message=%s %s", message_id, outcome)
    return stats
