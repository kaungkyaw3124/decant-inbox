"""docs/SPEC-v5.0-go-live-pack.md: alert bot (fake Bot API), alert rules (dedupe, rate limit, resolved, summary),
encrypted backup round trip + restore, 2-step login, log out everywhere, packing slips."""
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from app.alerts import bot, service as alerts
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import ServiceHeartbeat
from app.web import auth, twostep
from scripts import backup_db, create_user, restore_backup
from tests.test_after_payment import paid_order
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_payments import photo, waiting_for_payment
from tests.test_web import PASSWORD, client, csrf, log_in  # noqa: F401  (fixture)


# ---------- G1 the bot ----------

@pytest.fixture
def fake_api(monkeypatch):
    """The Bot API over a mock transport; returns the list of (method, form fields, file names) sent."""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = request.content.decode(errors="ignore")
        if "fail-me" in body:
            return httpx.Response(200, json={"ok": False, "error_code": 400, "description": "Bad Request"})
        sent.append((method, body, re.findall(r'filename="([^"]+)"', body)))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

    monkeypatch.setattr(bot, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(get_settings(), "alert_bot_token", SecretStr("123:SECRET-TOKEN"))
    monkeypatch.setattr(get_settings(), "alert_chat_id", "4242")
    return sent


def test_bot_sends_messages_files_in_parts_and_never_leaks_the_token(fake_api, tmp_path, monkeypatch):
    bot.send("hello", ("Open dashboard", "https://x.trycloudflare.com"))
    method, body, _ = fake_api[0]
    assert method == "sendMessage" and "4242" in body and "inline_keyboard" in body and "trycloudflare" in body
    bot.send("no button", ("Open", "http://not-https"))
    assert "inline_keyboard" not in fake_api[1][1]
    with pytest.raises(bot.BotError) as err:
        bot.send("fail-me")
    assert "SECRET" not in str(err.value) and "123:" not in str(err.value)
    f = tmp_path / "x.dump.gpg"
    f.write_bytes(b"a" * 25)
    monkeypatch.setattr(bot, "MAX_FILE", 10)
    assert bot.send_file(f, "backup") == 3
    assert [n for _, _, names in fake_api[2:] for n in names] == ["x.dump.gpg.part1", "x.dump.gpg.part2",
                                                                    "x.dump.gpg.part3"]
    monkeypatch.setattr(get_settings(), "alert_bot_token", None)
    assert not bot.configured()
    with pytest.raises(bot.BotError):
        bot.send("off")


# ---------- G1 the rules ----------

def tick(now, monkeypatch=None, found=None):
    got = []
    if found is not None:
        monkeypatch.setattr(alerts, "problems", lambda s, n, p: dict(found))
    sent = alerts.tick(now, send=lambda text, button: got.append(text))
    assert sent == got
    return got


def test_alert_new_once_resolved_and_same_alert_once_per_30_min(db, monkeypatch):
    now = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)  # 09:30 in Yangon: no daily summary
    down = {"check:listener": ("service", "❌ listener: last heartbeat 5 min ago")}
    assert tick(now, monkeypatch, down) == ["❌ listener: last heartbeat 5 min ago"]
    assert tick(now + timedelta(seconds=30), monkeypatch, down) == []  # told once
    assert tick(now + timedelta(minutes=2), monkeypatch, {}) == ["✅ resolved: listener: last heartbeat 5 min ago"]
    assert tick(now + timedelta(minutes=3), monkeypatch, down) == []  # flapping: not again within 30 min
    assert tick(now + timedelta(minutes=4), monkeypatch, {}) == ["✅ resolved: listener: last heartbeat 5 min ago"]
    assert tick(now + timedelta(minutes=40), monkeypatch, down) == ["❌ listener: last heartbeat 5 min ago"]
    pay = {"payment:7": ("payment", "💳 Payment to check: Ko Aung, 18,000 Ks")}
    assert tick(now + timedelta(minutes=41), monkeypatch, pay) == ["💳 Payment to check: Ko Aung, 18,000 Ks",
                                                                   "✅ resolved: listener: last heartbeat 5 min ago"]
    assert tick(now + timedelta(minutes=42), monkeypatch, {}) == []  # a checked payment: no "resolved" noise


def test_alert_rate_limit_switches_and_daily_summary(db, monkeypatch):
    now = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)
    many = {f"payment:{n}": ("payment", f"💳 {n}") for n in range(25)}
    assert len(tick(now, monkeypatch, many)) == alerts.PER_HOUR
    later = now + timedelta(hours=1, minutes=1)
    one = {**many, "check:disk": ("disk", "❌ disk: 3 GiB free (8%)")}
    got = tick(later, monkeypatch, one)
    # the 5 held back are not sent late; the next alert says how many were held back
    assert got == ["❌ disk: 3 GiB free (8%)\n(+5 more alerts were held back: max 20 per hour)"]
    with SessionLocal.begin() as s:
        alerts.save_settings(s, {**{k: True for k in alerts.TYPES}, "disk": False}, False, None)
    assert tick(later + timedelta(minutes=1), monkeypatch, {}) == []  # disk alerts off: no "resolved" either
    evening = datetime(2026, 11, 2, 14, 35, tzinfo=UTC)  # 21:05 in Yangon
    got = tick(evening, monkeypatch, {})
    assert len(got) == 1 and got[0].startswith("📊 Today: 0 paid orders") and "automatic" in got[0]
    assert tick(evening + timedelta(minutes=5), monkeypatch, {}) == []  # once a day


