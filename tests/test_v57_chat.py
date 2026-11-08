"""docs/SPEC-v5.7-date-filter-and-light-chat.md B / D2-D4: a chat opens with the last 20 messages, older ones come 20
at a time (no gap, no double), and the open chat's poll answers 204 when nothing changed, else only what is new."""
import re
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.db import SessionLocal
from scripts.perf_check import LONG_CHAT, seed_long_chat
from tests.test_messaging import scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def long_chat(db) -> int:
    with SessionLocal.begin() as s:
        return seed_long_chat(s, "long-test")


def bubble_ids(html: str) -> list[int]:
    return [int(i) for i in re.findall(r'class="bubble [^"]*" id="m(\d+)"', html)]


def poll_vals(html: str) -> tuple[int, str]:
    after, v = re.search(r'hx-vals=\'\{"after": (\d+), "v": "(\w+)"\}\'', html).groups()
    return int(after), v


def test_d2_opens_with_the_last_20_messages(client, db):  # noqa: F811
    log_in(client)
    cid = long_chat(db)
    page = client.get(f"/chats/{cid}").text
    ids = bubble_ids(page)
    newest20 = [r for r, in db.connect().execute(text(
        "SELECT id FROM messages WHERE customer_id = :c ORDER BY received_at DESC, id DESC LIMIT 20"), {"c": cid})]
    assert ids == list(reversed(newest20))
    assert f'hx-get="/chats/{cid}/thread?before={ids[0]}"' in page and "Load older messages" in page
    assert 'hx-trigger="every 4s"' in page and 'id="new-pill"' in page
    assert page.count('class="day-sep"') == len(set(re.findall(r'data-day="([\d-]+)"', page)))  # one per day


def test_d3_older_pages_cover_everything_once_and_end_cleanly(client, db):  # noqa: F811
    log_in(client)
    cid = long_chat(db)
    seen = bubble_ids(client.get(f"/chats/{cid}").text)
    pages = 0
    while True:
        part = client.get(f"/chats/{cid}/thread?before={seen[0]}").text
        older = bubble_ids(part)
        assert 0 < len(older) <= 20 and max(older) < min(seen) or len(seen) == LONG_CHAT
        seen = older + seen
        pages += 1
        if "Beginning of the conversation" in part:
            assert "Load older messages" not in part
            break
        assert f"before={older[0]}" in part
    all_ids = [r for r, in db.connect().execute(text(
        "SELECT id FROM messages WHERE customer_id = :c ORDER BY received_at, id"), {"c": cid})]
    assert seen == all_ids and len(seen) == LONG_CHAT and pages == LONG_CHAT // 20 - 1  # no gap, no double
    other = scalar(db, "SELECT id FROM customers WHERE id <> :c LIMIT 1".replace(":c", str(cid)))
    if other:  # a message id from another chat gives nothing
        assert bubble_ids(client.get(f"/chats/{other}/thread?before={seen[-1]}").text) == []


def test_d4_poll_is_204_when_nothing_changed_and_brings_only_new_bubbles(client, db):  # noqa: F811
    token = log_in(client)
    cid = long_chat(db)
    page = client.get(f"/chats/{cid}").text
    after, v = poll_vals(page)
    r = client.get(f"/chats/{cid}/thread?after={after}&v={v}")
    assert r.status_code == 204 and r.content == b"" and r.headers["X-Thread-Version"] == v
    with db.begin() as c:  # the customer writes again, the same day as the last message
        last = c.execute(text("SELECT received_at FROM messages WHERE id = :i"), {"i": after}).scalar()
        new = c.execute(text(
            "INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, received_at) "
            "VALUES ('telegram', 'long-test', 'new-1', :c, 'brand new message', :t) RETURNING id"),
            {"c": cid, "t": last}).scalar()
    r = client.get(f"/chats/{cid}/thread?after={after}&v={v}")
    assert r.status_code == 200 and r.headers["X-Thread-After"] == str(new)
    new_part = r.text.split('data-part="new"')[1].split('data-part="pending"')[0]
    assert bubble_ids(new_part) == [new] and "brand new message" in new_part and "day-sep" not in new_part
    assert len(r.text) < 6000  # a few bubbles, not the thread
    after, v = int(r.headers["X-Thread-After"]), r.headers["X-Thread-Version"]
    assert client.get(f"/chats/{cid}/thread?after={after}&v={v}").status_code == 204
    # a reply's state changes (queued -> failed): the pending part comes again, no bubbles repeated
    with db.begin() as c:
        c.execute(text("INSERT INTO outbox (customer_id, text, reply_kind, status, idempotency_key, created_by, error) "
                       "VALUES (:c, 'our reply', 'custom', 'failed', 'k-1', 1, 'flood wait')"), {"c": cid})
    r = client.get(f"/chats/{cid}/thread?after={after}&v={v}")
    assert r.status_code == 200 and "our reply" in r.text and "Try again" in r.text
    assert bubble_ids(r.text.split('data-part="new"')[1].split('data-part="pending"')[0]) == []
    assert token


def test_d4_new_day_gets_its_separator_and_unknown_after_is_safe(client, db):  # noqa: F811
    log_in(client)
    cid = long_chat(db)
    after, v = poll_vals(client.get(f"/chats/{cid}").text)
    with db.begin() as c:
        c.execute(text("INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, "
                       "received_at) VALUES ('telegram', 'long-test', 'new-2', :c, 'next day', :t)"),
                  {"c": cid, "t": datetime.now(UTC).replace(year=2030)})
    r = client.get(f"/chats/{cid}/thread?after={after}&v={v}")
    assert 'class="day-sep"' in r.text.split('data-part="pending"')[0]
    r = client.get(f"/chats/{cid}/thread?after=999999999&v=x")  # unknown id: the newest 20, never an error
    assert r.status_code == 200 and len(bubble_ids(r.text.split('data-part="pending"')[0])) == 20


def test_d4_photo_loading_state_is_refreshed_in_place(client, db):  # noqa: F811
    log_in(client)
    cid = long_chat(db)
    after, v = poll_vals(client.get(f"/chats/{cid}").text)
    photo = scalar(db, f"SELECT max(id) FROM messages WHERE customer_id = {cid} AND kind = 'photo'")
    with db.begin() as c:
        c.execute(text("INSERT INTO media_downloads (message_id, status, requested_by) VALUES (:m, 'queued', 1)"),
                  {"m": photo})
    r = client.get(f"/chats/{cid}/thread?after={after}&v={v}")
    replace = r.text.split('data-part="replace"')[1]
    assert r.status_code == 200 and bubble_ids(replace) == [photo] and "Loading photo" in replace
    v = r.headers["X-Thread-Version"]
    assert client.get(f"/chats/{cid}/thread?after={after}&v={v}").status_code == 204


def test_link_to_an_old_message_loads_down_to_it_in_one_request(client, db):  # noqa: F811
    log_in(client)
    cid = long_chat(db)
    shown = bubble_ids(client.get(f"/chats/{cid}").text)
    all_ids = [r for r, in db.connect().execute(text(
        "SELECT id FROM messages WHERE customer_id = :c ORDER BY received_at, id"), {"c": cid})]
    target = all_ids[30]
    part = client.get(f"/chats/{cid}/thread?before={shown[0]}&to={target}").text
    assert bubble_ids(part) == all_ids[30:all_ids.index(shown[0])]  # exactly down to the target, nothing missing
    assert f"before={target}" in part and "Load older messages" in part  # 30 older ones are still there
    first = client.get(f"/chats/{cid}/thread?before={shown[0]}&to={all_ids[0]}").text
    assert "Beginning of the conversation" in first
