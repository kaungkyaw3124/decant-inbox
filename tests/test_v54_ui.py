"""docs/SPEC-v5.4-ui-ux-cleanup.md X1 / X3 / X6: page pattern, Settings sections, empty states."""
import re

from app.core.db import SessionLocal
from app.models import User
from app.web import auth
from tests.test_web import PASSWORD, client, log_in  # noqa: F401  (fixture)


def test_settings_save_comes_back_to_its_section_with_saved(client, db):
    token = log_in(client)
    r = client.post("/settings/auto-speed", data={"csrf": token, "quiet_s": "1", "delay_min_s": "1",
                                                  "delay_max_s": "2"}, follow_redirects=False)
    assert r.headers["location"] == "/settings?section=auto-reply&saved=auto-speed#auto-speed"
    page = client.get(r.headers["location"]).text
    assert 'id="sec-auto-reply">' in page and 'id="sec-orders" hidden' in page  # one section shown
    assert page.count("Saved ✓") == 1 and 'aria-current="page"><i class="bi bi-chat"></i> Auto-reply' in page
    assert 'id="sec-orders">' in client.get("/settings").text  # default section


def test_settings_unknown_section_and_staff(client, db):
    log_in(client)
    assert 'id="sec-orders">' in client.get("/settings?section=<script>").text
    with SessionLocal.begin() as s:
        s.add(User(username="staff7", password_hash=auth.hash_password(PASSWORD), role="staff"))
    client.post("/logout", data={"csrf": re.search(r'name="csrf" value="([^"]+)"', client.get("/").text).group(1)})
    page = client.get("/login").text
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    client.post("/login", data={"csrf": token, "username": "staff7", "password": PASSWORD, "next": "/"})
    assert client.get("/settings?section=alerts", follow_redirects=False).status_code == 403


def test_no_emoji_in_page_titles_and_section_headings(client, db):
    log_in(client)
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    for path in ("/settings", "/ai", "/products", "/customers", "/orders", "/activity", "/users", "/stock"):
        page = client.get(path).text
        for heading in re.findall(r"<h[12][^>]*>(.*?)</h[12]>", page, re.S):
            text = re.sub(r"<details.*?</details>", "", heading, flags=re.S)  # the "?" help text may use ✅
            assert not emoji.search(text), (path, text)


def test_empty_lists_say_what_to_do_next(client, db):
    log_in(client)
    page = client.get("/products?q=zzzz").text
    assert 'class="empty-state"' in page and "Check the spelling" in page and 'href="/products"' in page
    assert 'class="empty-state"' in client.get("/customers?q=zzzz").text


def test_error_page_offers_next_steps_and_owner_request_id(client, db):
    log_in(client)
    r = client.get("/customers/999999")
    assert r.status_code == 404 and 'href="/chats"' in r.text and "Back to Chats" in r.text
    assert re.search(r'href="/customers/999999"[^>]*>Try again', r.text) and re.search(r"Request id: <code>[0-9a-f]{8}</code>", r.text)


def test_menu_has_customers(client, db):
    log_in(client)
    page = client.get("/products").text
    menu = page[page.index('class="sidebar"'):page.index("</nav>", page.index('class="sidebar"'))]
    assert [m for m in ("/chats", "/orders", "/payments", "/customers", "/products", "/sales", "/settings")
            if f'href="{m}"' not in menu] == []


def test_orders_list_and_detail_panel(client, db):
    from tests.matrix_v410 import make_state
    from tests.test_cart import shop  # noqa: F401
    from tests.test_messaging import scalar

    log_in(client)
    make_state(db, "paid")
    oid = scalar(db, "SELECT id FROM orders WHERE order_no IS NOT NULL ORDER BY id LIMIT 1")
    page = client.get("/orders?tab=all").text
    assert f'class="item order-row is-open" id="order-{oid}"' in page  # the first order is open
    assert f'href="/orders?tab=all&amp;open={oid}"' in page and 'class="rows orders split"' in page
    assert f'class="item order-row is-open" id="order-{oid}"' in client.get(f"/orders?tab=all&open={oid}").text
    assert f'class="item order-row is-open" id="order-{oid}"' in client.get("/orders?tab=all&open=999999").text
