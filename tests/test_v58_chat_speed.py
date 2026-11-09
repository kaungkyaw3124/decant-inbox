"""docs/SPEC-v5.8 B: the chat page stays light — a query budget for a 600-message chat, and the cached reference data
(app.web.refcache) follows every change, also one written straight to the database by another process."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, text

from app.core.db import SessionLocal, engine
from scripts.perf_check import seed_long_chat
from tests.test_web import client, log_in  # noqa: F401  (fixture)

BUDGET = 30  # 26 when written (v5.8); was 55 with 100 bubbles (v5.6)


def test_open_a_600_message_chat_within_the_query_budget(client, db, monkeypatch):  # noqa: F811
    from app.web import auto as auto_pages
    monkeypatch.setattr(auto_pages, "CACHE_SECONDS", 30)  # conftest switches the "Needs you" cache off; production has it
    log_in(client)
    with SessionLocal.begin() as s:
        cid = seed_long_chat(s, "budget")
    client.get(f"/chats/{cid}")  # warm the caches (the first open may change what the "Needs you" cache keys on)
    client.get(f"/chats/{cid}")
    seen = []
    import traceback

    def hook(*a):  # which function asked (shown when the budget is broken)
        st = [f for f in traceback.extract_stack() if "/app/" in f.filename]
        seen.append(st[-1].name if st else "?")
    event.listen(engine, "before_cursor_execute", hook)
    try:
        r = client.get(f"/chats/{cid}")
    finally:
        event.remove(engine, "before_cursor_execute", hook)
    from collections import Counter
    assert r.status_code == 200 and len(seen) <= BUDGET, (len(seen), Counter(seen).most_common())


def test_cached_reference_data_follows_a_change_from_another_process(client, db):  # noqa: F811
    log_in(client)
    with SessionLocal.begin() as s:  # the last message a day ago: the reply box starts with the greeting text
        cid = seed_long_chat(s, "cache", end=datetime.now(UTC) - timedelta(days=1))
    assert "Brand New Perfume" not in client.get(f"/chats/{cid}").text
    with db.begin() as c:  # like the listener / a script: no POST through this web process
        c.execute(text("INSERT INTO products (brand, name, source) VALUES ('X', 'Brand New Perfume', 'manual')"))
    assert "Brand New Perfume" in client.get(f"/chats/{cid}").text
    with db.begin() as c:
        c.execute(text("UPDATE products SET active = false WHERE name = 'Brand New Perfume'"))
    assert "Brand New Perfume" not in client.get(f"/chats/{cid}").text
    with db.begin() as c:
        c.execute(text("INSERT INTO reply_templates (key, text) VALUES ('greeting', 'Hello from the new template')"))
    assert "Hello from the new template" in client.get(f"/chats/{cid}").text
