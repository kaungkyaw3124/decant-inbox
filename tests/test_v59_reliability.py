"""docs/SPEC-v5.9-reliability-under-load.md: the small pieces the chaos tests (tests/chaos/) do not pin down."""
import asyncio
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from telethon import errors

from app.alerts import service as alerts
from app.core.db import SessionLocal
from app.listener import sender
from app.models import Outbox
from app.parser import worker
from tests.test_messaging import FakeClient, add, customer_id, queue, scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def test_fair_order_one_customers_burst_does_not_hold_up_another(db):
    add(1, "hi", customer="41")
    add(2, "hi", customer="42")
    burst = [queue(db, f"reply {i}", customer="41", key=f"a{i}") for i in range(3)]
    other = queue(db, "for 42", customer="42", key="b")
    with SessionLocal.begin() as s:  # customer 41 got a message a moment ago
        s.add(Outbox(customer_id=customer_id(db, "41"), text="earlier", reply_kind="custom", status="sent",
                     idempotency_key="old", sent_at=datetime.now(UTC)))
    order = [sender.claim_next()[0] for _ in range(4)]
    assert order == [other, *burst]  # 42 waited longest; 41's replies in their own order


def test_refused_row_does_not_delay_the_next(db):
    add(1, "hi", customer="41")
    add(2, "our message only", customer="42", direction="out")
    bad = queue(db, "never asked", customer="42", key="bad")
    good = queue(db, "ok", customer="41", key="good")
    assert sender.claim_next()[0] == good  # the refused row is skipped in the same call
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=bad) == "failed"


def test_transient_error_retries_then_fails_permanent_fails_at_once(db):
    add(1, "hi")
    oid = queue(db)
    for n in range(len(sender.RETRY_DELAYS)):
        with SessionLocal.begin() as s:
            s.execute(text("UPDATE outbox SET send_after = now() WHERE id = :i"), {"i": oid})
        asyncio.run(sender.send_next(FakeClient(fail=TimeoutError("slow")), sender.RateLimiter()))
        status, after = db.connect().execute(text("SELECT status, send_after FROM outbox WHERE id = :i"),
                                             {"i": oid}).one()
        assert status == "queued" and after > datetime.now(UTC) + timedelta(seconds=sender.RETRY_DELAYS[n] - 2)
    with SessionLocal.begin() as s:
        s.execute(text("UPDATE outbox SET send_after = now() WHERE id = :i"), {"i": oid})
    asyncio.run(sender.send_next(FakeClient(fail=ConnectionError("down")), sender.RateLimiter()))
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=oid) == "failed"
    blocked = queue(db, "again", key="k2")
    asyncio.run(sender.send_next(FakeClient(fail=errors.UserIsBlockedError(None)), sender.RateLimiter()))
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=blocked) == "failed"


def test_stuck_row_found_already_saved_is_marked_sent_not_resent(db):
    add(1, "hi")
    oid = queue(db, "STW 5ml က 18,000 ကျပ်ပါ။")
    with SessionLocal.begin() as s:
        s.execute(text("UPDATE outbox SET status = 'sending', claimed_at = now() - interval '5 minutes' "
                       "WHERE id = :i"), {"i": oid})
    add(77, "STW 5ml က 18,000 ကျပ်ပါ။", direction="out", when=datetime.now(UTC) - timedelta(minutes=4))
    client = FakeClient()
    assert asyncio.run(sender.recover_stuck(client)) == {"sent": 1}
    assert client.sent == []
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=oid) == "sent"


def test_stuck_row_requeued_once_then_failed(db):
    add(1, "hi")
    oid = queue(db, "hello")

    class Offline(FakeClient):
        async def get_messages(self, entity, limit=20):
            return []

    def stick():
        with SessionLocal.begin() as s:
            s.execute(text("UPDATE outbox SET status = 'sending', claimed_at = now() - interval '5 minutes' "
                           "WHERE id = :i"), {"i": oid})

    stick()
    assert asyncio.run(sender.recover_stuck(Offline())) == {"requeued": 1}
    stick()
    assert asyncio.run(sender.recover_stuck(Offline())) == {"failed": 1}  # never a second blind resend
    old = queue(db, "an hour ago", key="old")
    with SessionLocal.begin() as s:  # stuck long ago (e.g. before a long outage): stale, never sent this late
        s.execute(text("UPDATE outbox SET status = 'sending', claimed_at = now() - interval '1 hour' WHERE id = :i"),
                  {"i": old})
    assert asyncio.run(sender.recover_stuck(Offline())) == {"failed": 1}
    assert scalar(db, "SELECT error FROM outbox WHERE id = :i", i=old).startswith("stuck while sending for too long")


