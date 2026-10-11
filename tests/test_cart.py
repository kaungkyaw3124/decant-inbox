"""Step 4: cart flow with one-tap actions (buy -> remove -> confirm -> address -> payment
info), undo of each, "same address as last time", payment info blockers, idle carts."""
import asyncio
import html
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.listener import sender
from app.orders import cart
from app.parser.worker import run_batch
from tests.test_messaging import FakeClient, add, customer_id, scalar
from tests.test_prices import STW, run_import, xlsx
from tests.test_web import client, log_in  # noqa: F401  (fixture)

SAUVAGE = ["Dior", "Sauvage Eau de Parfum", 100, 420000, None, 20000, 38000, "yes"]
START = datetime.now(UTC) - timedelta(hours=1)


def say(db, n: int, body: str, customer: str = "91") -> int:
    """Customer message n minutes after START; returns its id once parsed."""
    add(1000 + n, body, customer=customer, when=START + timedelta(minutes=n))
    run_batch()
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(1000 + n))


def button(client, mid: int) -> tuple[str, str, str] | None:
    """(label, tooltip, fingerprint) of the one-tap button of a message."""
    page = client.get("/?intent=all&status=all").text
    m = re.search(rf'id="msg-{mid}".*?(?:action="/messages/{mid}/quick".*?name="expect" value="([^"]+)".*?'
                  rf'title="([^"]*)">([^<]+)</button>|</li>)', page, re.S)
    return (html.unescape(m.group(3)), html.unescape(m.group(2)), m.group(1)) if m and m.group(1) else None


def tap(client, token, mid: int) -> None:
    label, _, expect = button(client, mid)
    r = client.post(f"/messages/{mid}/quick", data={"csrf": token, "expect": expect}, follow_redirects=False)
    assert r.status_code == 303, r.text


def deliver(db) -> list[tuple[int, str]]:
    """Let the 10 s pass and send everything queued with a fake Telegram client."""
    with db.begin() as c:
        c.execute(text("UPDATE outbox SET send_after = now() - interval '1 second' WHERE status = 'queued'"))
    fake = FakeClient()
    while asyncio.run(sender.send_next(fake, sender.RateLimiter())):  # a new limiter: no 3 s wait
        pass
    return fake.sent


def order_row(db, customer="91"):
    with db.connect() as c:
        return c.execute(text(
            "SELECT o.status, o.total_mmk, o.address, o.phone FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


def items(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT p.name, i.size_ml, i.is_full_bottle, i.quantity, i.unit_price_mmk FROM order_items i "
            "JOIN products p ON p.id = i.product_id WHERE i.removed_at IS NULL ORDER BY i.id")))


@pytest.fixture
def shop(client, db):  # noqa: F811
    token = log_in(client)
    run_import(xlsx(STW, SAUVAGE))
    client.post("/settings/payment-methods", data={"csrf": token, "name": "KPay", "account_number": "09000000001",
                                                   "account_name": "Test Shop"})
    return client, token


def test_whole_flow_with_undo(shop, db):
    client, token = shop
    buy = say(db, 1, "stw intensely 5ml, sauvage edp 10ml ယူပါမယ်")
    label, tooltip, _ = button(client, buy)
    assert label == "🛒 Add to cart + send list"
    assert ("• Stronger With You Intensely 5ml – 18,000 ကျပ်\n• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်\n"
            "စုစုပေါင်း 56,000 ကျပ်ပါ။") in tooltip
    assert scalar(db, "SELECT count(*) FROM orders") == 0  # the preview changed nothing

    tap(client, token, buy)
    assert order_row(db)[:2] == ("cart", 56000) and len(items(db)) == 2
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=buy) == "done"
    # Undo: items gone, the new empty cart cancelled, reply cancelled, message back to new
    aid = scalar(db, "SELECT id FROM quick_actions")
    client.post(f"/quick/{aid}/undo", data={"csrf": token})
    assert order_row(db)[0] == "cancelled" and items(db) == []
    assert scalar(db, "SELECT status FROM outbox") == "cancelled"
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=buy) == "new"

    tap(client, token, buy)  # again, for real
    sent = deliver(db)
    assert sent[0][1].startswith("မင်္ဂလာပါ။\n• Stronger With You Intensely 5ml – 18,000 ကျပ်")

    remove = say(db, 2, "sauvage edp မယူတော့ဘူး")
    assert button(client, remove)[0] == "➖ Remove + send list"
    tap(client, token, remove)
    assert items(db) == [("Stronger With You Intensely", 5, False, 1, 18000)]
    assert deliver(db)[0][1] == ("• Stronger With You Intensely 5ml – 18,000 ကျပ်\n"
                                 "စုစုပေါင်း 18,000 ကျပ်ပါ။ အဆင်ပြေရင် confirm လုပ်ပေးပါနော်။")  # no greeting: < 6 h

    ok = say(db, 3, "ok")
    assert button(client, ok)[0] == "✅ Confirm + ask address & phone"
    tap(client, token, ok)
    assert order_row(db)[0] == "confirmed"
    assert deliver(db)[0][1] == "ပို့ပေးရမယ့် လိပ်စာနဲ့ ဖုန်းနံပါတ် ပို့ပေးပါနော်။"

    address = say(db, 4, "အမှတ် ၁၂, ဗဟန်း 09 777 123 456")
    label, tooltip, _ = button(client, address)
    assert label == "📍 Save address + 💳 send payment info"
    assert "KPay – 09000000001 (Test Shop)" in tooltip and "Saves: အမှတ် 12, ဗဟန်း, 09777123456" in tooltip
    tap(client, token, address)
    assert order_row(db) == ("waiting_payment", 18000, "အမှတ် 12, ဗဟန်း", "09777123456")
    assert scalar(db, "SELECT address FROM customers WHERE external_user_id = '91'") == "အမှတ် 12, ဗဟန်း"

    # Undo of the address action: back to confirmed, address forgotten again
    aid = scalar(db, "SELECT id FROM quick_actions WHERE message_id = :m", m=address)
    client.post(f"/quick/{aid}/undo", data={"csrf": token})
    assert order_row(db)[:3] == ("confirmed", 18000, None)
    assert scalar(db, "SELECT address FROM customers WHERE external_user_id = '91'") is None

    tap(client, token, address)
    payment = deliver(db)[0][1]
    assert payment == ("• Stronger With You Intensely 5ml – 18,000 ကျပ်\nစုစုပေါင်း 18,000 ကျပ်ပါ။\n"
                       "KPay – 09000000001 (Test Shop)\nငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။")
    cid = customer_id(db, "91")
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "💳 waiting for payment" in page and "Waiting for the payment screenshot" in page
    assert scalar(db, "SELECT count(*) FROM audit_log WHERE action = 'quick.cart_add'") == 2


