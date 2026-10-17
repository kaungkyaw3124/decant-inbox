"""Steps 4 + 4b: cart flow with one-tap actions and exact undo; partial carts (unknown /
unpriced / out-of-stock items); phone first, then address; several phones; editable
address; same phone & address next time; payment info blockers; idle carts."""
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
Y_SOLD_OUT = ["Yves Saint Laurent", "Y Eau de Parfum", 100, 380000, 8000, 18000, 34000, "no"]
START = datetime.now(UTC) - timedelta(hours=1)
PAYMENT_FOOTER = "KPay – 09000000001 (Test Shop)\nငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။"


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


def tap(client, token, mid: int, **extra) -> None:
    _, _, expect = button(client, mid)
    r = client.post(f"/messages/{mid}/quick", data={"csrf": token, "expect": expect, **extra},
                    follow_redirects=False)
    assert r.status_code == 303, r.text


def deliver(db) -> list[str]:
    """Let the 10 s pass and send everything queued with a fake Telegram client."""
    with db.begin() as c:
        c.execute(text("UPDATE outbox SET send_after = now() - interval '1 second' WHERE status = 'queued'"))
    fake = FakeClient()
    while asyncio.run(sender.send_next(fake, sender.RateLimiter())):  # a new limiter: no 3 s wait
        pass
    return [t for _, t in fake.sent]


def order_row(db, customer="91"):
    with db.connect() as c:
        return c.execute(text(
            "SELECT o.status, o.total_mmk, o.address, o.phones FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


def phones(db, customer="91") -> list[str]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT p.phone FROM customer_phones p JOIN customers c ON c.id = p.customer_id "
            "WHERE c.external_user_id = :e ORDER BY p.position"), {"e": customer}).scalars())


def items(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT coalesce(p.name, '?' || i.unknown_text), i.size_ml, i.is_full_bottle, i.quantity, i.unit_price_mmk "
            "FROM order_items i LEFT JOIN products p ON p.id = i.product_id WHERE i.removed_at IS NULL ORDER BY i.id")))


@pytest.fixture
def shop(client, db):  # noqa: F811
    token = log_in(client)
    run_import(xlsx(STW, SAUVAGE, Y_SOLD_OUT))
    client.post("/settings/payment-methods", data={"csrf": token, "name": "KPay", "account_number": "09000000001",
                                                   "account_name": "Test Shop"})
    return client, token