def test_alert_problems_from_the_shop(shop, db):  # noqa: F811
    client, token = shop
    waiting_for_payment(client, token, db, customer="701")
    photo(1, customer="701")
    from app.parser.worker import scan_payments

    scan_payments()
    with SessionLocal.begin() as s:
        s.add(ServiceHeartbeat(name="listener", last_seen=datetime.now(UTC) - timedelta(hours=1), details="x"))
    with SessionLocal() as s:
        found = alerts.problems(s, datetime.now(UTC), preview=False)
    kinds = {k.split(":")[0] + ":" + v[0] for k, v in found.items()}
    assert "payment:payment" in kinds and "check:service" in kinds
    assert all("hi" not in text for _, text in found.values())  # no message text without "preview"


def test_settings_page_alerts_section_and_test_button(shop, db, fake_api):  # noqa: F811
    client, token = shop
    page = client.get("/settings").text
    assert 'id="alerts"' in page and "Send a test alert" in page
    data = {"csrf": token, "preview": "1", **{f"type_{k}": "1" for k in alerts.TYPES if k != "summary"}}
    client.post("/settings/alerts", data=data)
    with SessionLocal() as s:
        cfg = alerts.settings(s)
    assert cfg["preview"] and not cfg["types"]["summary"] and cfg["types"]["payment"]
    client.post("/settings/alerts/test", data={"csrf": token})
    assert fake_api[-1][0] == "sendMessage" and "Test+alert" in fake_api[-1][1]


# ---------- G2 backup ----------

