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
- the customer has been quiet for 15 s (several quick messages: handled one by one, each
  seeing the latest state; the "reply still queued" rule stops double replies);
- a random 8-20 s delay in the outbox (human-like, Cancel in the chat);
- at most 300 auto replies a day, then one-tap again;
- at most one auto decision per incoming message (auto_runs).
Never automatic: photos, intents other/unknown, unknown items (those go to "Needs you").
"""
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import AppSetting, AutoRun, Customer, Message, Outbox, ParseItem, ParseResult, QuickAction, User
from app.orders import actions
from app.replies import templates as replies

log = logging.getLogger("auto")
SETTING = "auto_reply"
AUTO_INTENTS = ("ask_price", "ask_stock", "buy", "remove", "done", "confirm", "address")
CERTAIN_MATCHES = ("exact", "inherited", "human")
DELAY_SECONDS = (8, 20)
QUIET_SECONDS = 15
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


def decide(session: Session, message: Message, now: datetime) -> str | None:
    """Handle one message. Returns what happened, or None = not yet (try again later)."""
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
    if result.intent not in AUTO_INTENTS:
        return _skip(session, message.id, f"intent {result.intent}")
    if answered_by_human(session, message):
        return _skip(session, message.id, "already answered")
    if paused_until(session, customer, now):
        return _skip(session, message.id, "paused: owner is replying by hand")
    items = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)).all()
    open_unknown = actions.unknown.open_unknowns(session, message)
    if open_unknown:
        return None  # "Needs you": decided again once the admin resolved the items
    if any(i.product_id and (i.from_context or (i.match not in CERTAIN_MATCHES and result.method != "human"))
           for i in items):
        return _skip(session, message.id, "product not named exactly")
    latest_in = session.scalar(select(func.max(Message.received_at)).where(
        Message.customer_id == customer.id, Message.direction == "in"))
    if now - latest_in < timedelta(seconds=QUIET_SECONDS):
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
    delay = timedelta(seconds=random.randint(*DELAY_SECONDS))
    try:
        action = actions.perform(session, message, suggestion.fingerprint, None, texts, delay=delay)
    except actions.Refused as exc:
        return _skip(session, message.id, str(exc)[:120])
    session.add(AutoRun(message_id=message.id, status="replied", quick_action_id=action.id))
    return f"{suggestion.kind}"


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
    with SessionLocal() as session:
        ids = candidates(session, now)
    stats: dict[str, int] = {}
    for message_id in ids:
        try:
            with SessionLocal.begin() as session:
                if not enabled(session):
                    break  # switched off meanwhile
                outcome = decide(session, session.get(Message, message_id), now)
        except Exception:
            log.exception("auto decision failed for message=%s", message_id)
            continue
        if outcome:
            key = "replied" if not outcome.startswith("skipped") else "skipped"
            stats[key] = stats.get(key, 0) + 1
            log.info("auto message=%s %s", message_id, outcome)
    return stats
