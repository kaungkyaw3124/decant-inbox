"""Step 4c: auto mode (same code as the one-tap buttons, without the tap), its safety
rules, unknown-item resolution, and the monitoring screen."""
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.orders import auto
from app.parser.worker import run_batch
from tests.test_cart import deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)

NOW = datetime.now(UTC)
T0 = NOW - timedelta(hours=1)


def switch_on(db, since=T0):
    with SessionLocal.begin() as s:
        auto.set_enabled(s, True, None)
    with db.begin() as c:
        c.execute(text("UPDATE app_settings SET value = jsonb_set(value, '{since}', to_jsonb(CAST(:s AS text))) "
                       "WHERE key = 'auto_reply'"), {"s": since.isoformat()})


def say(n: int, body: str, customer: str = "91", minutes: float | None = None) -> None:
    add(2000 + n, body, customer=customer, when=T0 + timedelta(minutes=minutes if minutes is not None else n))
    run_batch()


def msg(db, n: int) -> int:
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(2000 + n))


def outbox(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text("SELECT text, status, created_by, send_after - created_at FROM outbox ORDER BY id")))


def runs(db) -> dict[int, tuple]:
    with db.connect() as c:
        return {m: (s, r) for m, s, r in c.execute(text("SELECT message_id, status, reason FROM auto_runs"))}


def test_off_by_default(shop, db):
    client, _ = shop
    assert "Auto-reply: <b>OFF</b>" in client.get("/").text
    switch_on(db)
    with SessionLocal.begin() as s:
        auto.set_enabled(s, False, None)
    say(1, "stw intensely 5ml ဘယ်လောက်လဲ")
    assert auto.run_once() == {} and outbox(db) == []


def test_auto_reply_after_quiet_once_per_message(shop, db):
    client, token = shop
    client.post("/auto-reply", data={"csrf": token, "on": "1"})
    assert "Auto-reply: <b>ON</b>" in client.get("/").text
    now = datetime.now(UTC)
    add(3001, "stw intensely 5ml ဘယ်လောက်လဲ", customer="91", when=now)
    run_batch()
    assert auto.run_once(now + timedelta(seconds=5)) == {}  # customer may still be typing
    assert auto.run_once(now + timedelta(seconds=16)) == {"replied": 1}
    (body, status, created_by, delay), = outbox(db)
    assert body.startswith("မင်္ဂလာပါ။\nStronger With You Intensely 5ml က 18,000 ကျပ်ပါ။")
    assert status == "queued" and created_by is None and timedelta(seconds=8) <= delay <= timedelta(seconds=20)
    assert auto.run_once(now + timedelta(seconds=60)) == {} and len(outbox(db)) == 1  # one reply per message
    with db.connect() as c:
        assert c.execute(text("SELECT user_id, details->>'actor' FROM audit_log WHERE action = 'auto.price'")).one() \
            == (None, "auto")
    page = client.get("/").text
    assert "🤖 Handled automatically (last 24 h): 1" in page and "price reply" in page
    deliver(db)
    assert "Sent by auto-reply" in client.get(f"/chats/{customer_id(db, '91')}").text


def test_whole_order_flow_automatic(shop, db):
    switch_on(db)
    say(1, "stw intensely 5ml, sauvage edp 10ml ယူပါမယ်")
    auto.run_once()
    say(2, "ok")
    auto.run_once()  # waits: the cart list is still in the outbox
    sent = deliver(db)
    auto.run_once()
    sent += deliver(db)
    say(3, "09 777 123 456")
    auto.run_once()
    sent += deliver(db)
    say(4, "အမှတ် ၁၂, ဗဟန်း ကိုပို့ပေးပါ")
    auto.run_once()
    sent += deliver(db)
    assert [s.splitlines()[-1] for s in sent] == [
        "စုစုပေါင်း 56,000 ကျပ်ပါ။ အဆင်ပြေရင် confirm လုပ်ပေးပါနော်။",
        "ဆက်သွယ်ရန် ဖုန်းနံပါတ် ပို့ပေးပါနော်။",
        "ဖုန်းနံပါတ် 09777123456 ရပါပြီ။ ပို့ပေးရမယ့် လိပ်စာ ပို့ပေးပါနော်။",
        "ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။",
    ]
    with db.connect() as c:
        assert c.execute(text("SELECT status, address, phones FROM orders")).one() == \
            ("waiting_payment", "အမှတ် 12, ဗဟန်း", ["09777123456"])
        assert c.execute(text("SELECT count(*) FROM quick_actions WHERE auto")).scalar() == 4  # one per message


