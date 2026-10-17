"""docs/SPEC-v4.12-address-payment-ai.md acceptance tests P1-P10 (fake AI provider; no network).

N0 repair + guard, N1 AI address assistant, N2 address gates, N3 AI payment-screenshot reader,
N4 /ai switches and counts."""
import re
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.orders import address
from scripts import repair_addresses
from tests.test_cart import deliver, order_row, say, shop, tap  # noqa: F401  (fixture)
from tests.test_messaging import customer_id, scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)

BAD = "လိပ်စာ ပြောင်းချင်ပါတယ်"


def send_payment_info(client, token, cid: int) -> str:
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    r = client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "reply_kind": "payment_info",
                                                 "text": "info"})
    return r.headers.get("location", "")


def confirmed_cart(client, token, db, customer="91", address_text="No. 12, Bahan") -> int:
    """A confirmed cart (Stronger With You Intensely 5ml) with a phone (and an address if given)."""
    say(db, 0, "hi", customer=customer)
    cid = customer_id(db, customer)
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5"})
    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    client.post(f"/chats/{cid}/cart/phones", data={"csrf": token, "phone": "09777123456"})
    if address_text:
        client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": address_text})
    return cid


def flags(db, customer="91") -> tuple:
    with db.connect() as c:
        return c.execute(text(
            "SELECT o.address_invalid, c.address_invalid FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


def repair(monkeypatch, capsys) -> str:
    monkeypatch.setattr(sys, "argv", ["repair_addresses"])
    assert repair_addresses.main() == 0
    return capsys.readouterr().out


# ---------- the validator ----------

@pytest.mark.parametrize("raw, status, township", [
    (BAD, "invalid", None),
    ("ဒီကိုပို့ပေးပါ ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅", "valid", "Bahan"),
    ("သုခလမ်း အမှတ် ၁၂", "partial", None),
    ("ရန်ကင်း", "invalid", "Yankin"),  # a township alone is shorter than 8 characters
    ("No 5, Bo Aung Kyaw St, Kyauktada Township, Yangon", "valid", "Kyauktada"),
    ("ပြည်လမ်း အမှတ် ၄၅ ကမာရွတ်", "valid", "Kamayut"),  # "ပြည်လမ်း" is a street, not Pyay
    ("ပြည်သူ့ဆေးရုံ နား အမှတ် 5", "partial", None),  # "ပြည်သူ့" is no township either
    ("35 လမ်း 80x81 ကြား မန္တလေး", "valid", None),  # city + street
    ("No 7 Shwe Taung Gyar Rd, Zigon township", "invalid", None),  # unknown township
    ("address", "invalid", None),
])
def test_validator(raw, status, township):
    check = address.validate(raw)
    assert check.status == status
    assert (check.township.en if check.township else None) == township
    assert "ပို့ပေးပါ" not in check.parts.full_text and "ဒီကို" not in check.parts.full_text


def test_validator_never_keeps_a_phone():
    check = address.validate("ဗဟန်း သုခလမ်း အမှတ် ၅ ဖုန်း ၀၉၇၇၇၁၂၃၄၅၆")
    assert check.valid and "၀၉၇" not in check.parts.full_text and "ဖုန်း" not in check.parts.full_text
    assert check.parts.full_text == "ဗဟန်း သုခလမ်း အမှတ် ၅"  # digits as written


# ---------- P1 N0: the live data case ----------

def test_p1_repair_marks_invalid_and_blocks_payment_info(shop, db, monkeypatch, capsys):
    client, token = shop
    cid = confirmed_cart(client, token, db, address_text=None)
    with db.begin() as c:  # left-over damage from the 4.8 bug (saved before the validator existed)
        c.execute(text("UPDATE orders SET address = :a"), {"a": BAD})
        c.execute(text("UPDATE customers SET address = :a WHERE external_user_id = '91'"), {"a": BAD})
    out = repair(monkeypatch, capsys)
    assert re.search(r"order id=\d+ no order ID confirmed: invalid \(keywords\)", out) and "customer id=" in out
    assert BAD not in out  # ids and reasons only
    assert flags(db) == (True, True)
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "⚠️ invalid address" in page and "Next: Send payment info" not in page
    assert "The address is not valid: fix it in the cart panel." in page
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    assert "The address is not valid: fix it in the cart panel." in page and 'name="key"' not in page
    assert scalar(db, "SELECT count(*) FROM outbox WHERE reply_kind = 'payment_info'") == 0
    assert order_row(db)[0] == "confirmed"
    # the invalid address is never offered as "same as last time"
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": BAD})  # the validator refuses it
    assert flags(db) == (True, True)
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": "No. 5, Sanchaung"})
    assert flags(db) == (False, False) and order_row(db)[2] == "No. 5, Sanchaung"
    assert "Next: Send payment info" in client.get(f"/chats/{cid}?tab=cart").text
    send_payment_info(client, token, cid)
    assert order_row(db)[0] == "waiting_payment"
    assert "0 invalid address(es) marked." in repair(monkeypatch, capsys)  # idempotent


def test_p1_paid_order_fixed_with_edit_locked_order(shop, db, monkeypatch, capsys):
    client, token = shop
    confirmed_cart(client, token, db, address_text=None)
    with db.begin() as c:
        c.execute(text("UPDATE orders SET address = :a, status = 'paid', order_no = 1001, paid_at = now()"),
                  {"a": BAD})
        c.execute(text("UPDATE customers SET address = :a WHERE external_user_id = '91'"), {"a": BAD})
    assert "#1001 paid: invalid (keywords)" in repair(monkeypatch, capsys)
    page = client.get("/orders?tab=all").text
    assert "⚠️ invalid address" in page
    oid = scalar(db, "SELECT id FROM orders")
    form = {"csrf": token, "address": BAD, "phones": "09777123456", "reason": "customer sent the new address",
            "back": "/orders?tab=all"}
    client.post(f"/orders/{oid}/edit-locked", data=form)
    assert flags(db) == (True, True)  # still invalid: refused
    client.post(f"/orders/{oid}/edit-locked", data={**form, "address": "No. 9, Thida St, Dagon"})
    assert flags(db) == (False, False)
    assert scalar(db, "SELECT address FROM customers WHERE external_user_id = '91'") == "No. 9, Thida St, Dagon"
    assert "⚠️ invalid address" not in client.get("/orders?tab=all").text


# ---------- P4: keyword-only / change requests never become an address ----------

@pytest.mark.parametrize("body", [BAD, "လိပ်စာ", "ပို့ပေးပါ", "address", "ဒီလိပ်စာကို ပို့ပေးပါ", "change address",
                                  "လိပ်စာ အသစ် ပို့ပေးမယ်နော်"])
def test_p4_keywords_never_an_address(shop, db, body):
    client, token = shop
    confirmed_cart(client, token, db, address_text=None)
    mid = say(db, 5, body)
    with SessionLocal() as s:
        from app.models import Message

        assert address.read_message(s, s.get(Message, mid)) is None
    from tests.test_cart import button

    b = button(client, mid)
    assert b is None or "Save address" not in b[0]
    assert order_row(db)[2] is None
