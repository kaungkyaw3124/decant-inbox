"""One-tap price reply: when it is offered, queue with 10 s undo, done status, undo."""
import asyncio
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.listener import sender
from app.parser.worker import run_batch
from tests.test_messaging import FakeClient, add, customer_id, scalar
from tests.test_prices import STW, run_import, xlsx
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def button(html: str, message_id: int) -> str | None:
    m = re.search(rf'action="/messages/{message_id}/quick-price".*?name="expect" value="([^"]+)"', html, re.S)
    return m.group(1) if m else None


def msg_id(db, external: str) -> int:
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=external)


def setup_messages(db):
    run_import(xlsx(STW, ["Dior", "Sauvage Eau de Parfum", 100, 420000, None, 20000, None, "no"]))
    now = datetime.now(UTC)
    add(101, "stw intensely 5ml ဘယ်လောက်လဲ", customer="51", when=now)           # quick: size known
    add(102, "stw intensely ဘယ်လောက်လဲ", customer="52", when=now)                # quick: all sizes
    add(103, "stw intensely 3ml ဘယ်လောက်လဲ", customer="53", when=now)            # 3ml has no price
    add(104, "sauvage edp 5ml ရှိလား", customer="54", when=now)                   # out of stock
    add(105, "stw intensely 5ml ဝယ်ချင်လို့ပါ", customer="55", when=now)          # buy: quick too (until cart)
    run_batch()


def test_when_the_button_is_offered(client, db):  # noqa: F811
    log_in(client)
    setup_messages(db)
    page = client.get("/?intent=all").text
    for ext in ("101", "102", "105", "1"):  # 105 and 1 are buy messages: offered too (until cart)
        assert button(page, msg_id(db, ext)), ext
    for ext in ("103", "104", "3"):  # 3ml has no price, out of stock, unknown "aventus"
        assert button(page, msg_id(db, ext)) is None, ext
    assert 'title="မင်္ဂလာပါ။\nStronger With You Intensely 5ml က 18,000 ကျပ်ပါ။' in page  # full text on hover
    assert "မင်္ဂလာပါ။ · Stronger With You Intensely 5ml က 18,000" in page  # one-line preview
    detail = client.get(f"/messages/{msg_id(db, '102')}").text
    assert "Edit before send" in detail and "• Full 100ml – 380,000 ကျပ်" in detail


def test_one_tap_queue_undo_and_send(client, db):  # noqa: F811
    token = log_in(client)
    setup_messages(db)
    mid = msg_id(db, "101")
    expect = button(client.get("/").text, mid)

    r = client.post(f"/messages/{mid}/quick-price", data={"csrf": token, "expect": expect},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Sending in" in r.text and "Undo" in r.text and 'hx-trigger="every 3s"' in r.text
    with db.connect() as c:
        status, send_after, prev, kind = c.execute(text(
            "SELECT status, send_after - created_at, previous_review_status, reply_kind FROM outbox")).one()
        assert (status, prev, kind) == ("queued", "new", "price") and timedelta(seconds=9) < send_after <= timedelta(seconds=11)
        assert c.execute(text("SELECT status FROM message_reviews WHERE message_id = :m"), {"m": mid}).scalar() == "done"
        assert c.execute(text("SELECT action FROM audit_log")).scalar() == "outbox.quick_price"

    # the listener does not send before the 10 s are over
    fake = FakeClient()
    assert asyncio.run(sender.send_next(fake, sender.RateLimiter())) is False and fake.sent == []

    # second tap (other tab) is refused: a reply was just queued
    r = client.post(f"/messages/{mid}/quick-price", data={"csrf": token, "expect": expect})
    assert scalar(db, "SELECT count(*) FROM outbox") == 1

    oid = scalar(db, "SELECT id FROM outbox")
    r = client.post(f"/outbox/{oid}/undo", data={"csrf": token}, headers={"HX-Request": "true"})
    assert "💬 Reply price" in r.text  # offered again
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM outbox")).scalar() == "cancelled"
        assert c.execute(text("SELECT status FROM message_reviews WHERE message_id = :m"), {"m": mid}).scalar() == "new"

    # tap again, let the 10 s pass, the listener sends it; undo is now too late
    expect = button(client.get("/").text, mid)
    client.post(f"/messages/{mid}/quick-price", data={"csrf": token, "expect": expect})
    with db.begin() as c:
        c.execute(text("UPDATE outbox SET send_after = now() - interval '1 second' WHERE status = 'queued'"))
    assert asyncio.run(sender.send_next(fake, sender.RateLimiter())) is True
    assert fake.sent == [(51, "မင်္ဂလာပါ။\nStronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။")]
    oid = scalar(db, "SELECT id FROM outbox WHERE status = 'sent'")
    client.post(f"/outbox/{oid}/undo", data={"csrf": token})
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=oid) == "sent"
    assert "✓ price reply sent" in client.get("/?status=all").text


def test_changed_price_is_refused(client, db):  # noqa: F811
    token = log_in(client)
    setup_messages(db)
    mid = msg_id(db, "101")
    expect = button(client.get("/").text, mid)
    run_import(xlsx(["Emporio Armani", "Stronger With You Intensely", 19000], header=["brand", "name", "5ml"]))
    r = client.post(f"/messages/{mid}/quick-price", data={"csrf": token, "expect": expect})
    assert "the reply changed" in r.text
    assert scalar(db, "SELECT count(*) FROM outbox") == 0
    assert scalar(db, "SELECT count(*) FROM message_reviews") == 0


def test_recent_reply_and_low_confidence_hide_button(client, db):  # noqa: F811
    token = log_in(client)
    setup_messages(db)
    mid = msg_id(db, "102")
    cid = customer_id(db, "52")
    page = client.get(f"/chats/{cid}?compose=custom").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "text": "ok"})
    assert button(client.get("/").text, mid) is None  # an editor reply was queued < 60 s ago
    with db.begin() as c:
        c.execute(text("UPDATE outbox SET created_at = now() - interval '2 minutes'"))
        c.execute(text("UPDATE parse_results SET confidence = 0.3 WHERE message_id = :m"), {"m": mid})
    assert button(client.get("/").text, mid) is None  # low confidence
