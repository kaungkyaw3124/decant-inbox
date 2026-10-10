"""Dashboard: login, inbox filters, edits, review, catalog. Runs on the test DB."""
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.listener.save import IncomingMessage, save_message
from app.models import User
from app.parser.worker import run_batch
from app.web.auth import hash_password
from scripts.seed_catalog import seed
from tests.test_seed_catalog import write_csvs

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


def add_message(msg_id: int, body: str, user_id: str = "42") -> None:
    with SessionLocal.begin() as s:
        save_message(s, IncomingMessage(user_id, str(msg_id), user_id, None, f"User {user_id}", body, NOW))


def csrf(client: TestClient, path: str = "/login") -> str:
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


@pytest.fixture
def client(db, tmp_path):
    from app.web.main import app

    seed(write_csvs(tmp_path))
    with SessionLocal.begin() as s:
        s.add(User(username="owner", password_hash=hash_password(PASSWORD), role="owner"))
    add_message(1, "stw intensely ၅ ml ဝယ်ချင်လို့ပါ")
    add_message(2, "ကျေးဇူးပါ")
    add_message(3, "aventus 10ml ရှိလား", user_id="77")
    run_batch()
    return TestClient(app, base_url="https://testserver")


def log_in(client: TestClient) -> str:
    token = csrf(client)
    r = client.post("/login", data={"username": "Owner", "password": PASSWORD, "csrf": token, "next": "/"},
                    follow_redirects=False)
    assert r.status_code == 303
    return csrf(client, "/")


def ids(html: str) -> list[int]:
    return [int(i) for i in re.findall(r'id="msg-(\d+)"', html)]


def test_pages_need_login(client):
    for path in ("/", "/messages/1", "/products"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_wrong_password_and_missing_csrf(client):
    token = csrf(client)
    r = client.post("/login", data={"username": "owner", "password": "nope", "csrf": token})
    assert r.status_code == 401 and "Wrong username or password" in r.text
    r = client.post("/login", data={"username": "owner", "password": PASSWORD})
    assert r.status_code == 403


def test_inbox_filters(client):
    log_in(client)
    assert ids(client.get("/").text) == [3, 1]  # newest first, "other" hidden by default
    assert ids(client.get("/?intent=all").text) == [3, 2, 1]
    assert ids(client.get("/?intent=buy").text) == [1]
    assert ids(client.get("/?needs_review=1").text) == [3]  # aventus is not in the catalog
    assert ids(client.get("/?q=aventus").text) == [3]
    assert ids(client.get("/?q=%E1%81%85").text) == [1]  # Burmese digit ၅ matches normalized "5"


def test_review_status_htmx_and_form(client):
    token = log_in(client)
    r = client.post("/messages/1/review", data={"status": "done"},
                    headers={"HX-Request": "true", "X-CSRF-Token": token})
    assert r.status_code == 200 and 'id="msg-1"' in r.text and "Undo" in r.text
    assert ids(client.get("/").text) == [3]
    assert ids(client.get("/?status=done").text) == [1]
    r = client.post("/messages/3/review", data={"status": "ignored", "note": "spam", "csrf": token})
    assert r.status_code == 200 and "spam" in r.text
    assert client.post("/messages/3/review", data={"status": "bogus", "csrf": token}).status_code == 400


def test_edit_parse_is_human_and_saves_alias(db, client):
    token = log_in(client)
    with db.connect() as c:
        sauvage = c.execute(text("SELECT id FROM products WHERE brand = 'Dior'")).scalar()
    r = client.post("/messages/3/parse", data={
        "intent": "ask_stock", "product_id": str(sauvage), "size_ml": "10", "quantity": "1",
        "alias": "Aventus", "csrf": token, "back": "/?intent=all",
    }, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/messages/3?back=")
    with db.connect() as c:
        rows = c.execute(text("SELECT method, is_current FROM parse_results WHERE message_id = 3 ORDER BY id")).all()
        alias = c.execute(text("SELECT source FROM product_aliases WHERE normalized_alias = 'aventus'")).scalar()
    assert rows == [("rules", False), ("human", True)]
    assert alias == "learned"
    page = client.get("/messages/3").text
    assert "edited" in page and "Alias “Aventus” added" in page


def customer_id(db, external_id: str) -> int:
    with db.connect() as c:
        return c.execute(text("SELECT id FROM customers WHERE external_user_id = :e"), {"e": external_id}).scalar()


def test_ignore_customer_hides_messages(db, client):
    token = log_in(client)
    r = client.post(f"/customers/{customer_id(db, '77')}/ignored", data={"ignored": "1", "csrf": token, "back": "/"})
    assert r.status_code == 200
    assert ids(client.get("/").text) == [1]
    assert ids(client.get("/?show_ignored=1").text) == [3, 1]


def test_open_redirect_blocked(db, client):
    token = log_in(client)
    r = client.post(f"/customers/{customer_id(db, '77')}/ignored", data={"ignored": "0", "csrf": token, "back": "//evil.example"},
                    follow_redirects=False)
    assert r.headers["location"] == "/"


def test_products_and_aliases(db, client, tmp_path_factory):
    token = log_in(client)
    assert "Stronger With You Intensely" in client.get("/products").text
    r = client.post("/products", data={"brand": "Creed", "name": "Aventus", "csrf": token}, follow_redirects=False)
    pid = int(r.headers["location"].rsplit("/", 1)[1])
    client.post(f"/products/{pid}/aliases", data={"alias": "အဗင်တပ်စ်", "csrf": token})
    page = client.get(f"/products/{pid}").text
    assert "အဗင်တပ်စ်" in page and "added here" in page
    with db.connect() as c:
        alias_ids = c.execute(text("SELECT id FROM product_aliases WHERE product_id = :p ORDER BY id"), {"p": pid}).scalars().all()
    client.post(f"/products/{pid}/aliases/{alias_ids[-1]}/delete", data={"csrf": token})
    assert "အဗင်တပ်စ်" not in client.get(f"/products/{pid}").text
    # seed aliases cannot be deleted from the dashboard
    with db.connect() as c:
        seed_alias, seed_pid = c.execute(text("SELECT id, product_id FROM product_aliases WHERE source='seed' LIMIT 1")).one()
    r = client.post(f"/products/{seed_pid}/aliases/{seed_alias}/delete", data={"csrf": token})
    assert "Only aliases added here can be deleted" in r.text
    # a manual product survives a re-seed
    seed(write_csvs(tmp_path_factory.mktemp("reseed")))
    with db.connect() as c:
        assert c.execute(text("SELECT active FROM products WHERE id = :p"), {"p": pid}).scalar() is True


def test_logout(client):
    token = log_in(client)
    client.post("/logout", data={"csrf": token})
    assert client.get("/", follow_redirects=False).status_code == 303
