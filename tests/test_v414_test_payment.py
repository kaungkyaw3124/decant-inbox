"""docs/SPEC-v4.14-test-payment-code.md acceptance tests C1-C10 (C11 = the full suite)."""
import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.ai import privacy, service
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.orders import sales, testpay
from app.parser import worker
from tests.test_cart import deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_payments import downloaded, order, photo, waiting_for_payment
from tests.test_v46_ai import ai, mode  # noqa: F401  (fixture)
from tests.test_v4_teaching import staff_client
from tests.test_web import client, log_in  # noqa: F401  (fixture)

CODE = "Test2468x"


@pytest.fixture
def code(monkeypatch):
    monkeypatch.setattr(get_settings(), "test_pay_code", SecretStr(CODE))
    return CODE


@pytest.fixture
def tester(shop, db, code):
    """Customer 91 waiting for payment, marked as a test account by the owner."""
    client, token = shop
    cid = waiting_for_payment(client, token, db)
    client.post(f"/customers/{cid}/tester", data={"csrf": token, "on": "1"})
    return client, token, cid


def send(n: int, body: str, customer="91") -> None:
    """A customer message, then what the parser worker does with it."""
    add(700 + n, body, customer=customer)
    worker.run_batch()
    worker.scan_payments()


def checks(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text("SELECT decision, is_test, transaction_id FROM payment_checks ORDER BY id")))


def audits(db, action: str) -> list[dict]:
    with db.connect() as c:
        return [d for d, in c.execute(text("SELECT details FROM audit_log WHERE action = :a ORDER BY id"), {"a": action})]


def test_c1_tester_code_is_a_test_screenshot(tester, db):
    client, token, cid = tester
    assert audits(db, "customer.tester") == [{"customer_id": cid, "is_tester": True}]
    send(1, f"  {CODE} ")
    assert checks(db) == [("pending", True, None)]
    assert order(db) == ("photo_received", None) and scalar(db, "SELECT is_test FROM orders") is True
    assert deliver(db) == []  # like a real screenshot: no reply until a person decides
    mid = scalar(db, "SELECT id FROM messages WHERE external_message_id = '701'")
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=mid) == "done"
    assert "🧪 TEST PAYMENT — no money" in client.get("/payments").text

    # the code again: no second check (one per message, nothing waiting for payment now) -> Needs you note
    send(2, CODE)
    assert len(checks(db)) == 1 and len(audits(db, "test_code.no_order")) == 1
    assert "🧪 test code but no order waiting for payment" in client.get("/").text


def test_c2_non_tester_code_is_an_ordinary_message(shop, db, code):
    client, token = shop
    cid = waiting_for_payment(client, token, db, customer="92")
    send(1, CODE, customer="92")
    assert checks(db) == [] and order(db, "92") == ("waiting_payment", None)
    mid = scalar(db, "SELECT id FROM messages WHERE external_message_id = '701'")
    assert scalar(db, "SELECT count(*) FROM parse_results WHERE message_id = :m", m=mid) == 1  # normal parsing
    assert audits(db, "test_code.non_tester") == [{"message_id": mid, "customer_id": cid}]
    assert deliver(db) == []
    assert "⚠️ someone sent the test payment code" in client.get("/").text
    worker.scan_payments()
    assert len(audits(db, "test_code.non_tester")) == 1  # once per message


def test_c3_empty_or_weak_code_is_off(tester, db, monkeypatch):
    for value in ("", "short1", "has space1"):
        monkeypatch.setattr(get_settings(), "test_pay_code", SecretStr(value) if value else None)
        assert testpay.code() is None and not testpay.is_code(value)
    monkeypatch.setattr(get_settings(), "test_pay_code", None)
    send(1, CODE)
    assert checks(db) == [] and order(db) == ("waiting_payment", None)
    assert scalar(db, "SELECT count(*) FROM audit_log WHERE action LIKE 'test_code.%'") == 0


@pytest.mark.parametrize("body", [CODE + "1", f"my code is {CODE}", CODE.lower(), CODE.upper()])
def test_c4_only_the_exact_code(tester, db, body):
    send(1, body)
    assert checks(db) == [] and order(db) == ("waiting_payment", None)


def test_c5_burmese_digits(tester, db):
    send(1, "Test၂၄၆၈x")
    assert checks(db) == [("pending", True, None)]


