"""docs/SPEC-v3.md Step 6 acceptance tests A1-A6: delivery statuses, "when will it arrive?",
payment reminder + auto-cancel, unanswered messages in Needs you, cancelling the whole
order, and the "wanted but not stocked" report. Customer messages in -> exact replies out
(fake Telegram client), DB state checked."""
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import Order
from app.orders import auto, delivery, followups
from app.parser.worker import run_batch
from app.web import auto as auto_pages
from tests.test_cart import deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_payments import downloaded, photo, waiting_for_payment
from tests.test_web import client, log_in  # noqa: F401  (fixture)

FOOTER = "ပို့ခကို ပစ္စည်းရောက်မှ ပေးချေပေးပါနော်။"


def auto_on(db):
    with SessionLocal.begin() as s:
        auto.set_enabled(s, True, None)
    with db.begin() as c:  # count messages of the last hour too
        c.execute(text("UPDATE app_settings SET value = jsonb_set(value, '{since}', to_jsonb(CAST(:s AS text))) "
                       "WHERE key = 'auto_reply'"), {"s": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})


def auto_off():
    with SessionLocal.begin() as s:
        auto.set_enabled(s, False, None)


def paid_order(client, token, db, tmp_path, monkeypatch, customer="91", n=1) -> int:
    """An approved payment: order #100x, status paid, confirmation delivered. Returns the order id."""
    waiting_for_payment(client, token, db, customer=customer)
    photo(n, customer=customer)
    check = scalar(db, "SELECT max(id) FROM payment_checks")
    client.get(f"/payments/{check}")
    downloaded(db, tmp_path, monkeypatch, check, content=f"shot-{n}".encode())
    client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": f"TX{n}", "amount": "18000",
                                                     "confirmed": "1"})
    assert len(deliver(db)) == 1  # the confirmation
    return scalar(db, "SELECT o.id FROM orders o JOIN customers c ON c.id = o.customer_id "
                      "WHERE c.external_user_id = :e AND o.status = 'paid'", e=customer)


def status(db, order_id: int) -> str:
    return scalar(db, "SELECT status FROM orders WHERE id = :o", o=order_id)


def tap(client, token, order_id: int, to: str, **deli) -> None:
    r = client.post(f"/orders/{order_id}/status", data={"csrf": token, "to": to, **deli}, follow_redirects=False)
    assert r.status_code == 303


def undo_last(client, token, order_id: int) -> None:
    page = client.get("/orders?tab=all").text
    event = re.search(rf'id="order-{order_id}".*?action="/orders/events/(\d+)/undo"', page, re.S).group(1)
    client.post(f"/orders/events/{event}/undo", data={"csrf": token})


def say(n: int, body: str, customer: str, ago: timedelta = timedelta(0)) -> int:
    add(7000 + n, body, customer=customer, when=datetime.now(UTC) - ago)
    run_batch()
    with SessionLocal() as s:
        return s.execute(text("SELECT id FROM messages WHERE external_message_id = :e"), {"e": str(7000 + n)}).scalar()


def run_auto(seconds: float = 5) -> None:
    auto.run_once(datetime.now(UTC) + timedelta(seconds=seconds))


def needs(db, minutes: float = 0) -> dict:
    with SessionLocal() as s:
        return auto_pages.needs_you(s, datetime.now(UTC) + timedelta(minutes=minutes))


# ---------- A1 delivery statuses ----------