def test_same_address_next_time_and_payment_via_editor(shop, db):
    client, token = shop
    with db.begin() as c:
        c.execute(text("INSERT INTO customers (channel, external_user_id, address, phone) "
                       "VALUES ('telegram', '92', 'No. 5, Sanchaung', '09111222333')"))
    tap(client, token, say(db, 1, "stw intensely 10ml ယူမယ်", customer="92"))
    deliver(db)
    ok = say(db, 2, "ဟုတ်ကဲ့", customer="92")
    assert button(client, ok)[0] == "✅ Confirm cart"  # address known from last time: don't ask
    tap(client, token, ok)
    cid = customer_id(db, "92")
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "Next: Use same address as last time" in page and "No. 5, Sanchaung" in page
    client.post(f"/chats/{cid}/cart/same-address", data={"csrf": token})
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "Next: Send payment info" in page

    page = client.get(f"/chats/{cid}?compose=payment_info").text
    assert "KPay – 09000000001 (Test Shop)" in page
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    body = re.search(r'<textarea name="text"[^>]*>([^<]*)</textarea>', page).group(1)
    client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "reply_kind": "payment_info", "text": body})
    assert order_row(db, "92")[:3] == ("waiting_payment", 33000, "No. 5, Sanchaung")


def test_payment_info_blocked_until_ready(shop, db):
    client, token = shop
    add(1, "hi", customer="93")
    cid = customer_id(db, "93")
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "3", "quantity": "2"})
    assert items(db) == [("Stronger With You Intensely", 3, False, 2, None)]
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    assert "not confirmed the cart yet" in page and "No price for: Stronger With You Intensely 3ml × 2" in page
    assert "No address yet" in page and "/send" not in page.split('id="reply"')[1]
    r = client.post(f"/chats/{cid}/send", data={"csrf": token, "key": "k", "reply_kind": "payment_info", "text": "x"})
    assert "Not sent" in r.text and scalar(db, "SELECT count(*) FROM outbox") == 0

    item_id = scalar(db, "SELECT id FROM order_items")
    client.post(f"/chats/{cid}/cart/items/{item_id}/remove", data={"csrf": token})
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "100", "quantity": "1"})
    assert items(db) == [("Stronger With You Intensely", None, True, 1, 380000)]  # 100ml = full bottle
    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    client.post(f"/chats/{cid}/cart/contact", data={"csrf": token, "address": "Yankin", "phone": "09 5555 6666"})
    assert order_row(db, "93") == ("confirmed", 380000, "Yankin", "0955556666")
    assert "Next: Send payment info" in client.get(f"/chats/{cid}?tab=cart").text
    # changing the items of a confirmed cart needs a new confirmation
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5", "quantity": "1"})
    assert order_row(db, "93")[:2] == ("cart", 398000)
    client.post(f"/chats/{cid}/cart/cancel", data={"csrf": token})
    assert order_row(db, "93")[0] == "cancelled"


def test_idle_carts_are_abandoned(shop, db):
    client, token = shop
    add(1, "hi", customer="94")
    cid = customer_id(db, "94")
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5"})
    with SessionLocal.begin() as s:
        assert cart.abandon_idle(s) == 0
        assert cart.abandon_idle(s, now=datetime.now(UTC) + timedelta(days=3, minutes=1)) == 1
    assert order_row(db, "94")[0] == "abandoned"