def test_backup_encrypt_decrypt_restore_round_trip(shop, db, tmp_path, fake_api, monkeypatch):  # noqa: F811
    client, token = shop
    waiting_for_payment(client, token, db, customer="711")
    dump = backup_db.run_backup(3, tmp_path)
    secret = backup_db.encrypt(dump, "correct horse battery")
    assert secret.read_bytes()[:3] != dump.read_bytes()[:3] and b"messages" not in secret.read_bytes()
    with pytest.raises(RuntimeError):
        backup_db.decrypt(secret, tmp_path / "bad.dump", "wrong passphrase")
    plain = backup_db.decrypt(secret, tmp_path / "back.dump", "correct horse battery")
    assert plain.read_bytes() == dump.read_bytes()
    scratch = get_settings().db_name + "_restoretest"
    counts = restore_backup.restore(plain, scratch)
    for table, n in counts.items():
        assert n == scalar(db, f"SELECT count(*) FROM {table}"), table
    assert counts["messages"] > 0 and counts["orders"] == 1
    admin = create_engine(get_settings().database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{scratch}" WITH (FORCE)'))
    admin.dispose()
    # off-server copy: encrypted to the bot, nothing left behind
    assert "OFF" in backup_db.offsite(dump)  # no passphrase yet
    monkeypatch.setattr(get_settings(), "backup_passphrase", SecretStr("correct horse battery"))
    assert backup_db.offsite(dump) == "sent to the alert bot (1 file)"
    assert fake_api[-1][0] == "sendDocument" and fake_api[-1][2] == [dump.name + ".gpg"]
    assert not list(tmp_path.glob("*.gpg.*")) and not (tmp_path / (dump.name + ".gpg")).exists()
    run = subprocess.run([".venv/bin/python", "-m", "scripts.restore_backup", str(dump), "--db", get_settings().db_name],
                         capture_output=True, text=True)
    assert run.returncode != 0 and "LIVE database" in run.stderr  # never over the live DB by mistake


# ---------- G3 2-step login ----------

def test_totp_rfc_6238_vector_and_window():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
    assert twostep.code(secret, 59) == "287082" and twostep.code(secret, 1111111109) == "081804"
    assert twostep.verify(secret, "287 082", at=59) and twostep.verify(secret, twostep.code(secret, 30), at=59)
    assert not twostep.verify(secret, twostep.code(secret, 120), at=59) and not twostep.verify(None, "123456")
    shown, hashes = twostep.new_recovery_codes()
    assert len(shown) == 10 and len(set(hashes)) == 10
    left = twostep.use_recovery(hashes, shown[3].upper())
    assert left is not None and len(left) == 9 and twostep.use_recovery(left, shown[3]) is None
    assert "<svg" in twostep.qr_svg(twostep.uri(secret, "owner"))


def _enrol(client) -> tuple[str, list[str]]:
    token = csrf(client, "/account")
    page = client.post("/account/2fa/start", data={"csrf": token}).text
    secret = re.search(r"<code>([A-Z2-7]{32})</code>", page).group(1)
    assert "<svg" in page
    assert client.post("/account/2fa/confirm", data={"csrf": token, "code": "000000"}).status_code == 400
    page = client.post("/account/2fa/confirm", data={"csrf": token, "code": twostep.code(secret)}).text
    codes = re.findall(r"\b[0-9a-f]{4}-[0-9a-f]{4}\b", page)
    assert len(codes) == 10 and "not shown again" in page
    return secret, codes


def _password(client):
    return client.post("/login", data={"username": "owner", "password": PASSWORD, "csrf": csrf(client), "next": "/"},
                       follow_redirects=False)


def test_two_step_login_recovery_code_and_reset(client, db, monkeypatch):  # noqa: F811
    log_in(client)
    secret, codes = _enrol(client)
    client.post("/logout", data={"csrf": csrf(client, "/")})
    r = _password(client)
    assert r.status_code == 200 and 'action="/login/code"' in r.text  # the password alone is not enough
    assert client.get("/", follow_redirects=False).status_code == 303  # not logged in yet
    token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    assert client.post("/login/code", data={"csrf": token, "code": "123456"}).status_code == 401
    r = client.post("/login/code", data={"csrf": token, "code": twostep.code(secret), "next": "/"},
                    follow_redirects=False)
    assert r.status_code == 303 and client.get("/").status_code == 200
    client.post("/logout", data={"csrf": csrf(client, "/")})
    r = _password(client)
    token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    client.post("/login/code", data={"csrf": token, "code": codes[0]})
    assert client.get("/").status_code == 200 and len(scalar(db, "SELECT totp_recovery FROM users")) == 9
    client.post("/logout", data={"csrf": csrf(client, "/")})
    r = _password(client)
    token = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    assert client.post("/login/code", data={"csrf": token, "code": codes[0]}).status_code == 401  # used up
    assert create_user.reset_2fa("owner") == ""  # lost phone: over SSH
    assert scalar(db, "SELECT totp_secret FROM users") is None
    assert _password(client).status_code == 303  # password only again


def test_staff_without_2fa_logs_in_and_new_device_alert(client, db, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(alerts, "login_alert", lambda *a: calls.append(a))
    from app.models import User
    with SessionLocal.begin() as s:
        s.add(User(username="staff2", password_hash=auth.hash_password(PASSWORD), role="staff"))
    r = client.post("/login", data={"username": "staff2", "password": PASSWORD, "csrf": csrf(client)},
                    follow_redirects=False)
    assert r.status_code == 303 and calls == []  # first login: remembered, no alert
    client.post("/logout", data={"csrf": csrf(client, "/")})
    client.post("/login", data={"username": "staff2", "password": PASSWORD, "csrf": csrf(client)})
    assert calls == []  # same device
    client.post("/logout", data={"csrf": csrf(client, "/")})
    client.headers["user-agent"] = "another phone"
    client.post("/login", data={"username": "staff2", "password": PASSWORD, "csrf": csrf(client)})
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls and calls[0][0] == "staff2" and calls[0][2] == "another phone"


def test_log_out_everywhere_and_12_hour_sessions(client, db, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient
    from app.web.main import app

    log_in(client)
    other = TestClient(app, base_url="https://testserver")
    log_in(other)
    assert other.get("/").status_code == 200
    client.post("/account/logout-everywhere", data={"csrf": csrf(client, "/account")})
    assert client.get("/").status_code == 200  # this browser stays in
    assert other.get("/", follow_redirects=False).status_code == 303  # the other one is out
    monkeypatch.setattr(auth, "SESSION_HOURS", 0)
    assert client.get("/", follow_redirects=False).status_code == 303  # 12 h passed


# ---------- G4 packing slips ----------

def test_packing_slip_and_print_all(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, token = shop
    order = paid_order(client, token, db, tmp_path, monkeypatch, customer="721")
    page = client.get(f"/orders/{order}/slip").text
    assert '<span class="order-id">#1001</span>' in page and "18,000" in page and "Stronger With You" in page
    assert "/static/slip.css" in page and "ကျေးဇူးတင်ပါတယ်" in page and "<svg" in page and "09777123456" in page
    css = Path("app/web/static/slip.css").read_text()
    assert "@page { size: 80mm auto" in css and "@media print" in css
    assert f'href="/orders/{order}/slip"' in client.get("/orders").text
    assert 'href="/orders/slips"' in client.get("/orders").text
    assert "#1001" in client.get("/orders/slips").text
    other = waiting_for_payment(client, token, db, customer="722")
    unpaid = scalar(db, "SELECT id FROM orders WHERE customer_id = :c", c=other)
    assert client.get(f"/orders/{unpaid}/slip").status_code == 404  # no Order ID yet
    assert json.dumps(scalar(db, "SELECT count(*) FROM orders WHERE status = 'paid'")) == "1"