def test_a1_packed_sent_out_delivered(shop, db, tmp_path, monkeypatch):
    client, token = shop
    first = paid_order(client, token, db, tmp_path, monkeypatch, "91", 1)
    second = paid_order(client, token, db, tmp_path, monkeypatch, "92", 2)
    page = client.get("/orders").text
    assert "#1001" in page and "#1002" in page and "📦 Packed" in page and "No. 12, Bahan" in page
    assert 'Orders <span class="badge">2</span>' in page

    # 📦 Packed, with Undo
    tap(client, token, first, "packed")
    assert status(db, first) == "packed" and deliver(db) == []
    undo_last(client, token, first)
    assert status(db, first) == "paid"
    tap(client, token, first, "packed")
    assert "#1001" in client.get("/orders?tab=to_send").text

    # 🚚 Sent out with deli -> exact text with the deli line
    tap(client, token, first, "sent_out", deli_name="Ko Min", deli_phone="09555111222", deli_note="paid deli 3000")
    assert status(db, first) == "sent_out"
    wait = scalar(db, "SELECT send_after - created_at FROM outbox ORDER BY id DESC LIMIT 1")
    assert timedelta(seconds=59) < wait < timedelta(seconds=61)  # 60 s to undo
    assert deliver(db) == [f"Order #1001 ကို ပို့လိုက်ပါပြီ။\nDeli: Ko Min 09555111222\n{FOOTER}"]

    # without deli -> no deli line; Undo within 60 s takes the message back
    tap(client, token, second, "sent_out")
    undo_last(client, token, second)
    assert status(db, second) == "paid" and deliver(db) == []
    tap(client, token, second, "sent_out")
    assert deliver(db) == [f"Order #1002 ကို ပို့လိုက်ပါပြီ။\n{FOOTER}"]

    # ✅ Delivered: no message (setting off) ...
    tap(client, token, second, "delivered")
    assert status(db, second) == "delivered" and deliver(db) == []
    undo_last(client, token, second)
    # ... thank-you when switched on in Settings
    client.post("/settings/order-rules", data={"csrf": token, "reminder_hours": "12", "cancel_hours": "48",
                                                "auto_delivered_days": "5", "thank_you": "1"})
    tap(client, token, second, "delivered")
    assert deliver(db) == ["ပစ္စည်းရရှိပြီဖြစ်လို့ ကျေးဇူးတင်ပါတယ်။ နောက်လည်း အားပေးပါဦးနော်။"]
    with db.connect() as c:
        assert c.execute(text("SELECT action FROM audit_log WHERE action LIKE 'order.%' ORDER BY id")).scalars().all() \
            == ["order.packed", "order.undo", "order.packed", "order.sent_out", "order.sent_out", "order.undo",
                "order.sent_out", "order.delivered", "order.undo", "order.delivered"]

    # sent out 5 days ago -> delivered by itself, no message
    with SessionLocal.begin() as s:
        sent_at = s.get(Order, first).sent_out_at
        assert delivery.auto_deliver(s, sent_at + timedelta(days=4, hours=23)) == 0
        assert delivery.auto_deliver(s, sent_at + timedelta(days=5, minutes=1)) == 1
    assert status(db, first) == "delivered" and deliver(db) == []
    assert "#1001" in client.get("/orders?tab=delivered").text


# ---------- A2 "when will it arrive?" ----------

def test_a2_ask_delivery(shop, db, tmp_path, monkeypatch):
    client, token = shop
    order_id = paid_order(client, token, db, tmp_path, monkeypatch, "91", 1)
    auto_on(db)
    say(1, "ဘယ်တော့ရောက်မလဲ", "91")
    run_auto()
    assert deliver(db) == ["Order #1001 ကို ပြင်ဆင်နေပါတယ်။ ပို့လိုက်တာနဲ့ အကြောင်းကြားပေးပါမယ်နော်။"]

    tap(client, token, order_id, "sent_out", deli_name="Ko Min", deli_phone="09555111222")
    deliver(db)
    say(2, "ဘယ်တော့ရောက်မလဲ", "91")
    run_auto()
    today = delivery.local_date(datetime.now(UTC))
    assert deliver(db) == [f"Order #1001 ကို {today} မှာ ပို့ပြီးပါပြီ။\nDeli: Ko Min 09555111222"]

    # no order -> no auto reply; after 2 minutes it is in Needs you
    mid = say(3, "ဘယ်တော့ရောက်မလဲ", "93", ago=timedelta(minutes=3))
    run_auto()
    assert deliver(db) == []
    assert scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "ask_delivery"
    rows = needs(db).get("unanswered")
    assert [r.message_ids for r in rows] == [[mid]]
    assert "ဘယ်တော့ရောက်မလဲ" in client.get("/").text


# ---------- A3 payment reminder + auto-cancel ----------

def _sent_at(db, customer: str) -> datetime:
    return scalar(db, "SELECT o.payment_info_sent_at FROM orders o JOIN customers c ON c.id = o.customer_id "
                      "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1", e=customer)


def _follow_up(at: datetime) -> dict:
    with SessionLocal.begin() as s:
        return followups.run(s, at)


def _order_of(db, customer: str) -> tuple:
    with db.connect() as c:
        return c.execute(text("SELECT o.id, o.status, o.reminder_sent_at IS NOT NULL FROM orders o JOIN customers c "
                              "ON c.id = o.customer_id WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"),
                         {"e": customer}).one()