def test_whole_flow_phone_first_with_undo(shop, db):
    client, token = shop
    buy = say(db, 1, "stw intensely 5ml, sauvage edp 10ml ယူပါမယ်")
    label, tooltip, _ = button(client, buy)
    assert label == "🛒 Add to cart + send list"
    assert ("• Stronger With You Intensely 5ml – 18,000 ကျပ်\n• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်\n"
            "စုစုပေါင်း 56,000 ကျပ်ပါ။") in tooltip
    assert scalar(db, "SELECT count(*) FROM orders") == 0  # the preview changed nothing

    tap(client, token, buy)
    assert order_row(db)[:2] == ("cart", 56000) and len(items(db)) == 2
    aid = scalar(db, "SELECT id FROM quick_actions")
    client.post(f"/quick/{aid}/undo", data={"csrf": token})  # Undo: all gone again
    assert order_row(db)[0] == "cancelled" and items(db) == []
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=buy) == "new"
    tap(client, token, buy)
    assert deliver(db)[0].startswith("မင်္ဂလာပါ။\n• Stronger With You Intensely 5ml – 18,000 ကျပ်")

    tap(client, token, say(db, 2, "sauvage edp မယူတော့ဘူး"))
    assert items(db) == [("Stronger With You Intensely", 5, False, 1, 18000)]
    deliver(db)

    ok = say(db, 3, "ok")
    assert button(client, ok)[0] == "✅ Confirm + ask phone"
    tap(client, token, ok)
    assert deliver(db) == ["ဆက်သွယ်ရန် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]

    two = say(db, 4, "09 777 123 456 နဲ့ ၀၉ ၄၄၄ ၅၅၅ ၆၆၆")
    assert button(client, two)[0] == "📞 Save phones + ask address"
    tap(client, token, two)
    assert phones(db) == ["09777123456", "09444555666"] and order_row(db)[3] == ["09777123456", "09444555666"]
    assert deliver(db) == ["ဖုန်းနံပါတ် 09777123456, 09444555666 ရပါပြီ။ ပို့ပေးရမယ့် လိပ်စာ ပို့ပေးပါနော်။"]

    address = say(db, 5, "အမှတ် ၁၂, ဗဟန်း ကိုပို့ပေးပါ")
    label, tooltip, _ = button(client, address)
    assert label == "📍 Save address + 💳 send payment info" and "Saves: အမှတ် 12, ဗဟန်း." in tooltip
    tap(client, token, address)
    assert order_row(db)[:3] == ("waiting_payment", 18000, "အမှတ် 12, ဗဟန်း")
    aid = scalar(db, "SELECT id FROM quick_actions WHERE message_id = :m", m=address)
    client.post(f"/quick/{aid}/undo", data={"csrf": token})
    assert order_row(db)[:3] == ("confirmed", 18000, None)
    assert scalar(db, "SELECT address FROM customers WHERE external_user_id = '91'") is None

    # the cart panel offers the same action with the address editable before the tap
    cid = customer_id(db, "91")
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "Address to save (you can fix it first)" in page and "အမှတ် 12, ဗဟန်း</textarea>" in page
    tap(client, token, address, address="No. 12, Bahan Road, Bahan", back=f"/chats/{cid}?tab=cart")
    assert order_row(db)[:3] == ("waiting_payment", 18000, "No. 12, Bahan Road, Bahan")
    assert deliver(db) == ["• Stronger With You Intensely 5ml – 18,000 ကျပ်\nစုစုပေါင်း 18,000 ကျပ်ပါ။\n"
                           + PAYMENT_FOOTER]

    # a later message with another number: added as phone 3, short reply
    third = say(db, 6, "ph 09 111 222 333 လည်းရပါတယ်")
    assert button(client, third)[0] == "📞 Save phone + reply"
    tap(client, token, third)
    assert phones(db) == ["09777123456", "09444555666", "09111222333"]
    # docs/SPEC-v4.10-interruptions.md: + the resume line (still waiting for the payment screenshot)
    assert deliver(db) == ["ဖုန်းနံပါတ် 09111222333 ကိုလည်း ထည့်ထားပါပြီ။\nငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။"]
    assert button(client, say(db, 7, "09 999 888 777")) is None  # max 3 numbers: use the cart panel


def test_partial_cart(shop, db):
    client, token = shop
    buy = say(db, 1, "stw intensely 5ml, ysl y edp 5ml, sauvage edp 3ml, hawas ice 10ml ယူမယ်", customer="95")
    label, tooltip, _ = button(client, buy)
    assert label == "🛒 Add 1 known item + send list"
    tap(client, token, buy)
    assert items(db) == [("Stronger With You Intensely", 5, False, 1, 18000),
                         ("Sauvage Eau de Parfum", 3, False, 1, None), ("?hawas ice", 10, False, 1, None)]
    assert deliver(db) == ["မင်္ဂလာပါ။\n• Stronger With You Intensely 5ml – 18,000 ကျပ်\n"
                           "စုစုပေါင်း 18,000 ကျပ်ပါ။\n"
                           "hawas ice 10ml, Sauvage Eau de Parfum 3ml ကိုတော့ စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။\n"
                           "Y Eau de Parfum 5ml လောလောဆယ် ကုန်နေပါတယ်နော်။\n"
                           "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]
    cid = customer_id(db, "95")
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "❓ hawas ice" in page and "not in product list" in page and "no price" in page
    # confirm + phone + address: everything saved, but payment info stays blocked
    tap(client, token, say(db, 2, "ok", customer="95"))
    deliver(db)
    contact = say(db, 3, "09 777 123 456 အမှတ် ၁၂, ဗဟန်း ကိုပို့ပေးပါ", customer="95")
    label, tooltip, _ = button(client, contact)
    assert label == "📞 Save phone & 📍 Save address"  # no payment info: red items first
    assert "Still to check before payment: hawas ice 10ml, Sauvage Eau de Parfum 3ml" in tooltip
    tap(client, token, contact)
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    assert "Not in the product list: hawas ice 10ml" in page and "No price for: Sauvage Eau de Parfum 3ml" in page
    # removing the red rows -> new confirmation -> payment info is the next step
    with db.connect() as c:
        red = c.execute(text("SELECT id FROM order_items WHERE unit_price_mmk IS NULL AND removed_at IS NULL")
                        ).scalars().all()
    for item_id in red:
        client.post(f"/chats/{cid}/cart/items/{item_id}/remove", data={"csrf": token})
    assert order_row(db, "95")[0] == "cart"  # changed items: needs a new confirmation
    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    assert "Next: Send payment info" in client.get(f"/chats/{cid}?tab=cart").text


def test_same_phone_and_address_next_time(shop, db):
    client, token = shop
    with db.begin() as c:
        cid = c.execute(text("INSERT INTO customers (channel, external_user_id, address, phone) VALUES "
                             "('telegram', '92', 'No. 5, Sanchaung', '09111222333') RETURNING id")).scalar()
        c.execute(text("INSERT INTO customer_phones (customer_id, phone, position) VALUES (:c, '09111222333', 1)"),
                  {"c": cid})
    tap(client, token, say(db, 1, "stw intensely 10ml ယူမယ်", customer="92"))
    assert deliver(db)[0].endswith("ဖုန်း 09111222333၊ လိပ်စာ No. 5, Sanchaung ကိုပဲ ပို့ပေးရမလား။")
    ok = say(db, 2, "ဟုတ်ကဲ့", customer="92")
    assert button(client, ok)[0] == "✅ Confirm + 💳 send payment info"  # "yes, same as last time"
    tap(client, token, ok)
    assert deliver(db)[0].endswith(PAYMENT_FOOTER)
    assert order_row(db, "92")[:4] == ("waiting_payment", 33000, "No. 5, Sanchaung", ["09111222333"])

    # the cart panel offers the same when the admin confirms by hand
    client.post(f"/chats/{cid}/cart/cancel", data={"csrf": token})
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "10"})
    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "Next: Same phone &amp; address as last time" in page and "09111222333" in page
    client.post(f"/chats/{cid}/cart/same-contact", data={"csrf": token})
    assert order_row(db, "92")[2:] == ("No. 5, Sanchaung", ["09111222333"])
    assert "Next: Send payment info" in client.get(f"/chats/{cid}?tab=cart").text

    page = client.get(f"/chats/{cid}?compose=payment_info").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    body = html.unescape(re.search(r'<textarea name="text"[^>]*>([^<]*)</textarea>', page).group(1))
    assert body.endswith(PAYMENT_FOOTER)
    client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "reply_kind": "payment_info", "text": body})
    assert order_row(db, "92")[0] == "waiting_payment"


