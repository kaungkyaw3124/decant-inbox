"""docs/SPEC-v5.4-ui-ux-cleanup.md U2 / X2: the shared pager."""
import pytest
from sqlalchemy import select, text
from starlette.requests import Request

from app.core.db import SessionLocal
from app.models import Product
from app.web import paging
from tests.test_web import client  # noqa: F401  (fixture)


def request(query: str = "", cookie: str = "") -> Request:
    headers = [(b"cookie", f"per={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/products", "query_string": query.encode(),
                    "headers": headers, "scheme": "https", "server": ("testserver", 443)})


@pytest.fixture
def products(db):
    def make(n: int):
        with db.begin() as c:
            c.execute(text("DELETE FROM products WHERE name LIKE 'P%-pager'"))
            for i in range(n):
                c.execute(text("INSERT INTO products (brand, name, active) VALUES ('B', :n, true)"),
                          {"n": f"P{i:03d}-pager"})
        return select(Product.name).where(Product.name.like("P%-pager")).order_by(Product.name)
    return make


def page(query, q: str = "", cookie: str = "", default: int = 20) -> paging.Page:
    with SessionLocal() as s:
        return paging.paginate(s, query, request(q, cookie), default, scalars=True)


@pytest.mark.parametrize("q,number,first", [("page=0", 1, "P000-pager"), ("page=-3", 1, "P000-pager"),
                                            ("page=abc", 1, "P000-pager"), ("page=2", 2, "P020-pager"),
                                            ("page=99999999", 3, "P040-pager"), ("page=3", 3, "P040-pager")])
def test_page_numbers_are_clamped(products, q, number, first):
    p = page(products(45), q)
    assert (p.page, p.items[0], p.total, p.pages) == (number, first, 45, 3)
    assert len(p.items) == (5 if number == 3 else 20)


def test_last_page_range_and_exact_multiple(products):
    p = page(products(40), "page=2")
    assert (p.pages, p.first, p.last, len(p.items)) == (2, 21, 40, 20)


def test_empty_list(products):
    p = page(products(0))
    assert (p.items, p.total, p.pages, p.first, p.last, p.numbers()) == ([], 0, 1, 0, 0, [1])


@pytest.mark.parametrize("q,cookie,per", [("per=50", "", 50), ("per=7", "", 20), ("per=10", "100", 10),
                                          ("", "100", 100), ("", "33", 20), ("per=999999999999", "", 20)])
def test_per_from_url_then_cookie_else_default(products, q, cookie, per):
    assert page(products(3), q, cookie).per == per


def test_numbers_with_ellipsis_and_urls_keep_filters(products):
    p = page(products(200), "q=sauvage&tab=all&page=6", default=10)
    assert p.numbers() == [1, None, 5, 6, 7, None, 20]
    assert p.url(page=7) == "/products?q=sauvage&tab=all&page=7"
    assert p.url(per=50) == "/products?q=sauvage&tab=all&per=50"  # a new size starts at page 1


def test_per_choice_is_remembered_in_a_small_cookie(client):
    from tests.test_web import log_in

    log_in(client)
    client.get("/chats?per=50")
    assert client.cookies.get("per") == "50"
    client.get("/chats?per=7")  # not a choice: ignored, the old one stays
    assert client.cookies.get("per") == "50"


def test_ai_calls_page_shows_10_with_a_working_pager(client, db):
    from tests.test_messaging import add
    from tests.test_web import log_in

    for n in range(23):
        add(9000 + n, f"m{n}")
    with db.begin() as c:
        c.execute(text("INSERT INTO ai_calls (message_id, model, mode, ok, decision, latency_ms) "
                       "SELECT id, 'm', 'shadow', true, 'shadow', 700 + id FROM messages "
                       "WHERE external_message_id::int >= 9000"))
    log_in(client)
    page = client.get("/ai").text
    assert page.count('<div class="list-row">') == 10 and "1–10 of 23" in page and 'aria-label="Next page"' in page
    page = client.get("/ai?page=3").text
    assert page.count('<div class="list-row">') == 3 and "21–23 of 23" in page
    assert client.get("/products?per=50").status_code == 200 and client.cookies.get("per") == "50"
    assert "1–20 of 23" not in client.get("/ai").text  # AI calls follow the remembered 50 too


def test_two_lists_on_one_page_page_separately(products):
    query = products(45)
    with SessionLocal() as s:
        a = paging.paginate(s, query, request("approved_page=3&auto_page=2"), key="approved_page", scalars=True)
        b = paging.paginate(s, query, request("approved_page=3&auto_page=2"), key="auto_page", scalars=True)
    assert (a.page, b.page) == (3, 2)
    assert a.url(page=1) == "/products?approved_page=1&auto_page=2"
    assert b.url(per=50) == "/products?approved_page=3&per=50"
