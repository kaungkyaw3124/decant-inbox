"""Builds the customer states and sends the messages of the docs/SPEC-v4.10-interruptions.md J1
matrix (state x message). Used by tests/test_v410_interruptions.py."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import Customer, Message, Order, PaymentCheck
from app.orders import auto, cart, payments
from app.parser.worker import run_batch
from tests.test_cart import deliver
from tests.test_messaging import add, scalar

STATES = ("browsing", "cart", "need_phone", "need_address", "waiting_new_info", "waiting_payment", "photo_received",
          "paid", "packed", "sent_out", "delivered")
MESSAGES = {
    "buy_known": "sauvage edp 5ml ယူမယ်",
    "buy_unknown": "tobacco vanille 10ml ယူမယ်",
    "remove": "stw intensely ကို မယူတော့ဘူး",
    "cancel_order": "မယူတော့ဘူး",
    "ask_price": "sauvage edp 5ml ဘယ်လောက်လဲ",
    "ask_stock": "sauvage edp 5ml ရှိလား",
    "faq": "authentic လား",
    "question": "ဒီအနံ့က ဘယ်လိုမျိုးလဲ",
    "greeting": "hi",
    "address": "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅",
    "phone": "09444555666",
    "change_info": "လိပ်စာ ပြောင်းချင်ပါတယ်",
    "paid_no_photo": "ငွေလွှဲပြီးပါပြီ",
    "photo": None,
    "previous_item": "ဟိုနေ့ကဟာ ထပ်ယူမယ်",
    "ask_delivery": "ဘယ်တော့ ရောက်မလဲ",
}
CUSTOMER = "91"
OLD_ADDRESS = "No. 5, Sanchaung"
OLD_PHONE = "09111222333"


def _now() -> datetime:
    return datetime.now(UTC)


def make_state(db, state: str) -> None:
    """Customer 91 in `state`. We messaged them 30 min ago (so no leading greeting); the order holds
    Stronger With You Intensely 5ml + Sauvage Eau de Parfum 10ml (18,000 + 38,000)."""
    now = _now()
    returning = state in ("cart", "waiting_new_info")
    with SessionLocal.begin() as s:
        customer = Customer(channel="telegram", external_user_id=CUSTOMER, display_name="Matrix",
                            auto_resumed_at=now - timedelta(minutes=1),  # "our last message" is no hand reply
                            address=OLD_ADDRESS if state not in ("need_phone", "need_address") else None,
                            phone=OLD_PHONE if state not in ("need_phone", "need_address") else None)
        s.add(customer)
        s.flush()
        if customer.phone:
            cart.set_customer_phones(s, customer, [(OLD_PHONE, None)])
        s.add(Message(channel="telegram", external_chat_id=CUSTOMER, external_message_id="m-old", customer_id=customer.id,
                      raw_text="old", received_at=now - timedelta(days=3), direction="in"))
        s.add(Message(channel="telegram", external_chat_id=CUSTOMER, external_message_id="m-out",
                      customer_id=customer.id, raw_text="(our last message)", received_at=now - timedelta(minutes=30),
                      direction="out"))
        if state == "browsing":
            return
        order = cart.open_cart(s, customer.id, create=True)
        stw = s.execute(text("SELECT id FROM products WHERE name = 'Stronger With You Intensely'")).scalar()
        sauvage = s.execute(text("SELECT id FROM products WHERE name = 'Sauvage Eau de Parfum'")).scalar()
        cart.add_items(s, order, [cart.WantedItem(stw, 5, False, 1, None), cart.WantedItem(sauvage, 10, False, 1, None)],
                       None)
        order.list_sent_at = now - timedelta(minutes=30)
        if state in ("cart", "need_phone"):
            return  # returning: "…ကိုပဲ ပို့ပေးရမလား။" · new: "ဖုန်းနံပါတ် ပို့ပေးပါ"
        if state == "need_address":
            cart.confirm(s, order)
            cart.add_phones(s, order, customer, [OLD_PHONE], None)
            return
        if state == "waiting_new_info":
            order.change_wanted, order.change_asked_at = "address", now - timedelta(minutes=20)
            return
        cart.confirm(s, order)
        order.phones, order.address = [OLD_PHONE], OLD_ADDRESS
        order.status, order.payment_info_sent_at = "waiting_payment", now - timedelta(minutes=30)
        cart.touch(s, order)
        if state == "waiting_payment":
            return
        photo = Message(channel="telegram", external_chat_id=CUSTOMER, external_message_id="m-shot",
                        customer_id=customer.id, raw_text="", received_at=now - timedelta(minutes=20), kind="photo")
        s.add(photo)
        s.flush()
        s.add(PaymentCheck(order_id=order.id, message_id=photo.id, decision="pending" if state == "photo_received"
                           else "approved"))
        order.status = "photo_received"
        if state == "photo_received":
            return
        order.order_no = s.execute(text("SELECT nextval('order_no_seq')")).scalar()
        order.status, order.paid_at = "paid", now - timedelta(minutes=15)
        if state in ("packed", "sent_out", "delivered"):
            order.status, order.packed_at = "packed", now - timedelta(minutes=10)
        if state in ("sent_out", "delivered"):
            order.status, order.sent_out_at = "sent_out", now - timedelta(minutes=5)
        if state == "delivered":
            order.status, order.delivered_at = "delivered", now - timedelta(minutes=2)


@dataclass
class Result:
    replies: list[str]
    open_status: str | None  # the open order's status after (None = no open order)
    open_items: int
    open_total: int
    open_address: str | None
    open_phones: list[str]
    paid_status: str | None  # the order with an Order ID (if any)
    paid_address: str | None
    paid_items: int
    requests: int  # Needs you: change requests a person must handle (4.10)
    card: bool  # Needs you: teaching card / unknown item
    unanswered: bool  # Needs you: unanswered (2 min)
    payment_check: bool  # a pending payment check
    parse_intent: str | None


def send(db, intent: str) -> Result:
    body = MESSAGES[intent]
    now = _now()
    if body is None:
        add(9100, "", customer=CUSTOMER, kind="photo", when=now)
        with SessionLocal.begin() as s:
            payments.scan(s)
    else:
        add(9100, body, customer=CUSTOMER, when=now)
    run_batch()
    auto.run_once(now + timedelta(seconds=5))
    replies = deliver(db)
    return snapshot(db, replies, now)


def snapshot(db, replies: list[str], now: datetime) -> Result:
    from app.web import auto as auto_page

    with SessionLocal() as s:
        cid = s.execute(text("SELECT id FROM customers WHERE external_user_id = :e"), {"e": CUSTOMER}).scalar()
        open_order = cart.open_cart(s, cid)
        paid = s.execute(text("SELECT id FROM orders WHERE customer_id = :c AND order_no IS NOT NULL"),
                         {"c": cid}).scalar()
        paid = s.get(Order, paid) if paid else None
        view = cart.view(s, open_order) if open_order else None
        needs = auto_page.needs_you(s, now + timedelta(minutes=3))
        mid = s.execute(text("SELECT id FROM messages WHERE external_message_id = '9100'")).scalar()
        unanswered = any(mid in r.message_ids for r in needs["unanswered"])
        card = any(m.id == mid for m, *_ in needs["teach"]) or any(m.id == mid for m, *_ in needs["unknown"]) or any(
            r.card and r.card[0].id == mid for r in needs["unanswered"])
        check = s.execute(text("SELECT count(*) FROM payment_checks WHERE decision = 'pending'")).scalar()
        return Result(
            replies, open_order.status if open_order else None, len(view.lines) if view else 0,
            view.total if view else 0, open_order.address if open_order else None,
            list(open_order.phones or []) if open_order else [], paid.status if paid else None,
            paid.address if paid else None, len(cart.view(s, paid).lines) if paid else 0, len(needs["requests"]),
            card, unanswered, bool(check),
            scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid))