def test_stuck_row_left_alone_when_telegram_cannot_tell(db):
    add(1, "hi")
    oid = queue(db, "hello")
    with SessionLocal.begin() as s:
        s.execute(text("UPDATE outbox SET status = 'sending', claimed_at = now() - interval '5 minutes' "
                       "WHERE id = :i"), {"i": oid})

    class Broken(FakeClient):
        async def get_messages(self, entity, limit=20):
            raise ConnectionError("offline")

    assert asyncio.run(sender.recover_stuck(Broken())) == {"unknown": 1}
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=oid) == "sending"
    with SessionLocal() as s:  # the alert service reports it (reply queue: stuck)
        found = alerts.problems(s, datetime.now(UTC), preview=False)
    assert found["check:reply queue"][0] == "queue" and "stuck" in found["check:reply queue"][1]


def test_health_shows_reply_queue_and_pool(client):  # noqa: F811
    log_in(client)
    page = client.get("/health").text
    assert "reply queue" in page.lower() and "0 waiting" in page
    assert 'id="db-pool"' in page
    body = client.get("/healthz").text
    assert "reply queue: ok" in body


def test_queue_and_failed_alert_types_in_settings(client, db):  # noqa: F811
    assert alerts.TYPES["send_failed"] == "Reply failed" and alerts.TYPES["queue"] == "Reply queue long"
    log_in(client)
    page = client.get("/settings").text
    assert "Reply failed" in page and "Reply queue long" in page
    with SessionLocal.begin() as s:  # an old queued reply: the queue alert, then its "resolved" line
        s.execute(text("UPDATE outbox SET status = 'sent'"))
    cid = customer_id(db, "42")
    with SessionLocal.begin() as s:
        s.add(Outbox(customer_id=cid, text="late", reply_kind="custom", idempotency_key="late",
                     send_after=datetime.now(UTC) - timedelta(minutes=3)))
    got = []
    alerts.tick(send=lambda body, button=None: got.append(body))
    assert any("reply queue" in g for g in got), got
    with SessionLocal.begin() as s:
        s.execute(text("UPDATE outbox SET status = 'failed', error = 'UserIsBlockedError' WHERE idempotency_key = 'late'"))
    got = []
    alerts.tick(send=lambda body, button=None: got.append(body))
    assert any(g.startswith("✅ resolved: reply queue") for g in got), got
    assert any("Reply to" in g and "failed" in g for g in got), got


def test_max_three_live_streams_per_user(client, monkeypatch):  # noqa: F811
    from app.web import live

    log_in(client)
    now = time.monotonic()
    monkeypatch.setattr(live.hub, "streams", {1: {object(): now, object(): now, object(): now}})  # owner = user 1
    assert client.get("/events").status_code == 204  # a 4th tab polls instead
    live.hub.streams[1] = {object(): now - live.STREAM_SECONDS - 60}  # a stream that never closed stops counting
    assert live.hub.open_streams(1) == 0


def test_failed_parse_is_retried_after_ten_minutes(db, monkeypatch):
    add(1, "stw intensely 5ml ရှိလား")
    calls = []

    def boom(*args):
        calls.append(1)
        raise RuntimeError("bad row")

    monkeypatch.setattr(worker, "parse_message", boom)
    worker._failed.clear()
    assert worker.run_batch() == 0 and len(calls) == 1
    assert worker.run_batch() == 0 and len(calls) == 1  # skipped meanwhile: one bad row never blocks the queue
    mid = next(iter(worker._failed))
    worker._failed[mid] -= worker.RETRY_FAILED + 1  # ten minutes later
    monkeypatch.undo()
    assert worker.run_batch() == 1
    worker._failed.clear()


def test_pool_full_is_counted_on_health(client, monkeypatch):  # noqa: F811
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.web import health
    from app.web.main import app

    @app.get("/__pool_test")
    def full():
        raise PoolTimeout("QueuePool limit reached")

    before = health.pool_timeouts
    try:
        assert client.get("/__pool_test").status_code == 503
        assert health.pool_timeouts == before + 1
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__pool_test"]