def test_cart_panel_phones_and_blockers(shop, db):
    client, token = shop
    add(1, "hi", customer="93")
    cid = customer_id(db, "93")
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "100"})
    assert items(db) == [("Stronger With You Intensely", None, True, 1, 380000)]  # 100ml = full bottle
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    assert "not confirmed the cart yet" in page and "No phone yet" in page and "No address yet" in page
    r = client.post(f"/chats/{cid}/send", data={"csrf": token, "key": "k", "reply_kind": "payment_info", "text": "x"})
    assert "Not sent" in r.text and scalar(db, "SELECT count(*) FROM outbox") == 0

    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    assert "Next: Ask for phone" in client.get(f"/chats/{cid}?tab=cart").text
    for number in ("09 5555 6666", "၀၉၇၇၇၇၈၈၈၈", "+959 4444 3333", "09 1111 2222"):
        client.post(f"/chats/{cid}/cart/phones", data={"csrf": token, "phone": number})
    assert phones(db, "93") == ["0955556666", "0977778888", "0944443333"]  # max 3
    client.post(f"/chats/{cid}/cart/phones/2/up", data={"csrf": token})
    client.post(f"/chats/{cid}/cart/phones/0/remove", data={"csrf": token})
    assert phones(db, "93") == order_row(db, "93")[3] == ["0944443333", "0977778888"]
    assert scalar(db, "SELECT phone FROM customers WHERE external_user_id = '93'") == "0944443333"
    assert "Next: Ask for address" in client.get(f"/chats/{cid}?tab=cart").text
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": "Yankin"})  # 4.12: too short
    assert "Next: Ask for address" in client.get(f"/chats/{cid}?tab=cart").text
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": "No. 3, Kaba Aye Rd, Yankin"})
    assert "Next: Send payment info" in client.get(f"/chats/{cid}?tab=cart").text
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
