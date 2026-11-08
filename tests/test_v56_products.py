"""docs/SPEC-v5.6-simple-products-page.md: ONE Products page — list + side panel (Prices / Stock / Nicknames),
two buttons (+ Add perfume, More ▾), one warning bar, old URLs redirect, nothing lost (S1-S3; S2/S4 in ui_check)."""
import re

from app.core.db import SessionLocal
from app.inventory import stock
from app.parser.worker import run_batch
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_v4_teaching import staff_client
from tests.test_web import add_message, client  # noqa: F401  (fixture)

STW = "Stronger With You Intensely"


def pid(db, name=STW) -> int:
    return scalar(db, f"SELECT id FROM products WHERE name = '{name}'")


def price(db, product_id: int, size: int | None) -> int | None:
    where = "size_ml IS NULL" if size is None else f"size_ml = {size}"
    return scalar(db, f"SELECT price_mmk FROM product_prices WHERE product_id = {product_id} AND {where} "
                      "ORDER BY effective_from DESC, id DESC LIMIT 1")


def head(page: str) -> str:
    return page[page.index('class="page-head"'):page.index('class="toolbar"')]


def test_one_page_two_buttons_no_tabs_no_messages_column(shop, db):  # noqa: F811
    client, _ = shop
    page = client.get("/products").text
    top = head(page)
    assert 'href="/stock"' not in page and 'class="tabs"' not in top  # no Products / Prices / Stock tabs
    buttons = re.findall(r'class="button[^"]*"', top)
    assert len(buttons) == 2 and "+ Add perfume" in top and "More" in top
    for item in ("Download prices (Excel)", "Upload prices (Excel)", "Upload first stock count (Excel)", "Empty vials"):
        assert item in top
    assert ">Perfume<" in page and ">Stock<" in page and ">Nicknames<" in page and ">Messages<" not in page
    assert 'id="panel" hidden' in page  # closed


