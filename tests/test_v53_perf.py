"""docs/SPEC-v5.3-performance-pc.md: speed on the PC browser without weakening security."""
import base64
import hashlib
import json
import logging
import re

from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.models import User
from app.web import auth, perf, twostep
from tests.test_messaging import scalar
from tests.test_web import PASSWORD, client, csrf, log_in  # noqa: F401 (fixture)


def test_server_timing_on_every_response(client):
    log_in(client)
    for path in ("/chats", "/login", "/healthz"):
        timing = client.get(path).headers["server-timing"]
        assert re.fullmatch(r"db;dur=[\d.]+, app;dur=-?[\d.]+, total;dur=[\d.]+", timing), timing


def test_slow_request_log_has_the_route_only(client, caplog, monkeypatch):
    log_in(client)
    monkeypatch.setattr(perf, "SLOW_MS", -1)
    monkeypatch.setattr(perf.log, "disabled", False)  # alembic's fileConfig in the test setup disables it
    with caplog.at_level(logging.WARNING, logger="perf"):
        client.get("/chats?q=secret-search-words")
        client.get("/chats/1")
    text = caplog.text
    assert "GET /chats " in text and "GET /chats/{customer_id}" in text
    assert "secret-search-words" not in text and "/chats/1 " not in text
    assert any(r["route"] == "GET /chats/{customer_id}" for r in perf.summary())


def test_static_files_cached_for_a_year_pages_never(client):
    log_in(client)
    page = client.get("/chats")
    assert page.headers["cache-control"] == "no-store"  # customer data: never stored by browser or Cloudflare
    urls = re.findall(r'(?:href|src)="(/static/[^"]+)"', page.text)
    assert any("app.css?v=" in u for u in urls) and any("app.js?v=" in u for u in urls)
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable", url
    assert client.get("/static/app.css").headers["cache-control"] == "no-cache"  # unversioned: check first
    assert client.get("/static/nope.css?v=1").headers["cache-control"] == "no-store"
    for path in ("/login", "/orders", "/healthz", "/health"):
        assert client.get(path).headers["cache-control"] == "no-store", path


def test_versioned_url_changes_when_the_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "STATIC", tmp_path)
    (tmp_path / "x.css").write_text("a{}")
    perf.static_url.cache_clear()
    first = perf.static_url("x.css")
    (tmp_path / "x.css").write_text("b{}")
    perf.static_url.cache_clear()  # a deploy restarts the web service
    assert first.startswith("/static/x.css?v=") and perf.static_url("x.css") != first
    perf.static_url.cache_clear()


def test_compression_on(client):
    log_in(client)
    for path in ("/chats", "/static/vendor/bootstrap-5.3.8/bootstrap.min.css"):
        r = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert r.headers.get("content-encoding") == "gzip", path


def test_security_headers_unchanged(client):
    log_in(client)
    for path in ("/chats", "/static/app.css"):
        h = client.get(path).headers
        assert h["content-security-policy"] == ("default-src 'self'; style-src 'self'; script-src 'self'; "
                                                "img-src 'self' data:; frame-ancestors 'none'")
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"


def test_csrf_token_masked_per_page_and_still_checked(client):
    log_in(client)
    a, b = csrf(client, "/chats"), csrf(client, "/chats")
    assert a != b  # random pad per page: compressed sizes say nothing about the token
    raw = json.loads(base64.b64decode(client.cookies.get("decant_session").split(".")[0]))["csrf"]
    assert raw not in client.get("/chats").text  # the real token never appears in a page
    for token in (a, b):
        r = client.post("/language", data={"csrf": token, "language": "en", "back": "/chats"}, follow_redirects=False)
        assert r.status_code == 303
    client.post("/language", data={"csrf": a[:-4] + "AAAA", "language": "my", "back": "/chats"})
    with SessionLocal() as s:  # a wrong token: nothing done
        assert s.scalar(select(User.language).where(User.username == "owner")) == "en"
    assert client.post("/language", data={"language": "en"}).status_code == 403


# ---------- M2 no full reloads ----------