def test_safety_rules(shop, db, monkeypatch):
    client, token = shop
    switch_on(db)
    say(0, "stw intensely 5ml ဘယ်လောက်လဲ", customer="70", minutes=-5)  # before the switch: never touched
    say(1, "stw intensely 5ml ဘယ်လောက်လဲ", customer="71")
    say(2, "stw intensely 5ml ဘယ်လောက်လဲ", customer="72")
    say(3, "stronger with you intensly 5ml ဘယ်လောက်လဲ", customer="73")  # typo = fuzzy match
    say(4, "ကျေးဇူးပါ", customer="74")
    with db.begin() as c:
        c.execute(text("UPDATE customers SET ignored = true WHERE external_user_id = '71'"))
        c.execute(text("UPDATE customers SET auto_reply_off = true WHERE external_user_id = '72'"))
    auto.run_once()
    assert outbox(db) == []
    r = runs(db)
    assert msg(db, 0) not in r
    assert r[msg(db, 1)] == ("skipped", "ignored customer")
    assert r[msg(db, 2)] == ("skipped", "auto-reply off for this customer")
    assert r[msg(db, 3)] == ("skipped", "product not named exactly")
    assert r[msg(db, 4)] == ("skipped", "intent other")

    # owner replies by hand -> paused 2 h for that chat; Resume auto -> automatic again
    say(5, "stw intensely 5ml ဘယ်လောက်လဲ", customer="75")
    add(2006, "18,000 ပါရှင့်", direction="out", customer="75", when=T0 + timedelta(minutes=6))
    say(7, "sauvage edp 10ml ဘယ်လောက်လဲ", customer="75")
    auto.run_once()
    r = runs(db)
    assert r[msg(db, 5)] == ("skipped", "already answered")
    assert r[msg(db, 7)] == ("skipped", "paused: owner is replying by hand")
    cid = customer_id(db, "75")
    assert "Paused — you're replying by hand" in client.get(f"/chats/{cid}").text
    assert "new message while paused" in client.get("/").text
    client.post(f"/customers/{cid}/resume-auto", data={"csrf": token})
    add(2008, "ysl y edp ဘယ်လောက်လဲ", customer="75", when=datetime.now(UTC) - timedelta(seconds=20))
    run_batch()
    auto.run_once()
    assert len(outbox(db)) == 0  # Y is out of stock: no certain reply...
    assert runs(db)[msg(db, 8)] == ("skipped", "no certain reply")

    # daily limit -> one-tap again
    monkeypatch.setattr(auto, "DAILY_CAP", 0)
    say(9, "sauvage edp 10ml ဘယ်လောက်လဲ", customer="76")
    auto.run_once()
    assert runs(db)[msg(db, 9)][1] == "daily limit of 0 auto replies"
    assert "💬 Reply price" in client.get("/?intent=all").text


def test_unknown_items_need_you_then_continue(shop, db):
    client, token = shop
    switch_on(db)
    say(1, "stw intensely 5ml, hawas ice 10ml ဘယ်လောက်လဲ", customer="81")
    say(2, "hawas ice 10ml ဘယ်လောက်လဲ", customer="82")
    say(3, "aqua ice 5ml ယူမယ်", customer="83")
    auto.run_once()
    assert outbox(db) == [] and runs(db) == {}  # waiting for the admin, not skipped
    page = client.get("/").text
    # 4 = these 3 + the client fixture's "aventus 10ml ရှိလား" (also not in the small catalog)
    assert "🟡 Needs you (4)" in page and "❓ hawas ice" in page and "❓ aqua ice" in page

    # 1. we don't have it -> price reply for the rest + "we don't have" line
    detail = client.get(f"/messages/{msg(db, 1)}").text
    assert "Not in your product list" in detail and "Save as alias" in detail
    client.post(f"/messages/{msg(db, 1)}/unknown/1/not-stocked", data={"csrf": token})
    # 2. new product with the asked price -> product + price + alias
    client.post(f"/messages/{msg(db, 2)}/unknown/0/new", data={
        "csrf": token, "brand": "Rasasi", "name": "Hawas Ice", "asked_price": "25,000", "p5": "13000",
        "full_size_ml": "100", "in_stock": "1"})
    # 3. it's in my list -> learned alias
    sauvage = scalar(db, "SELECT id FROM products WHERE name = 'Sauvage Eau de Parfum'")
    client.post(f"/messages/{msg(db, 3)}/unknown/0/map", data={"csrf": token, "product_id": str(sauvage)})
    assert scalar(db, "SELECT source FROM product_aliases WHERE normalized_alias = 'aqua ice'") == "learned"
    assert "🟡 Needs you (1)" in client.get("/").text  # only the fixture's aventus left

    auto.run_once()
    sent = sorted(deliver(db))
    assert sent == sorted([
        "မင်္ဂလာပါ။\nStronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။\n"
        "hawas ice ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။",
        "မင်္ဂလာပါ။\nHawas Ice 10ml က 25,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။",
        "မင်္ဂလာပါ။\n• Sauvage Eau de Parfum 5ml – 20,000 ကျပ်\nစုစုပေါင်း 20,000 ကျပ်ပါ။ အဆင်ပြေရင် confirm လုပ်ပေးပါနော်။",
    ])
    with db.connect() as c:
        assert c.execute(text("SELECT resolution, count(*) FROM unknown_requests GROUP BY 1 ORDER BY 1")).all() == \
            [("mapped", 1), ("new_product", 1), ("not_stocked", 1)]
    # the learned alias works for the next customer right away
    say(4, "aqua ice 10ml ဘယ်လောက်လဲ", customer="84")
    auto.run_once()
    assert deliver(db) == ["မင်္ဂလာပါ။\nSauvage Eau de Parfum 10ml က 38,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"]


def test_cancel_auto_reply_from_chat(shop, db):
    client, token = shop
    switch_on(db)
    say(1, "stw intensely 5ml ယူမယ်")
    auto.run_once()
    cid = customer_id(db, "91")
    page = client.get(f"/chats/{cid}").text
    assert "🤖" in page and "Sending in" in page
    oid = scalar(db, "SELECT id FROM outbox")
    client.post(f"/chats/{cid}/outbox/{oid}/cancel", data={"csrf": token})
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM outbox")).scalar() == "cancelled"
        assert c.execute(text("SELECT count(*) FROM order_items WHERE removed_at IS NULL")).scalar() == 0
        assert c.execute(text("SELECT undone_at IS NOT NULL FROM quick_actions")).scalar() is True
    auto.run_once()
    assert len(outbox(db)) == 1  # cancelled by the admin: auto does not try again
    assert re.search(r"Auto-reply: <b>(ON|OFF)</b>", page)
