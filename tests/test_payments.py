"""Step 5: payment screenshots -> checks; approve (Order ID, confirmation, warnings),
reject (3 reasons), not a payment, several photos."""
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.orders import auto, payments
from app.web import chats
from tests.test_cart import deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def waiting_for_payment(client, token, db, customer="91") -> int:
    """A confirmed cart (Stronger With You Intensely 5ml, 18,000) with payment info sent."""
    add(1, "hi", customer=customer, when=datetime.now(UTC) - timedelta(hours=1))
    cid = customer_id(db, customer)
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5"})
    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    for number in ("09777123456", "09444555666"):
        client.post(f"/chats/{cid}/cart/phones", data={"csrf": token, "phone": number})
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": "No. 12, Bahan"})
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "reply_kind": "payment_info", "text": "info"})
    deliver(db)
    return cid


def photo(n: int, customer="91", grouped_id=None, seconds_ago=0) -> None:
    add(500 + n, "", customer=customer, kind="photo", grouped_id=grouped_id,
        when=datetime.now(UTC) - timedelta(seconds=seconds_ago))
    with SessionLocal.begin() as s:
        payments.scan(s)


def downloaded(db, tmp_path, monkeypatch, check_id: int, content: bytes = b"\xff\xd8shot") -> None:
    """What the listener does after the card was opened."""
    import hashlib

    monkeypatch.setattr(chats, "MEDIA_DIR", tmp_path)
    mid = scalar(db, "SELECT message_id FROM payment_checks WHERE id = :c", c=check_id)
    (tmp_path / f"{mid}.jpg").write_bytes(content)
    with db.begin() as c:
        c.execute(text("UPDATE media_downloads SET status = 'done', path = :p, sha256 = :h WHERE message_id = :m"),
                  {"p": f"{mid}.jpg", "h": hashlib.sha256(content).hexdigest(), "m": mid})


def order(db, customer="91"):
    with db.connect() as c:
        return c.execute(text("SELECT o.status, o.order_no FROM orders o JOIN customers c ON c.id = o.customer_id "
                              "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


@pytest.fixture
def paying(shop, db):
    client, token = shop
    cid = waiting_for_payment(client, token, db)
    return client, token, cid


def test_approve_gives_order_id_and_sends_confirmation(paying, db, tmp_path, monkeypatch):
    client, token, cid = paying
    photo(1)
    assert order(db) == ("photo_received", None)
    check = scalar(db, "SELECT id FROM payment_checks")
    assert "Payments <span class=\"badge warn\">1</span>" in client.get("/").text
    assert "payment screenshot to check" in client.get("/").text
    assert "💳 Check the payment screenshot" in client.get(f"/chats/{cid}?tab=cart").text

    page = client.get(f"/payments/{check}").text  # opening the card asks the listener for the photo
    assert "Loading the screenshot" in page and scalar(db, "SELECT status FROM media_downloads") == "queued"
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "18000"})
    assert r.status_code == 400 and "still loading" in r.text
    downloaded(db, tmp_path, monkeypatch, check)
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "", "amount": "18000"})
    assert "transaction ID is required" in r.text

    # amount differs -> warning, nothing changed; "Approve anyway" with the second confirm
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "17,000",
                                                         "method": "KPay"})
    assert "Amount 17,000 ≠ order total 18,000" in r.text and "Approve anyway" in r.text
    assert order(db) == ("photo_received", None)
    client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "17000",
                                                     "method": "KPay", "confirmed": "1"})
    assert order(db) == ("paid", 1001)
    assert deliver(db) == ["✅ Order #1001 အတည်ပြုပြီးပါပြီ။\n• Stronger With You Intensely 5ml – 18,000 ကျပ်\n"
                           "စုစုပေါင်း 18,000 ကျပ် (ငွေရရှိပြီး)\nဖုန်း: 09777123456, 09444555666\n"
                           "လိပ်စာ: No. 12, Bahan\nပို့ခကို ပစ္စည်းရောက်မှ ပေးချေရပါမယ်။\nကျေးဇူးတင်ပါတယ်။"]
    assert "Payments <span" not in client.get("/").text

    # the next order reuses the transaction ID and the same image -> both warnings
    cid2 = waiting_for_payment(client, token, db, customer="92")
    photo(2, customer="92")
    check2 = scalar(db, "SELECT max(id) FROM payment_checks")
    client.get(f"/payments/{check2}")
    downloaded(db, tmp_path, monkeypatch, check2)
    r = client.post(f"/payments/{check2}/approve", data={"csrf": token, "transaction_id": "tx1", "amount": "18000"})
    assert "already used for order #1001" in r.text and "exact screenshot was sent before" in r.text
    client.post(f"/payments/{check2}/approve", data={"csrf": token, "transaction_id": "TX2", "amount": "18000",
                                                      "confirmed": "1"})
    assert order(db, "92") == ("paid", 1002) and cid2


def test_reject_and_not_a_payment(paying, db, tmp_path, monkeypatch):
    client, token, cid = paying
    photo(1)
    check = scalar(db, "SELECT id FROM payment_checks")
    client.get(f"/payments/{check}")
    downloaded(db, tmp_path, monkeypatch, check)
    r = client.post(f"/payments/{check}/reject", data={"csrf": token, "reason": "wrong_amount", "amount": ""})
    assert "Type the amount received" in r.text
    client.post(f"/payments/{check}/reject", data={"csrf": token, "reason": "wrong_amount", "amount": "15000"})
    assert order(db) == ("waiting_payment", None)
    assert deliver(db) == ["ကျန်ငွေ 3,000 ကျပ် ထပ်လွှဲပေးပါနော်။"]

    photo(2)  # a new screenshot: a new check
    check = scalar(db, "SELECT max(id) FROM payment_checks")
    assert order(db)[0] == "photo_received"
    client.post(f"/payments/{check}/not-payment", data={"csrf": token})
    assert order(db)[0] == "waiting_payment" and deliver(db) == []
    assert scalar(db, "SELECT decision FROM payment_checks WHERE id = :c", c=check) == "not_payment"


def test_several_photos(paying, db):
    client, token, cid = paying
    photo(1, grouped_id="77")
    photo(2, grouped_id="77")
    assert scalar(db, "SELECT decision || ':' || photo_count FROM payment_checks ORDER BY id LIMIT 1") == "several:2"
    assert order(db)[0] == "waiting_payment"
    check = scalar(db, "SELECT min(id) FROM payment_checks")
    page = client.get(f"/payments/{check}").text
    assert "Several photos (2)" in page and scalar(db, "SELECT count(*) FROM media_downloads") == 0  # no download
    assert "several photos — ask for one" in client.get("/").text
    client.post(f"/payments/{check}/ask-one", data={"csrf": token})
    assert deliver(db) == ["transaction id ပါတဲ့ screenshot တစ်ပုံတည်း ပို့ပေးပါနော်။"]
    photo(3)  # then one screenshot -> a normal check
    assert order(db)[0] == "photo_received"


def test_auto_mode_never_handles_payments(paying, db):
    client, token, cid = paying
    with SessionLocal.begin() as s:
        auto.set_enabled(s, True, None)
    photo(1)
    auto.run_once(datetime.now(UTC) + timedelta(seconds=30))
    assert order(db) == ("photo_received", None)
    assert scalar(db, "SELECT count(*) FROM outbox WHERE status = 'queued'") == 0


def test_photo_before_payment_info_is_not_a_payment(paying, db):
    photo(1, seconds_ago=600)  # sent before we asked for payment
    assert scalar(db, "SELECT count(*) FROM payment_checks") == 0 and order(db)[0] == "waiting_payment"