def test_boosted_navigation_keeps_csrf_and_no_history_in_local_storage(client):
    log_in(client)
    page = client.get("/orders", headers={"HX-Request": "true", "HX-Boosted": "true"})
    assert page.status_code == 200 and "<body" in page.text and 'X-CSRF-Token' in page.text
    assert '"historyCacheSize": 0' in page.text and '"refreshOnHistoryMiss": true' in page.text
    assert 'class="sidebar" aria-label="Menu" hx-boost="true"' in page.text
    for action in ("/logout", "/language"):  # posting forms in the menu stay normal posts
        assert re.search(rf'action="{action}"[^>]*hx-boost="false"', page.text), action
    chat = client.get("/chats/1").text
    assert 'id="ws" class="ws ws-chat" data-customer="1"' in chat
    assert re.search(r'class="compose-box" hx-boost="true" hx-target="#ws" hx-select="#ws"[^>]*hx-select-oob="#toasts"',
                     chat)
    r = client.post("/chats/1/send", headers={"HX-Request": "true"},
                    data={"csrf": csrf(client, "/chats/1"), "text": "hi", "key": "k-boost", "reply_kind": "custom"})
    assert r.status_code == 200 and 'id="toasts"' in r.text and "Queued" in r.text  # redirect followed


def test_prefetch_only_links_never_posts():
    js = (perf.STATIC / "app.js").read_text()
    selector = re.search(r'var PREFETCH = "([^"]+)"', js).group(1)
    assert all(part.strip().split(" ")[-1].startswith("a") for part in selector.split(","))  # <a> only
    fetches = re.findall(r"fetch\(url, \{([^}]*)", js)
    assert fetches and all("method" not in f for f in fetches)  # GET
    assert not re.search(r"\b(localStorage|sessionStorage)\.\w+\(|document\.cookie", js)  # nothing stored


# ---------- M3 live updates ----------

def test_events_need_login_and_say_only_what_changed(client, monkeypatch):
    from app.web import live
    assert client.get("/events").status_code == 204  # not logged in: no stream, no reconnect loop
    log_in(client)
    monkeypatch.setattr(live, "STREAM_SECONDS", 4)
    monkeypatch.setattr(live, "LOOK_EVERY", 0.2)
    from tests.test_web import add_message

    import threading
    threading.Timer(1.5, add_message, (50, "secret customer words")).start()  # customer 1 (Telegram user 42)
    r = client.get("/events?customer=1")  # TestClient reads the whole 4 s stream
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store"
    lines = r.text.splitlines()
    text = "\n".join(lines)
    assert "event: list" in text and "event: thread" in text
    assert "secret customer words" not in text and "42" not in text


# ---------- M5 trusted computer ----------

def _login(client, trust_pc=True, username="owner"):
    data = {"username": username, "password": PASSWORD, "csrf": csrf(client), "next": "/"}
    if trust_pc:
        data["trust_pc"] = "1"
    return client.post("/login", data=data, follow_redirects=False)


def _fresh(client, token):
    from fastapi.testclient import TestClient

    from app.web.main import app
    other = TestClient(app, base_url="https://testserver")
    other.cookies.set("decant_trust", token, domain="testserver.local")
    return other


def test_trust_cookie_flags_hash_and_silent_renewal_with_rotation(client, db):
    r = _login(client)
    cookie = r.headers["set-cookie"] if "decant_trust" in r.headers.get("set-cookie", "") else \
        [c for c in r.headers.get_list("set-cookie") if c.startswith("decant_trust=")][0]
    assert re.search(r"HttpOnly", cookie) and "Secure" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert 29 * 86400 < int(re.search(r"Max-Age=(\d+)", cookie).group(1)) <= 30 * 86400
    token = client.cookies.get("decant_trust")
    stored = scalar(db, "SELECT token_hash FROM trusted_devices")
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored
    pc = _fresh(client, token)  # the 12 h session is gone, the trusted cookie is not
    assert pc.get("/chats", follow_redirects=False).status_code == 200
    rotated = pc.cookies.get("decant_trust")
    assert rotated and rotated != token
    assert _fresh(client, token).get("/chats", follow_redirects=False).status_code == 303  # old token: dead
    assert scalar(db, "SELECT count(*) FROM trusted_devices") == 1