def test_c6_approve_test_check(tester, db, tmp_path, monkeypatch):
    client, token, cid = tester
    send(1, CODE)
    check = scalar(db, "SELECT id FROM payment_checks")
    page = client.get(f"/payments/{check}").text
    assert "🧪 TEST PAYMENT — no money" in page and 'name="transaction_id"' not in page and f"TEST-{check}" in page
    assert scalar(db, "SELECT count(*) FROM media_downloads") == 0  # nothing to download
    r = client.post(f"/payments/{check}/approve", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    assert checks(db) == [("approved", True, f"TEST-{check}")]
    assert order(db) == ("paid", 1)
    sent = deliver(db)
    assert len(sent) == 1 and sent[0].startswith("✅ Order #T1 အတည်ပြုပြီးပါပြီ။")
    assert "#T1" in client.get("/orders").text or "#T1" in client.get("/orders?show_test=1").text

    # a real order afterwards still gets #1001
    waiting_for_payment(client, token, db, customer="92")
    photo(1, customer="92")
    real = scalar(db, "SELECT max(id) FROM payment_checks")
    client.get(f"/payments/{real}")
    downloaded(db, tmp_path, monkeypatch, real)
    client.post(f"/payments/{real}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "18000"})
    assert order(db, "92") == ("paid", 1001)


def test_c7_auto_approve_only_test_checks(tester, db):
    client, token, cid = tester
    client.post("/settings/test-payments", data={"csrf": token, "auto_approve": "1"})
    assert 'name="auto_approve" value="1" checked' in client.get("/settings").text
    waiting_for_payment(client, token, db, customer="92")
    photo(1, customer="92")  # a real check
    send(1, CODE)
    with SessionLocal.begin() as s:
        assert testpay.run_auto_approve(s) == 0  # not 5 s yet
    with SessionLocal.begin() as s:
        assert testpay.run_auto_approve(s, datetime.now(UTC) + timedelta(seconds=6)) == 1
    assert order(db) == ("paid", 1)
    assert scalar(db, "SELECT decided_by FROM payment_checks WHERE is_test") is None  # the system
    assert any(t.startswith("✅ Order #T1") for t in deliver(db))
    with SessionLocal.begin() as s:
        assert testpay.run_auto_approve(s, datetime.now(UTC) + timedelta(hours=1)) == 0
    assert order(db, "92") == ("photo_received", None)


def test_c8_numbers_exclude_test_orders_and_clear(tester, db):
    client, token, cid = tester
    send(1, CODE)
    check = scalar(db, "SELECT id FROM payment_checks")
    client.post(f"/payments/{check}/approve", data={"csrf": token})
    deliver(db)
    today = date.today()
    with SessionLocal() as s:
        assert sales.report(s, "today", today - timedelta(days=1), today + timedelta(days=1)).total.orders == set()
    assert "#T1" not in client.get("/orders?tab=all").text
    page = client.get("/orders?tab=all&show_test=1").text
    assert "#T1" in page and "🧪" in page

    # a delivered test order stays; the paid one is cancelled ("confirm twice": button, then "I'm sure")
    with db.begin() as c:
        c.execute(text("INSERT INTO orders (customer_id, status, order_no, is_test, paid_at, delivered_at) "
                       "VALUES (:c, 'delivered', 99, true, now(), now())"), {"c": cid})
    r = client.post("/orders/clear-test", data={"csrf": token}, follow_redirects=False)
    assert "confirm_clear=1" in r.headers["location"] and order(db)[0] != "cancelled"
    assert "Yes, I'm sure" in client.get(r.headers["location"]).text
    client.post("/orders/clear-test", data={"csrf": token, "sure": "1"})
    with db.connect() as c:
        rows = list(c.execute(text("SELECT order_no, status, cancel_note FROM orders WHERE is_test ORDER BY order_no")))
    assert rows == [(1, "cancelled", testpay.CLEARED), (99, "delivered", None)]
    assert deliver(db) == []  # nothing sent
    page = client.get("/orders?tab=all&show_test=1").text
    assert "#T1" not in page and "#T99" in page


def test_c9_code_never_leaks(tester, db, caplog, ai):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    client, token, cid = tester
    mode("shadow")
    send(1, CODE)
    check = scalar(db, "SELECT id FROM payment_checks")
    client.post(f"/payments/{check}/approve", data={"csrf": token})
    deliver(db)
    # a non-tester sends it too, then something the AI looks at (with the code in its history)
    waiting_for_payment(client, token, db, customer="92")
    send(2, CODE, customer="92")
    send(3, f"{CODE} ဒါလေး ရလား", customer="92")
    send(4, "ဟိုဟာလေး ရလား", customer="92")
    service.run_once()
    assert ai.requests and all(CODE.lower() not in i.lower() and CODE.lower() not in u.lower()
                               for i, u in ai.requests)
    assert CODE.lower() not in privacy.mask(f"code {CODE}").lower()
    pages = [client.get(p).text for p in ("/", "/chats", f"/chats/{cid}", f"/chats/{customer_id(db, '92')}",
                                           f"/payments/{check}", "/settings", "/?q=" + CODE, "/ai",
                                           "/orders?tab=all&show_test=1")]
    with db.connect() as c:
        ids = list(c.execute(text("SELECT id FROM messages")).scalars())
    pages += [client.get(f"/messages/{m}").text for m in ids]
    assert all(CODE.lower() not in p.lower() for p in pages)
    assert "🧪 test payment code" in client.get(f"/chats/{cid}").text
    with db.connect() as c:
        stored = [str(v) for v, in c.execute(text("SELECT details::text FROM audit_log UNION ALL "
                                                   "SELECT coalesce(result_json::text, '') FROM ai_calls UNION ALL "
                                                   "SELECT text FROM outbox"))]
    assert all(CODE.lower() not in v.lower() for v in stored)
    assert CODE.lower() not in caplog.text.lower()


def test_c10_staff_cannot_touch_test_settings(tester, db):
    client, token, cid = tester
    staff, staff_token = staff_client(db)
    assert staff.post(f"/customers/{cid}/tester", data={"csrf": staff_token, "on": "0"}).status_code == 403
    assert staff.get("/settings").status_code == 403
    assert staff.post("/settings/test-payments", data={"csrf": staff_token, "auto_approve": "1"}).status_code == 403
    assert staff.post("/orders/clear-test", data={"csrf": staff_token, "sure": "1"}).status_code == 403
    page = staff.get(f"/chats/{cid}").text
    assert "Test account" not in page and "/tester" not in page
    assert scalar(db, "SELECT is_tester FROM customers WHERE id = :c", c=cid) is True
