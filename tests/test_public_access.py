"""Phase 5 public access: tunnel URL parsing, client IP behind cloudflared, login lockout."""
from types import SimpleNamespace

import pytest

from app.web import auth
from scripts.tunnel import find_url, write_url


@pytest.fixture(autouse=True)
def clean_failures():
    auth._failures.clear()
    yield
    auth._failures.clear()


def test_find_url_in_cloudflared_log():
    banner = "2026-10-11T03:00:00Z INF |  https://tidy-owl-river-lamp.trycloudflare.com                    |"
    assert find_url(banner) == "https://tidy-owl-river-lamp.trycloudflare.com"
    error = 'ERR failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp'
    assert find_url(error) is None
    assert find_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None


def test_write_url_is_private(tmp_path):
    target = tmp_path / "TUNNEL_URL"
    write_url("https://a-b.trycloudflare.com", target)
    assert target.read_text() == "https://a-b.trycloudflare.com\n"
    assert oct(target.stat().st_mode)[-3:] == "600"


def fake_request(peer: str, cf_ip: str | None = None):
    headers = {"cf-connecting-ip": cf_ip} if cf_ip else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_client_ip_trusts_cloudflare_header_only_from_localhost():
    assert auth.client_ip(fake_request("127.0.0.1", "203.0.113.7")) == "203.0.113.7"
    assert auth.client_ip(fake_request("127.0.0.1")) == "127.0.0.1"  # SSH tunnel
    assert auth.client_ip(fake_request("198.51.100.9", "203.0.113.7")) == "198.51.100.9"


def test_lockout_per_ip_does_not_lock_owner_elsewhere(monkeypatch):
    monkeypatch.setattr(auth, "_DUMMY_HASH", auth.hash_password("x"))  # verify() fails fast
    db = SimpleNamespace(query=lambda *_: SimpleNamespace(
        filter=lambda *_: SimpleNamespace(one_or_none=lambda: None)))
    for _ in range(auth.MAX_FAILURES_PER_IP):
        auth.authenticate(db, "owner", "wrong", "203.0.113.7")
    assert auth.locked_out("owner", "203.0.113.7")
    assert not auth.locked_out("owner", "198.51.100.9")  # owner on another IP can still log in
    assert auth.locked_out("someone", "203.0.113.7")    # the attacker IP is blocked for all names


def test_lockout_per_username_across_many_ips():
    for i in range(auth.MAX_FAILURES_PER_USER):
        auth._failures["user:owner"].append(auth.time.monotonic())
    assert auth.locked_out("owner", "192.0.2.1")
    assert not auth.locked_out("other", "192.0.2.1")
