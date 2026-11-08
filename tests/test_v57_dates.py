"""docs/SPEC-v5.7-date-filter-and-light-chat.md A / D1: date chips on Orders, Payments, Customers and Sales, in the
shop's days (Asia/Yangon, UTC+06:30): fixed clocks around 23:59 / 00:00 Yangon and the 17:30 UTC date change."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from starlette.requests import Request

from app.core.db import SessionLocal
from app.orders import sales
from app.web import dates
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_v4_roles import _photo_check
from tests.test_web import client  # noqa: F401  (fixture)

TODAY = date(2026, 11, 8)
LATE_7TH = datetime(2026, 11, 7, 17, 29, tzinfo=UTC)  # 23:59 Yangon, 7 Nov
EARLY_8TH = datetime(2026, 11, 7, 17, 31, tzinfo=UTC)  # 00:01 Yangon, 8 Nov (still the 7th in UTC)


def req(query: str = "", path: str = "/orders") -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query.encode(), "headers": []})


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(sales, "today", lambda: TODAY)


def test_yangon_day_bounds_not_utc():
    dr = dates.date_range(req("range=today"), today=TODAY)
    start, end = dr.bounds
    assert start == datetime(2026, 11, 7, 17, 30, tzinfo=UTC) and end == datetime(2026, 11, 8, 17, 30, tzinfo=UTC)
    assert dates.date_range(req("range=yesterday"), today=TODAY).first == date(2026, 11, 7)
    seven = dates.date_range(req("range=7d"), today=TODAY)
    assert (seven.first, seven.last) == (date(2026, 11, 2), TODAY)
    assert dates.date_range(req("range=30d"), today=TODAY).first == date(2026, 10, 10)
    everything = dates.date_range(req(), today=TODAY)
    assert everything.key == "all" and everything.bounds is None and not everything.active


def test_picked_dates_swapped_broken_ignored_and_urls():
    dr = dates.date_range(req("tab=all&from=2026-11-05&to=2026-11-01&page=3"), today=TODAY)
    assert (dr.key, dr.first, dr.last) == ("custom", date(2026, 11, 1), date(2026, 11, 5))  # reversed -> swapped
    assert dr.query == "from=2026-11-01&to=2026-11-05"
    assert dr.url("7d") == "/orders?tab=all&range=7d"  # page back to 1, the tab stays
    assert dr.url("all") == "/orders?tab=all" and dr.keep() == [("tab", "all")]
    one = dates.date_range(req("from=2026-11-03"), today=TODAY)
    assert (one.first, one.last) == (date(2026, 11, 3), date(2026, 11, 3))
    broken = dates.date_range(req("from=abc&to=31-31"), today=TODAY)
    assert broken.key == "all" and broken.note  # never an error page
    assert dates.date_range(req("range=zzz"), today=TODAY).key == "all"


def _paid_order(db, customer: str, created: datetime, status: str = "paid") -> int:
    with SessionLocal.begin() as s:
        s.execute(text("INSERT INTO customers (channel, external_user_id, display_name) VALUES ('telegram', :e, :e) "
                       "ON CONFLICT DO NOTHING"), {"e": customer})
        cid = s.execute(text("SELECT id FROM customers WHERE external_user_id = :e"), {"e": customer}).scalar()
        return s.execute(text(
            "INSERT INTO orders (customer_id, status, phones, order_no, total_mmk, paid_at, created_at, updated_at) "
            "VALUES (:c, :s, '{}', nextval('order_no_seq'), 18000, :t, :t, :t) RETURNING id"),
            {"c": cid, "s": status, "t": created}).scalar()


def test_orders_today_yesterday_counts_tabs_and_row_dates(shop, db, fixed_today):  # noqa: F811
    client, _ = shop
    late, early = _paid_order(db, "d1", LATE_7TH), _paid_order(db, "d2", EARLY_8TH)
    today = client.get("/orders?tab=to_pack&range=today").text
    assert f'id="order-{early}"' in today and f'id="order-{late}"' not in today
    assert "8 Nov, 12:01 am" in today and "Showing 1 orders" in today and ">Clear<" in today
    assert 'href="/orders?tab=sent&range=today"' in today  # the status tabs keep the range
    yesterday = client.get("/orders?tab=to_pack&range=yesterday").text
    assert f'id="order-{late}"' in yesterday and f'id="order-{early}"' not in yesterday and "7 Nov, 11:59 pm" in yesterday
    assert '📦 To pack <span class="badge">1</span>' in yesterday  # the tab count follows the dates
    both = client.get("/orders?tab=to_pack&from=2026-11-07&to=2026-11-08").text
    assert f'id="order-{late}"' in both and f'id="order-{early}"' in both and "7 Nov – 8 Nov" in both
    assert client.get("/orders?tab=to_pack&from=nonsense").status_code == 200
    everything = client.get("/orders?tab=to_pack").text
    assert f'id="order-{late}"' in everything and ">Clear<" not in everything  # default = All time


def test_payments_follow_the_screenshot_day(shop, db, fixed_today):  # noqa: F811
    client, token = shop
    check = _photo_check(client, token, db, "91", 1)
    with db.begin() as c:
        c.execute(text("UPDATE payment_checks SET created_at = :t WHERE id = :i"), {"t": EARLY_8TH, "i": check})
    assert f"/payments/{check}" in client.get("/payments?range=today").text
    page = client.get("/payments?range=yesterday").text
    assert f"/payments/{check}" not in page and "Show all dates" in page
    assert f"/payments/{check}" in client.get("/payments").text


def test_customers_follow_the_last_message_day(shop, db, fixed_today):  # noqa: F811
    client, _ = shop
    _paid_order(db, "d3", LATE_7TH, status="delivered")
    cid = scalar(db, "SELECT id FROM customers WHERE external_user_id = 'd3'")
    with db.begin() as c:
        c.execute(text("INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, "
                       "received_at) VALUES ('telegram', 'd3', 'd3-1', :c, 'hi', :t)"), {"c": cid, "t": LATE_7TH})
    assert f"/customers/{cid}" in client.get("/customers?range=yesterday").text
    assert f"/customers/{cid}" not in client.get("/customers?range=today").text
    assert f"/customers/{cid}" in client.get("/customers?sort=last").text


def test_sales_chips_keep_today_default_and_accept_picked_dates(shop, db, fixed_today):  # noqa: F811
    client, _ = shop
    assert sales.resolve("7d", now_date=TODAY) == ("7d", date(2026, 11, 2), TODAY)
    assert sales.resolve("today", "2026-11-05", "2026-11-01", TODAY) == ("custom", date(2026, 11, 1), date(2026, 11, 5))
    page = client.get("/sales").text
    assert 'class="tabs date-chips"' in page and '<a href="/sales" aria-current="page">Today</a>' in page
    assert 'href="/sales?range=7d"' in page and 'href="/sales?range=week"' in page  # old chips kept
    assert client.get("/sales?from=2026-11-01&to=2026-11-05").status_code == 200
