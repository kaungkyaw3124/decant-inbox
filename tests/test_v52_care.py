"""docs/SPEC-v5.2-customer-care.md: profile totals (paid only), VIP suggestion, reorder list (window, 30-day cap,
opt-out, admin click only), feedback after delivery (once; happy / unhappy), staff can't export."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app import care
from app.core.db import SessionLocal
from app.models import Customer
from app.orders import auto, holding
from app.parser.worker import run_batch
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_v4_teaching import auto_on
from tests.test_web import client, log_in  # noqa: F401  (fixture)

NOW = datetime.now(UTC)


def order(db, customer: str, days_ago: float, total=18000, status="paid", test=False, size=5, qty=1, no=[3000]) -> int:
    """A paid (or other status) order with one STW Intensely decant."""
    if customer_id(db, customer) is None:
        add(9000 + int(customer), "hi", customer=customer, when=NOW - timedelta(days=60))
    no[0] += 1
    at = NOW - timedelta(days=days_ago)
    with db.begin() as c:
        oid = c.execute(text(
            "INSERT INTO orders (customer_id, status, phones, order_no, total_mmk, paid_at, delivered_at, is_test) "
            "VALUES (:c, :s, '{}', :n, :t, :p, :d, :x) RETURNING id"),
            {"c": customer_id(db, customer), "s": status, "n": no[0], "t": total, "p": at, "x": test,
             "d": at if status == "delivered" else None}).scalar()
        c.execute(text("INSERT INTO order_items (order_id, product_id, size_ml, is_full_bottle, quantity, unit_price_mmk) "
                       "VALUES (:o, (SELECT id FROM products WHERE name = 'Stronger With You Intensely'), :z, false, :q, "
                       ":u)"), {"o": oid, "z": size, "q": qty, "u": total // qty})
    return oid


def test_profile_totals_paid_only_and_vip_suggestion(shop, db):  # noqa: F811
    for days in (40, 30, 20, 10):
        order(db, "801", days)
    order(db, "801", 5, total=999999, test=True)  # a test order: not counted
    order(db, "801", 3, total=888888, status="cancelled")  # cancelled: not counted
    with SessionLocal() as s:
        p = care.profile(s, s.get(Customer, customer_id(db, "801")))
    assert (p.orders, p.spent, p.average, p.usual_size) == (4, 72000, 18000, 5)
    assert p.top == [("Stronger With You Intensely", 4)] and not p.vip_suggested
    order(db, "801", 2)
    with SessionLocal() as s:
        assert care.profile(s, s.get(Customer, customer_id(db, "801"))).vip_suggested  # 5 orders
    client, token = shop
    cid = customer_id(db, "801")
    page = client.get(f"/chats/{cid}").text
    assert 'id="profile"' in page and "90,000" in page and "Suggested: mark as VIP" in page
    client.post(f"/customers/{cid}/tags", data={"csrf": token, "tag": "VIP", "back": f"/chats/{cid}"})
    client.post(f"/customers/{cid}/notes", data={"csrf": token, "text": "likes sweet scents"})
    page = client.get(f"/customers/{cid}").text
    assert 'class="tag vip"' in page and "likes sweet scents" in page and "Suggested: mark as VIP" not in page
    rows = client.get("/customers?tag=VIP").text
    assert f'href="/customers/{cid}"' in rows
    assert client.get("/customers/export.csv").text.count("\n") == 2  # header + 1 customer


def test_reorder_window_cap_opt_out_and_admin_click(shop, db):  # noqa: F811
    client, token = shop
    order(db, "811", 30)  # in the window
    order(db, "812", 10)  # too recent
    order(db, "813", 30)
    add(1, "stop", customer="813")  # opted out by the customer
    order(db, "814", 30)
    with db.begin() as c:
        c.execute(text("UPDATE customers SET ignored = true WHERE external_user_id = '814'"))
    with SessionLocal() as s:
        rows = care.reorder_list(s)
    assert [r["c"].external_user_id for r in rows] == ["811"]
    assert rows[0]["text"] == "Stronger With You Intensely 5ml ကုန်ခါနီးပြီလား? ထပ်ယူချင်ရင် ပြောပါနော်။"
    page = client.get("/customers/reorder").text
    assert 'action="/customers/' + str(customer_id(db, "811")) + '/reorder"' in page
    assert scalar(db, "SELECT count(*) FROM outbox") == 0  # nothing is sent without a click
    client.post(f"/customers/{customer_id(db, '811')}/reorder", data={"csrf": token, "text": "SWY ထပ်ယူမလား?"})
    assert scalar(db, "SELECT text FROM outbox") == "SWY ထပ်ယူမလား?"
    client.post(f"/customers/{customer_id(db, '811')}/reorder", data={"csrf": token, "text": "again"})
    assert scalar(db, "SELECT count(*) FROM outbox") == 1  # max 1 per 30 days
    client.post(f"/customers/{customer_id(db, '813')}/reorder", data={"csrf": token, "text": "hello"})
    assert scalar(db, "SELECT count(*) FROM outbox") == 1  # opted out: refused
    with SessionLocal() as s:
        assert care.reorder_list(s) == []


def test_feedback_once_happy_and_unhappy(shop, db):  # noqa: F811
    client, token = shop
    auto_on(db)
    happy = order(db, "821", 3, status="delivered")
    unhappy = order(db, "822", 2.5, status="delivered")
    order(db, "823", 1, status="delivered")  # too early
    with SessionLocal.begin() as s:
        assert care.ask_feedback(s) == 0  # off by default
        care.save_settings(s, {"feedback_on": True}, None)
    with SessionLocal.begin() as s:
        assert care.ask_feedback(s) == 2
    with SessionLocal.begin() as s:
        assert care.ask_feedback(s) == 0  # once per order
    assert scalar(db, "SELECT count(*) FROM outbox WHERE text LIKE 'Order #%အဆင်ပြေရဲ့လား%'") == 2
    with db.begin() as c:
        c.execute(text("UPDATE order_feedback SET asked_at = now() - interval '1 hour'"))
        c.execute(text("UPDATE outbox SET created_at = now() - interval '1 hour', status = 'sent'"))  # asked earlier
    now = datetime.now(UTC)
    add(11, "👍", customer="821", when=now - timedelta(seconds=2))
    add(12, "👎", customer="822", when=now - timedelta(seconds=2))
    run_batch()
    auto.run_once(now)
    assert scalar(db, "SELECT answer FROM order_feedback WHERE order_id = :o", o=happy) == "good"
    assert scalar(db, "SELECT answer FROM order_feedback WHERE order_id = :o", o=unhappy) == "bad"
    assert scalar(db, "SELECT count(*) FROM outbox WHERE text LIKE 'ကျေးဇူးတင်ပါတယ်ရှင့်%' AND customer_id = :c",
                  c=customer_id(db, "821")) == 1
    assert holding.run_once(now) == {"held": 1}  # the 👎: "please wait" at once + Needs you
    assert scalar(db, "SELECT customer_id FROM outbox WHERE reply_kind = 'holding'") == customer_id(db, "822")
    assert f'id="waiting-' in client.get("/").text
    page = client.get("/orders?tab=delivered").text
    assert "/feedback-now" in page
    with SessionLocal.begin() as s:
        assert care.ask_feedback(s, force_order=happy) == 0  # asked already


def test_staff_sees_customers_but_cannot_export(shop, db):  # noqa: F811
    from tests.test_v4_roles import staff_client

    staff, token = staff_client(db)
    assert staff.get("/customers").status_code == 200 and staff.get("/customers/reorder").status_code == 200
    assert staff.get("/customers/export.csv").status_code == 403
    assert staff.post("/customers/care-settings", data={"csrf": token, "feedback_on": "1"}).status_code == 403


def test_reorder_list_counts_a_test_accounts_test_orders(shop, db):  # noqa: F811
    order(db, "831", 30, test=True)
    with SessionLocal() as s:
        assert care.reorder_list(s) == []  # a normal customer's test order: no
    with db.begin() as c:
        c.execute(text("UPDATE customers SET is_tester = true WHERE external_user_id = '831'"))
    with SessionLocal() as s:
        assert [r["c"].external_user_id for r in care.reorder_list(s)] == ["831"]
        assert care.profile(s, s.get(Customer, customer_id(db, "831"))).orders == 0  # totals: still not counted
