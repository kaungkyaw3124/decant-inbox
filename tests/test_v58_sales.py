"""docs/SPEC-v5.8-sales-one-screen.md Z2/Z3: Sales on one screen — the same numbers as the report (= the old page),
Chart | Table remembered, per size, per perfume top 6 + "Show all", staff never see cost or profit."""
import re
from datetime import UTC, date, datetime, timedelta

from app.orders import sales
from tests.test_after_payment import paid_order
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_sales import costs, report, set_paid_at
from tests.test_v4_teaching import staff_client
from tests.test_web import client  # noqa: F401  (fixture)


def kpis(page: str) -> dict[str, str]:
    return dict(re.findall(r'<div class="kpi[^"]*"><span>([^<]+)</span><b>([^<]+)</b>', page))


def two_orders(shop, db, tmp_path, monkeypatch, with_costs=True):
    client, token = shop
    if with_costs:
        costs(db, client, token)
    a = paid_order(client, token, db, tmp_path, monkeypatch, "91", 1)
    b = paid_order(client, token, db, tmp_path, monkeypatch, "92", 2)
    today = sales.today()
    set_paid_at(db, b, datetime.combine(today - timedelta(days=2), datetime.min.time(), tzinfo=UTC) + timedelta(hours=6))
    return client, a, b, today


def test_z2_page_numbers_equal_the_report(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, _, _, today = two_orders(shop, db, tmp_path, monkeypatch)
    r = report(today - timedelta(days=6), today)
    page = client.get("/sales?range=7d").text
    k = kpis(page)
    assert k["Revenue"] == f"{r.total.revenue:,}" == "36,000" and k["Orders"] == str(len(r.total.orders))
    assert k["Cost"] == f"{r.total.cost:,}" and k["Profit"] == f"{r.total.profit:,}"
    assert f"Average order {r.total.average:,} Ks" in page and f"{r.total.margin:.1f}% of revenue" in page
    assert f"{r.total.items} items · {r.total.ml:,} ml poured" in page
    # per size and per perfume carry the same figures
    for g in r.sizes:
        assert f"<b>{g.label}</b><span>{g.revenue:,} Ks · {g.items} sold</span>" in page
    assert re.search(r'role="cell">Stronger With You Intensely</span><span role="cell" class="num">2</span>', page)
    # per day: 7 bars, the table has every day and the same total
    assert page.count('class="day-col"') == 7
    table = client.get("/sales?range=7d&view=table").text
    assert table.count("<tr><td>") == 7 and f'<th class="num">{r.total.revenue:,}</th>' in table


def test_z2_chart_table_choice_is_remembered(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, *_ = two_orders(shop, db, tmp_path, monkeypatch)
    r = client.get("/sales?range=7d&view=table")
    assert r.cookies.get("sales_view") == "table" or client.cookies.get("sales_view") == "table"
    page = client.get("/sales?range=7d").text
    assert '<table class="sales">' in page and 'class="day-chart"' not in page
    assert 'href="/sales?range=7d&amp;view=chart"' in page
    client.get("/sales?view=chart")
    assert 'class="day-chart"' in client.get("/sales?range=7d").text
    assert 'class="day-chart"' in client.get("/sales?range=7d&view=nonsense").text


def test_z2_long_range_gives_weekly_bars_and_empty_range_is_friendly(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, _, _, today = two_orders(shop, db, tmp_path, monkeypatch)
    first = today - timedelta(days=59)
    page = client.get(f"/sales?from={first.isoformat()}&to={today.isoformat()}").text
    assert "one bar per week" in page and 8 <= page.count('class="day-col"') <= 10
    bars, weekly = sales.day_bars(report(first, today))
    assert weekly and sum(b["g"].revenue for b in bars) == 36000
    empty = client.get("/sales?from=2020-01-01&to=2020-01-07").text
    assert empty.count("No paid orders in this range.") == 3 and 'class="tabs date-chips"' in empty


def test_z2_per_perfume_shows_six_then_show_all(client, monkeypatch):  # noqa: F811
    from tests.test_web import log_in
    log_in(client)
    total = sales.Group("Total", orders={1}, items=9, revenue=45000)
    fake = sales.Report("7d", date(2026, 11, 3), date(2026, 11, 9), total, [(date(2026, 11, 9), total)],
                        [sales.Group(f"Perfume {n}", orders={1}, items=1, revenue=1000 * (10 - n)) for n in range(9)], [], 0)
    monkeypatch.setattr(sales, "report", lambda *a: fake)
    page = client.get("/sales?range=7d").text
    top, rest = page.split('<details class="more-perfumes">')
    assert all(f"Perfume {n}<" in top for n in range(6)) and "Perfume 6<" not in top
    assert "Show all 9 perfumes" in rest and all(f"Perfume {n}<" in rest for n in range(6, 9))


def test_z3_missing_cost_bar_and_fill_costs(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, *_ = two_orders(shop, db, tmp_path, monkeypatch, with_costs=False)
    page = client.get("/sales?range=7d").text
    assert "Profit may look too high:" in page and "2 items have no cost yet" in page
    assert re.search(r"Use today(&#39;|')s costs for 2 orders", page) and 'action="/sales/fill-costs"' in page
    assert kpis(page)["Profit"] == "—"


def test_z3_staff_see_no_cost_or_profit_anywhere(shop, db, tmp_path, monkeypatch):  # noqa: F811
    two_orders(shop, db, tmp_path, monkeypatch)
    staff, _ = staff_client(db)
    for url in ("/sales?range=7d", "/sales?range=7d&view=table"):
        page = staff.get(url).text
        main = page[page.index("<main"):page.index("</main>")]
        assert set(kpis(page)) == {"Revenue", "Orders"} and 'class="kpis two"' in page
        assert not re.search(r"(?i)\bcost\b|\bprofit\b|bar profit|fill-costs", main), url