def test_panel_opens_by_url_with_three_tabs_and_old_url_redirects(shop, db):  # noqa: F811
    client, _ = shop
    stw = pid(db)
    r = client.get(f"/products/{stw}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/products?open={stw}&tab=prices"
    page = client.get(f"/products?open={stw}&tab=stock").text
    panel = page[page.index('id="panel"'):]
    assert 'class="side-panel"' in page and "data-close" in panel
    assert re.search(r'id="pane-stock"(?! hidden)', panel) and 'id="pane-prices" hidden' in panel
    assert 'id="pane-nicks" hidden' in panel and "Stock for this perfume is not counted yet." in panel
    assert client.get("/products/999999").status_code == 404


def test_prices_tab_saves_all_sizes_once_and_staff_only_view(shop, db):  # noqa: F811
    client, token = shop
    stw = pid(db)
    page = client.get(f"/products?open={stw}").text
    assert 'name="price_5"' in page and 'value="18,000"' in page and "Save prices" in page
    r = client.post(f"/products/{stw}/prices", data={"csrf": token, "price_2": "8,000", "price_5": "19,000",
                                                     "price_10": "", "price_full": "380000"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/products?open={stw}&tab=prices"
    assert price(db, stw, 5) == 19000 and price(db, stw, 10) is None and price(db, stw, None) == 380000
    rows = scalar(db, f"SELECT count(*) FROM product_prices WHERE product_id = {stw}")
    client.post(f"/products/{stw}/prices", data={"csrf": token, "price_2": "8000", "price_5": "19000",
                                                 "price_10": "", "price_full": "380,000"})
    assert scalar(db, f"SELECT count(*) FROM product_prices WHERE product_id = {stw}") == rows  # no change, no rows
    assert client.post(f"/products/{stw}/prices", data={"csrf": token, "price_5": "-3"}).status_code == 400
    staff, staff_token = staff_client(db)
    page = staff.get(f"/products?open={stw}").text
    assert "Only the owner can change prices." in page and "Save prices" not in page and "readonly" in page
    assert 'class="head-actions"' not in page and 'method="post" action="/products"' not in page
    assert staff.post(f"/products/{stw}/prices", data={"csrf": staff_token, "price_5": "1"}).status_code == 403


def test_stock_tab_add_bottle_fix_amount_and_available_switch(shop, db):  # noqa: F811
    client, token = shop
    stw, y = pid(db), pid(db, "Y Eau de Parfum")
    back = f"/products?open={stw}&tab=stock"
    r = client.post(f"/stock/bottles?back={back.replace('&', '%26')}",
                    data={"csrf": token, "product_id": str(stw), "size_ml": "100", "count": "1", "cost_mmk": "250000"},
                    follow_redirects=False)
    assert r.headers["location"] == back
    page = client.get(back).text
    assert "100.0</b> ml left" in page and "+ Add bottle" in page and "Fix the amount" in page
    assert "See what changed (history)" in page
    bottle = scalar(db, f"SELECT id FROM bottles WHERE product_id = {stw}")
    r = client.post(f"/stock/adjust?back={back.replace('&', '%26')}",
                    data={"csrf": token, "bottle_id": str(bottle), "remaining_ml": "90", "reason": "count"},
                    follow_redirects=False)
    assert r.headers["location"] == back and scalar(db, "SELECT remaining_ml FROM bottles") == 90
    assert client.post("/stock/adjust?back=//evil.example", data={"csrf": token, "bottle_id": "999999",
                       "remaining_ml": "1", "reason": "x"}, follow_redirects=False).headers["location"] == "/stock"
    # not counted: one switch = the old manual in-stock flag
    page = client.get(f"/products?open={y}&tab=stock").text
    assert "Start counting" in page and 'role="switch" aria-checked="false"' in page  # Y is sold out
    client.post(f"/products/{y}/available", data={"csrf": token, "available": "1"})
    assert scalar(db, f"SELECT bool_and(in_stock) FROM (SELECT DISTINCT ON (size_ml) in_stock FROM product_prices "
                      f"WHERE product_id = {y} ORDER BY size_ml, effective_from DESC, id DESC) x")


def test_nicknames_tab_add_remove_and_the_parser_knows_it(shop, db):  # noqa: F811
    client, token = shop
    stw = pid(db)
    r = client.post(f"/products/{stw}/aliases", data={"csrf": token, "alias": "swy int"}, follow_redirects=False)
    assert r.headers["location"] == f"/products?open={stw}&tab=nicks"
    page = client.get(r.headers["location"]).text
    assert "swy int" in page and "chip-x" in page and "Customers wrote this perfume" in page
    add_message(50, "swy int 5ml")
    run_batch()
    assert scalar(db, "SELECT p.product_id FROM parse_results p JOIN messages m ON m.id = p.message_id "
                      "WHERE m.external_message_id = '50' AND p.is_current") == stw
    alias = scalar(db, "SELECT id FROM product_aliases WHERE normalized_alias = 'swy int'")
    client.post(f"/products/{stw}/aliases/{alias}/delete", data={"csrf": token})
    assert scalar(db, "SELECT count(*) FROM product_aliases WHERE normalized_alias = 'swy int'") == 0


def test_warning_bar_only_when_needed_and_show_only_these(shop, db):  # noqa: F811
    client, _ = shop
    assert 'class="warn-bar"' not in client.get("/products").text  # nothing counted yet
    stw, sauvage = pid(db), pid(db, "Sauvage Eau de Parfum")
    with SessionLocal.begin() as s:
        stock.add_bottles(s, stw, 100, 1, None, None, None)
        stock.add_bottles(s, sauvage, 100, 1, None, 6, None)  # below the 10 ml low line
    page = client.get("/products").text
    bar = page[page.index('class="warn-bar"'):page.index('class="toolbar"')]
    assert "1 perfume needs more stock:" in bar and "Sauvage Eau de Parfum</b> (low)" in bar and STW not in bar
    assert 'href="/products?need=1"' in bar
    only = client.get("/products?need=1").text
    rows = only[only.index('id="product-list"'):]
    assert "Sauvage Eau de Parfum" in rows and STW not in rows and "Show all" in only
    assert "badge st-low" in page and "badge st-ok" in page and "badge st-none" in page  # Low / In stock / Not tracked


def test_add_perfume_dialog_with_prices_and_nicknames(shop, db):  # noqa: F811
    client, token = shop
    page = client.get("/products?dialog=add").text
    assert 'role="dialog"' in page and 'name="price_full"' in page and 'name="nicknames"' in page
    r = client.post("/products", data={"csrf": token, "brand": "Creed", "name": "Aventus", "price_5": "65,000",
                                       "price_full": "1150000", "nicknames": "aventus edp, အဗင်တပ်စ်"},
                    follow_redirects=False)
    new = pid(db, "Aventus")
    assert r.headers["location"] == f"/products/{new}" and price(db, new, 5) == 65000 and price(db, new, None) == 1150000
    assert scalar(db, f"SELECT count(*) FROM product_aliases WHERE product_id = {new}") == 3
    staff, _ = staff_client(db)
    assert 'role="dialog"' not in staff.get("/products?dialog=add").text


def test_old_urls_and_where_the_hidden_functions_went(shop, db):  # noqa: F811
    client, _ = shop
    assert client.get("/prices", follow_redirects=False).headers["location"] == "/products?dialog=prices"
    page = client.get("/prices").text
    assert 'role="dialog"' in page and "Download current prices" in page and 'action="/prices/import"' in page
    assert client.get("/stock", follow_redirects=False).headers["location"] == "/settings?section=inventory"
    settings = client.get("/settings?section=inventory").text
    for moved in ('id="stock-overview"', 'action="/stock/settings"', 'id="history"',
                  'action="/stock/bottles"', "Stock value at cost"):
        assert moved in settings, moved
    assert 'action="/stock/import"' in client.get("/products?dialog=stock-count").text
    assert 'action="/stock/vials?back=' in client.get("/products?dialog=vials").text
    staff, _ = staff_client(db)
    assert staff.get("/stock", follow_redirects=False).headers["location"] == "/products"
