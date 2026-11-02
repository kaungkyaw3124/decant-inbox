"""docs/SPEC-v5.2-customer-care.md: customer profiles, the reorder list (admin click only), feedback after delivery.

Telegram hard rules unchanged: a reorder message goes only when an admin taps Send (one tap = one message, through
the outbox and its rate limits); feedback is one question per delivered order and only when the owner switched it
on. Never to ignored / never-auto-reply / opted-out customers; "stop" / "မပို့နဲ့" from a customer opts them out.
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AppSetting, AuditLog, CareOptOut, Customer, CustomerNote, CustomerTag, Feedback, Message, Order, OrderItem, Outbox,
    Product, ReorderSent, User,
)
from app.models.orders import PAID_STATUSES

SETTING = "care"
DEFAULTS = {"reorder_min_days": 25, "reorder_max_days": 45, "feedback_on": False, "feedback_after_days": 2}
REORDER_EVERY = timedelta(days=30)
FEEDBACK_ANSWER_WINDOW = timedelta(days=7)
VIP_ORDERS, VIP_SPENT = 5, 200_000
TAG_COLOURS = {"VIP": "vip", "wholesale": "wholesale", "problem": "problem"}  # others: grey
GOOD_RE = re.compile(r"👍|❤|😍|🥰|ကောင်း|အဆင်ပြေ|ကြိုက်|(?<![a-z])(?:good|great|nice|ok|okay|love|thanks?|thank you)(?![a-z])",
                     re.IGNORECASE)
BAD_RE = re.compile(r"👎|😡|😞|မကောင်း|အဆင်မပြေ|မကြိုက်|(?<![a-z])(?:bad|not good|not ok)(?![a-z])", re.IGNORECASE)


def settings(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    return {**DEFAULTS, **(row.value if row else {})}


def save_settings(session: Session, values: dict, user: User | None) -> None:
    stmt = insert(AppSetting).values(key=SETTING, value={**settings(session), **values},
                                     updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


# ---------- P1 profile ----------

@dataclass
class Profile:
    orders: int
    spent: int
    first: datetime | None
    last: datetime | None
    average: int
    top: list[tuple[str, int]]  # (perfume, times)
    usual_size: int | None
    city: str
    tags: list[str]
    notes: list[tuple[CustomerNote, str | None]]
    vip_suggested: bool
    opted_out: bool


def _paid(customer_ids=None):
    query = select(Order).where(Order.status.in_(PAID_STATUSES), Order.is_test.is_(False), Order.order_no.is_not(None))
    return query if customer_ids is None else query.where(Order.customer_id.in_(customer_ids))


def profile(session: Session, customer: Customer) -> Profile:
    """Paid orders only (test and cancelled orders excluded)."""
    orders = session.scalars(_paid([customer.id]).order_by(Order.paid_at)).all()
    items = session.execute(select(OrderItem, Product).join(Product, Product.id == OrderItem.product_id).where(
        OrderItem.order_id.in_([o.id for o in orders]), OrderItem.removed_at.is_(None))).all()
    perfumes = Counter()
    sizes = Counter()
    for i, p in items:
        perfumes[p.name] += i.quantity
        if i.size_ml and not i.is_full_bottle:
            sizes[i.size_ml] += i.quantity
    spent = sum(o.total_mmk or 0 for o in orders)
    tags = list(session.scalars(select(CustomerTag.tag).where(CustomerTag.customer_id == customer.id)
                                .order_by(CustomerTag.created_at)))
    notes = session.execute(select(CustomerNote, User.username).outerjoin(User, User.id == CustomerNote.user_id)
                            .where(CustomerNote.customer_id == customer.id).order_by(CustomerNote.id.desc())).all()
    return Profile(len(orders), spent, orders[0].paid_at if orders else None, orders[-1].paid_at if orders else None,
                   spent // len(orders) if orders else 0, perfumes.most_common(3),
                   sizes.most_common(1)[0][0] if sizes else None,
                   ((customer.address_parts or {}).get("city") or "").split(",")[0], tags, [tuple(n) for n in notes],
                   "VIP" not in tags and (len(orders) >= VIP_ORDERS or spent >= VIP_SPENT),
                   opted_out(session, customer.id))


def add_note(session: Session, customer_id: int, text: str, user: User) -> None:
    if text.strip():
        session.add(CustomerNote(customer_id=customer_id, text=text.strip()[:500], user_id=user.id))


def set_tag(session: Session, customer_id: int, tag: str, on: bool, user: User) -> None:
    tag = re.sub(r"\s+", " ", tag).strip()[:24]
    if not tag:
        return
    if on:
        session.execute(insert(CustomerTag).values(customer_id=customer_id, tag=tag, user_id=user.id)
                        .on_conflict_do_nothing())
    else:
        session.execute(CustomerTag.__table__.delete().where(CustomerTag.customer_id == customer_id,
                                                             CustomerTag.tag == tag))


def customer_rows(session: Session, q: str = "", tag: str = "", city: str = "", sort: str = "spent") -> list[dict]:
    """The Customers page: everyone who ever paid (and anyone matching the search)."""
    paid = _paid().subquery()
    totals = select(paid.c.customer_id, func.count().label("orders"), func.sum(paid.c.total_mmk).label("spent"),
                    func.max(paid.c.paid_at).label("last")).group_by(paid.c.customer_id).subquery()
    query = select(Customer, totals.c.orders, totals.c.spent, totals.c.last).join(totals, totals.c.customer_id == Customer.id)
    if q.strip():
        query = query.where(Customer.display_name.icontains(q.strip(), autoescape=True)
                            | Customer.username.icontains(q.strip(), autoescape=True))
    if tag:
        query = query.where(exists().where(CustomerTag.customer_id == Customer.id, CustomerTag.tag == tag))
    if city:
        query = query.where(Customer.address_parts["city"].astext.icontains(city, autoescape=True))
    query = query.order_by(totals.c.last.desc() if sort == "last" else totals.c.spent.desc(), Customer.id)
    tags: dict[int, list[str]] = {}
    for cid, t in session.execute(select(CustomerTag.customer_id, CustomerTag.tag)):
        tags.setdefault(cid, []).append(t)
    return [{"c": c, "orders": n, "spent": int(s or 0), "last": last, "tags": tags.get(c.id, []),
             "city": ((c.address_parts or {}).get("city") or "").split(",")[0]}
            for c, n, s, last in session.execute(query.limit(500))]


# ---------- opt-out ----------

def opted_out(session: Session, customer_id: int) -> bool:
    if session.get(CareOptOut, customer_id) is not None:
        return True
    return bool(session.scalar(select(exists().where(
        Message.customer_id == customer_id, Message.direction == "in",
        Message.raw_text.op("~*")(r"(^|[^a-z])(stop|unsubscribe)([^a-z]|$)|မပို့နဲ့|မပို့ပါနဲ့|မလိုချင်တော့ဘူး")))))


def set_opt_out(session: Session, customer_id: int, on: bool) -> None:
    if on:
        session.execute(insert(CareOptOut).values(customer_id=customer_id, source="admin").on_conflict_do_nothing())
    else:
        session.execute(CareOptOut.__table__.delete().where(CareOptOut.customer_id == customer_id))


def _reachable(session: Session, customer: Customer) -> bool:
    return not (customer.ignored or customer.auto_reply_off or opted_out(session, customer.id))


# ---------- P2 reorder list ----------

def reorder_list(session: Session, now: datetime | None = None) -> list[dict]:
    """Customers whose last decant was 25-45 days ago, not messaged for a reorder in 30 days, reachable."""
    now = now or datetime.now(UTC)
    cfg = settings(session)
    texts = None
    found = []
    # a test account's test orders count here, so the owner can try the list (totals still exclude them)
    counted = Order.is_test.is_(False) | select(Customer.is_tester).where(Customer.id == Order.customer_id).scalar_subquery()
    last_paid = select(Order.customer_id, func.max(Order.paid_at).label("last")).where(
        Order.status.in_(PAID_STATUSES), counted, Order.order_no.is_not(None)).group_by(Order.customer_id).subquery()
    rows = session.execute(select(Customer, last_paid.c.last).join(last_paid, last_paid.c.customer_id == Customer.id)
                           .where(last_paid.c.last <= now - timedelta(days=cfg["reorder_min_days"]),
                                  last_paid.c.last >= now - timedelta(days=cfg["reorder_max_days"]))
                           .order_by(last_paid.c.last)).all()
    for customer, last in rows:
        if not _reachable(session, customer) or session.scalar(select(exists().where(
                ReorderSent.customer_id == customer.id, ReorderSent.created_at >= now - REORDER_EVERY))):
            continue
        order = session.scalar(select(Order).where(
            Order.customer_id == customer.id, Order.status.in_(PAID_STATUSES), Order.order_no.is_not(None),
            Order.is_test.is_(False) | customer.is_tester).order_by(Order.paid_at.desc()).limit(1))
        item = session.execute(select(OrderItem, Product).join(Product, Product.id == OrderItem.product_id).where(
            OrderItem.order_id == order.id, OrderItem.removed_at.is_(None), OrderItem.is_full_bottle.is_(False))
            .order_by(OrderItem.id).limit(1)).first()
        if item is None:
            continue  # full bottles only: not a decant to run out of
        from app.replies import templates as replies

        texts = texts or replies.load(session)
        i, p = item
        found.append({"c": customer, "last": last, "days": (now - last).days, "product": f"{p.name} {i.size_ml}ml",
                      "text": replies.render(texts["reorder_suggest"], product=f"{p.name} {i.size_ml}ml")})
    return found


class CareError(Exception):
    pass


def send_reorder(session: Session, customer: Customer, text: str, user: User, now: datetime | None = None) -> Outbox:
    """One admin tap = one message (the outbox and its rate limits send it)."""
    from app.models.outbox import MAX_TEXT

    now = now or datetime.now(UTC)
    text = text.replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_TEXT:
        raise CareError("Write the message (1-4000 characters).")
    if not _reachable(session, customer):
        raise CareError("This customer opted out / is ignored / has auto replies off: not sent.")
    if session.scalar(select(exists().where(ReorderSent.customer_id == customer.id,
                                            ReorderSent.created_at >= now - REORDER_EVERY))):
        raise CareError("Already sent a reorder message in the last 30 days.")
    if not session.scalar(select(exists().where(Message.customer_id == customer.id, Message.direction == "in"))):
        raise CareError("This customer has never messaged us; we never message first.")
    box = Outbox(customer_id=customer.id, text=text, reply_kind="custom", status="queued",
                 idempotency_key=f"reorder-{customer.id}-{now.timestamp()}", created_by=user.id, send_after=now)
    session.add(box)
    session.flush()
    session.add(ReorderSent(customer_id=customer.id, outbox_id=box.id, user_id=user.id))
    session.add(AuditLog(user_id=user.id, action="care.reorder", details={"customer_id": customer.id,
                                                                           "outbox_id": box.id}))
    return box


# ---------- P3 feedback after delivery ----------

def ask_feedback(session: Session, now: datetime | None = None, force_order: int | None = None) -> int:
    """Delivered >= 2 days ago (or force_order: the owner's "send now" test), once per order. Returns how many."""
    now = now or datetime.now(UTC)
    cfg = settings(session)
    if not cfg["feedback_on"] and force_order is None:
        return 0
    asked = exists().where(Feedback.order_id == Order.id)
    query = select(Order).where(Order.status == "delivered", ~asked)
    if force_order is not None:
        query = query.where(Order.id == force_order)
    else:  # recent deliveries only: switching it on does not ask about old orders
        query = query.where(Order.delivered_at <= now - timedelta(days=cfg["feedback_after_days"]),
                            Order.delivered_at >= now - timedelta(days=cfg["feedback_after_days"] + 5))
    from app.orders import testpay
    from app.replies import templates as replies

    texts, n = replies.load(session), 0
    for order in session.scalars(query.with_for_update(skip_locked=True)):
        customer = session.get(Customer, order.customer_id)
        box = None
        if _reachable(session, customer):
            box = Outbox(customer_id=customer.id, reply_kind="custom", status="queued", created_by=None,
                         text=replies.render(texts["feedback_ask"], order_no=testpay.order_label(order)),
                         idempotency_key=f"feedback-{order.id}", send_after=now)
            session.add(box)
            session.flush()
            n += 1
        session.add(Feedback(order_id=order.id, customer_id=customer.id, outbox_id=box.id if box else None,
                             answer=None if box else "skipped"))
    return n


def open_feedback(session: Session, message: Message) -> Feedback | None:
    """The customer's unanswered feedback question this message may answer (asked before it, within 7 days)."""
    return session.scalar(select(Feedback).where(
        Feedback.customer_id == message.customer_id, Feedback.answer.is_(None), Feedback.outbox_id.is_not(None),
        Feedback.asked_at <= message.received_at, Feedback.asked_at >= message.received_at - FEEDBACK_ANSWER_WINDOW)
        .order_by(Feedback.asked_at.desc()).limit(1))


def classify(text: str | None) -> str:
    from app.orders import holding

    text = text or ""
    if BAD_RE.search(text) or holding.is_complaint(text):
        return "bad"
    return "good" if GOOD_RE.search(text) else "other"