def test_two_step_code_skipped_only_with_a_valid_token(client, db):
    from tests.test_v50_golive import _enrol
    log_in(client)
    _enrol(client)
    client.post("/logout", data={"csrf": csrf(client, "/")})
    r = _login(client)  # no token yet: the code is asked, trust waits for it
    assert r.status_code == 200 and 'action="/login/code"' in r.text
    secret = scalar(db, "SELECT totp_secret FROM users")
    token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    client.post("/login/code", data={"csrf": token, "code": twostep.code(secret), "next": "/"})
    trusted = client.cookies.get("decant_trust")
    assert trusted
    pc = _fresh(client, trusted)
    assert pc.post("/login", data={"username": "owner", "password": "wrong", "csrf": csrf(pc)}).status_code == 401
    r = _login(pc, trust_pc=False)
    assert r.status_code == 303  # password yes, code no
    from fastapi.testclient import TestClient
    from app.web.main import app
    stranger = TestClient(app, base_url="https://testserver")
    assert 'action="/login/code"' in _login(stranger, trust_pc=False).text  # another computer: code asked


def test_remove_logout_everywhere_logout_and_expiry_revoke(client, db):
    _login(client)
    token = client.cookies.get("decant_trust")
    page = client.get("/account").text
    assert "Trusted computers" in page and "This computer" in page
    device = scalar(db, "SELECT id FROM trusted_devices")
    client.post(f"/account/trusted/{device}/remove", data={"csrf": csrf(client, "/account")})
    assert _fresh(client, token).get("/chats", follow_redirects=False).status_code == 303

    _login(client)
    token = client.cookies.get("decant_trust")
    client.post("/account/logout-everywhere", data={"csrf": csrf(client, "/account")})
    assert scalar(db, "SELECT count(*) FROM trusted_devices") == 0
    assert _fresh(client, token).get("/chats", follow_redirects=False).status_code == 303

    client.post("/logout", data={"csrf": csrf(client, "/")})
    _login(client)
    client.post("/logout", data={"csrf": csrf(client, "/")})  # log out on this PC ends its trust
    assert scalar(db, "SELECT count(*) FROM trusted_devices") == 0 and not client.cookies.get("decant_trust")
    assert client.get("/chats", follow_redirects=False).status_code == 303

    _login(client)
    token = client.cookies.get("decant_trust")
    with db.begin() as c:
        c.execute(text("UPDATE trusted_devices SET expires_at = now() - interval '1 second'"))
    pc = _fresh(client, token)
    assert pc.get("/chats", follow_redirects=False).status_code == 303  # 30 days over: password again
    assert not pc.cookies.get("decant_trust")


def test_staff_cannot_trust_a_computer(client, db):
    with SessionLocal.begin() as s:
        s.add(User(username="staff9", password_hash=auth.hash_password(PASSWORD), role="staff"))
    r = _login(client, username="staff9")
    assert r.status_code == 303 and "decant_trust" not in r.headers.get("set-cookie", "")
    assert scalar(db, "SELECT count(*) FROM trusted_devices") == 0


# ---------- M4 the "Needs you" queue is computed once, not on every page ----------

def test_needs_you_cache_reused_until_data_changes_a_post_or_max_age(client, monkeypatch):
    from app.web import auto as auto_pages
    from tests.test_web import add_message
    monkeypatch.setattr(auto_pages, "CACHE_SECONDS", 30)
    first = auto_pages.needs_you_cached()
    assert auto_pages.needs_you_cached() is first  # nothing changed: same result, no recompute
    add_message(60, "aventus 10ml ရှိလား", user_id="88")  # a new customer message
    second = auto_pages.needs_you_cached()
    assert second is not first
    log_in(client)
    assert auto_pages.needs_you_cached() is not second  # the login POST cleared it
    third = auto_pages.needs_you_cached()
    monkeypatch.setattr(auto_pages, "CACHE_SECONDS", 0)  # older than max_age (time-based items)
    assert auto_pages.needs_you_cached() is not third
    calls = []
    real = auto_pages.needs_you
    monkeypatch.setattr(auto_pages, "needs_you", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(auto_pages, "CACHE_SECONDS", 30)
    auto_pages.forget_needs_you()
    ids = [i for i, in SessionLocal().execute(text("SELECT id FROM customers ORDER BY id"))]
    for path in ["/chats", "/"] + [f"/chats/{i}" for i in ids]:
        assert client.get(path).status_code == 200
    assert len(calls) == 1  # four pages + menu badges: one computation