def test_a3_reminder_then_auto_cancel(shop, db):
    client, token = shop
    auto_on(db)
    waiting_for_payment(client, token, db, customer="91")
    t0 = _sent_at(db, "91")
    assert _follow_up(t0 + timedelta(hours=11, minutes=59)) == {}
    assert _follow_up(t0 + timedelta(hours=12, minutes=1)) == {"reminder": 1}
    assert _follow_up(t0 + timedelta(hours=13)) == {}  # never more than one reminder
    assert deliver(db) == ["Order အတွက် ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။ "
                           "စုစုပေါင်း 18,000 ကျပ်ပါ။"]
    assert _follow_up(t0 + timedelta(hours=47)) == {}
    assert _follow_up(t0 + timedelta(hours=48, minutes=1)) == {"cancel": 1}
    assert _order_of(db, "91")[1] == "cancelled"
    assert deliver(db) == ["ငွေလွှဲမှု မရရှိသေးတဲ့အတွက် အော်ဒါကို cancel လုပ်ထားပါတယ်။ ပြန်မှာချင်ရင် ပြောပေးပါနော်။"]
    assert _follow_up(t0 + timedelta(hours=60)) == {}
    assert "order cancelled automatically (not paid)" in client.get("/").text  # info in Needs you


def test_a3_photo_at_13h_stops_the_cancel(shop, db):
    client, token = shop
    auto_on(db)
    waiting_for_payment(client, token, db, customer="91")
    t0 = _sent_at(db, "91")
    _follow_up(t0 + timedelta(hours=12, minutes=1))
    deliver(db)
    photo(1)  # the screenshot arrives (13 h in real life; the order now waits for the admin's check)
    assert _follow_up(t0 + timedelta(hours=49)) == {}
    assert _order_of(db, "91")[1] == "photo_received" and deliver(db) == []


def test_a3_auto_off_only_lists_in_needs_you(shop, db):
    client, token = shop
    auto_off()
    waiting_for_payment(client, token, db, customer="94")
    t0 = _sent_at(db, "94")
    now = datetime.now(UTC)
    assert _follow_up(t0 + timedelta(hours=13)) == {} and deliver(db) == []
    unpaid = needs(db, minutes=(t0 + timedelta(hours=13) - now).total_seconds() / 60)["unpaid"]
    assert [(d.what, why) for d, why in unpaid] == [("reminder", "auto-reply is off")]
    assert _follow_up(t0 + timedelta(hours=49)) == {} and _order_of(db, "94")[1] == "waiting_payment"
    unpaid = needs(db, minutes=(t0 + timedelta(hours=49) - now).total_seconds() / 60)["unpaid"]
    assert [d.what for d, _ in unpaid] == ["cancel"]

    # the admin sends the reminder from Needs you: only once
    order_id = _order_of(db, "94")[0]
    client.post(f"/orders/{order_id}/remind", data={"csrf": token})
    client.post(f"/orders/{order_id}/remind", data={"csrf": token})
    assert len(deliver(db)) == 1 and _order_of(db, "94")[2]
    # ... and cancels with the "not paid" message
    client.post(f"/orders/{order_id}/cancel", data={"csrf": token, "message": "order_auto_cancelled",
                                                     "note": "not paid in 49 h"})
    assert _order_of(db, "94")[1] == "cancelled"
    assert deliver(db) == ["ငွေလွှဲမှု မရရှိသေးတဲ့အတွက် အော်ဒါကို cancel လုပ်ထားပါတယ်။ ပြန်မှာချင်ရင် ပြောပေးပါနော်။"]


def test_a3_never_auto_customer_is_not_reminded(shop, db):
    client, token = shop
    auto_on(db)
    cid = waiting_for_payment(client, token, db, customer="95")
    client.post(f"/customers/{cid}/auto", data={"csrf": token, "off": "1"})
    assert _follow_up(_sent_at(db, "95") + timedelta(hours=13)) == {} and deliver(db) == []


# ---------- A4 unanswered -> Needs you ----------

def test_a4_unanswered_with_open_cart(shop, db):
    client, token = shop
    auto_on(db)
    say(1, "stw intensely 5ml ယူမယ်", "91", ago=timedelta(minutes=5))
    run_auto()
    assert len(deliver(db)) == 1  # cart list
    mid = say(2, "authentic လား", "91", ago=timedelta(seconds=10))
    run_auto()
    assert deliver(db) == []  # not certain: no auto reply
    assert needs(db, minutes=1)["unanswered"] == []  # not yet 2 minutes
    rows = needs(db, minutes=2.5)["unanswered"]
    assert [(r.customer.external_user_id, r.message_ids, r.reason) for r in rows] == [("91", [mid], "open order")]

    # the admin replies (custom) -> cleared
    cid = customer_id(db, "91")
    page = client.get(f"/chats/{cid}").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "reply_kind": "custom",
                                            "text": "အားလုံး original ပါ"})
    assert needs(db, minutes=3)["unanswered"] == []
    deliver(db)
    assert needs(db, minutes=3)["unanswered"] == []

    # a question from someone without an order counts too; "done" clears it
    other = say(3, "ဟိုင်း", "96", ago=timedelta(minutes=10))
    assert [r.message_ids for r in needs(db)["unanswered"]] == [[other]]
    client.post("/needs-you/clear", data={"csrf": token, "message_id": str(other), "status": "done"})
    assert needs(db)["unanswered"] == []


# ---------- A5 cancel the whole order ----------

def test_a5_cancel_open_cart(shop, db):
    client, token = shop
    auto_on(db)
    say(1, "stw intensely 5ml, sauvage edp 10ml ယူပါမယ်", "91", ago=timedelta(minutes=5))
    run_auto()
    deliver(db)
    # with a product name: remove that item (unchanged behaviour)
    say(2, "sauvage edp 10ml မယူတော့ဘူး", "91", ago=timedelta(minutes=4))
    run_auto()
    assert deliver(db) == ["• Stronger With You Intensely 5ml – 18,000 ကျပ်\nစုစုပေါင်း 18,000 ကျပ်ပါ။\n"
                           "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]
    # without: the whole order
    mid = say(3, "မယူတော့ဘူး", "91", ago=timedelta(minutes=3))
    assert scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "cancel_order"
    run_auto()
    assert _order_of(db, "91")[1] == "cancelled"
    assert deliver(db) == ["အော်ဒါ cancel လုပ်ပြီးပါပြီ။ နောက်မှ ပြန်မှာချင်ရင် ပြောပေးပါနော်။"]
    assert needs(db)["unanswered"] == []


def test_a5_cancel_paid_order_needs_you(shop, db, tmp_path, monkeypatch):
    client, token = shop
    order_id = paid_order(client, token, db, tmp_path, monkeypatch, "91", 1)
    auto_on(db)
    mid = say(1, "အော်ဒါ cancel", "91")
    run_auto()
    assert deliver(db) == [] and status(db, order_id) == "paid"  # no auto
    found = needs(db)["cancels"]
    assert [(m.id, o.id) for m, _, o in found] == [(mid, order_id)]
    assert "wants to cancel a paid order" in client.get("/").text
    # the admin decides: cancel + note (refund outside the system)
    client.post(f"/orders/{order_id}/cancel", data={"csrf": token, "note": "refunded 18,000 by KPay",
                                                     "message": "order_cancelled"})
    assert status(db, order_id) == "cancelled"
    assert scalar(db, "SELECT cancel_note FROM orders WHERE id = :o", o=order_id) == "refunded 18,000 by KPay"
    assert deliver(db) == ["အော်ဒါ cancel လုပ်ပြီးပါပြီ။ နောက်မှ ပြန်မှာချင်ရင် ပြောပေးပါနော်။"]
    assert needs(db)["cancels"] == []


# ---------- A6 wanted but not stocked ----------

def test_a6_wanted_report(shop, db):
    client, token = shop
    for n, customer in ((1, "81"), (2, "82")):
        mid = say(n, "hawas ice 10ml ဘယ်လောက်လဲ", customer)
        client.post(f"/messages/{mid}/unknown/0/not-stocked", data={"csrf": token})
    say(3, "ysl y edp 10ml ရှိလား", "83")  # sold out in the price list
    page = client.get("/reports/wanted").text
    rows = re.findall(r"<tr><td>([^<]+?) <span[^>]*>[^<]+</span></td>\s*<td class=\"num\">(\d+)</td>"
                      r"<td class=\"num\">(\d+)</td>", page)
    assert rows == [("hawas ice", "2", "2"), ("Y Eau de Parfum 10ml", "1", "1")]


@pytest.mark.parametrize("body, intent", [
    ("ဘယ်တော့ရောက်မလဲ", "ask_delivery"), ("ရောက်ပြီလား", "ask_delivery"), ("deli ပို့ပြီးပြီလား", "ask_delivery"),
    ("deli", "ask_delivery"), ("Bahan, deli နဲ့ ပို့ပေးပါ", "address"), ("မယူတော့ဘူး", "cancel_order"),
    ("မမှာတော့ဘူး", "cancel_order"), ("cancel", "cancel_order"), ("အော်ဒါ cancel", "cancel_order"),
    ("i dont want anymore, cancel my order", "cancel_order"),
])
def test_new_intents(body, intent):
    from app.parser.normalize import normalize
    from app.parser.rules import parse

    assert parse(normalize(body), []).intent == intent
