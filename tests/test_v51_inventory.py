"""docs/SPEC-v5.1-inventory.md: availability, packed deducts (opens the next bottle), undo / cancel give back,
blocked when short, vials, automatic in_stock + the bot's size question, Excel import preview, history, alert."""
import io
from datetime import UTC, datetime

from openpyxl import Workbook
from sqlalchemy import text

from app.core.db import SessionLocal
from app.inventory import stock
from app.orders import actions, cart
from tests.test_after_payment import paid_order, status, tap, undo_last
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def pid(db, name="Stronger With You Intensely") -> int:
    return scalar(db, "SELECT id FROM products WHERE name = :n", n=name)


def bottles(db, product_id: int) -> list[tuple]:
    with db.connect() as c:
        return [(s, float(r)) for s, r in c.execute(text(
            "SELECT status, remaining_ml FROM bottles WHERE product_id = :p ORDER BY id"), {"p": product_id})]


def vial_count(db, size: int) -> int:
    return scalar(db, "SELECT count FROM vials WHERE size_ml = :s", s=size)


def add(db, product_id, size, remaining=None, count=1, cost=None):
    with SessionLocal.begin() as s:
        stock.add_bottles(s, product_id, size, count, cost, remaining, None)


def vials(size, change):
    with SessionLocal.begin() as s:
        stock.change_vials(s, size, change, 300, "test", None)


def test_availability_math():
    level = stock.Level(1, open_ml=10.3, sealed=[])
    assert stock.sellable(level, 10, {}, 0.3) and not stock.sellable(stock.Level(1, 10.2), 10, {}, 0.3)
    assert not stock.sellable(level, None, {}, 0.3)  # a full bottle needs a sealed one
    assert stock.sellable(stock.Level(1, 0, [100]), None, {}, 0.3)
    assert not stock.sellable(level, 5, {5: 0}, 0.3) and stock.sellable(level, 5, {5: 1}, 0.3)
    assert stock.sellable(level, 2, {5: 0}, 0.3)  # a vial size never entered is not checked
    assert stock.Level(1, 3.5, [100, 50]).available_ml == 153.5


def test_in_stock_is_automatic_only_for_perfumes_with_bottles(shop, db):  # noqa: F811
    stw, sauvage = pid(db), pid(db, "Sauvage Eau de Parfum")
    with SessionLocal() as s:
        assert cart.price_of(s, stw, 5, False) == (18000, True)  # manual flag (no bottles yet)
    add(db, stw, 100, remaining=3)
    with SessionLocal() as s:
        assert cart.price_of(s, stw, 2, False) == (8000, True)
        assert cart.price_of(s, stw, 5, False) == (18000, False)  # 3 ml can't fill 5 ml (+0.3 spill)
        assert cart.price_of(s, stw, None, True) == (380000, False)  # no sealed bottle
        assert [p.size_ml for p in actions._sold_sizes(s, stw)] == [2]  # the bot's size question offers 2 ml only
        assert cart.price_of(s, sauvage, 5, False) == (20000, True)  # Sauvage: still the manual flag
    add(db, stw, 100)
    with SessionLocal() as s:
        assert [p.size_ml for p in actions._sold_sizes(s, stw)] == [2, 5, 10, None]  # back when stock is added


def test_packed_takes_ml_and_vial_opens_next_bottle_undo_gives_back(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, token = shop
    stw = pid(db)
    add(db, stw, 100)  # OWNER TEST 5.1: 1 bottle of 100 ml, 20 vials of 5 ml
    vials(5, 20)
    order = paid_order(client, token, db, tmp_path, monkeypatch)  # STW 5ml
    tap(client, token, order, "packed")
    assert status(db, order) == "packed"
    assert bottles(db, stw) == [("open", 94.7)] and vial_count(db, 5) == 19
    undo_last(client, token, order)
    assert status(db, order) == "paid" and bottles(db, stw) == [("open", 100.0)] and vial_count(db, 5) == 20
    tap(client, token, order, "packed")  # again: taken again once
    assert bottles(db, stw) == [("open", 94.7)] and vial_count(db, 5) == 19
    client.post(f"/orders/{order}/cancel", data={"csrf": token, "note": "test", "message": "none"})
    assert status(db, order) == "cancelled" and bottles(db, stw) == [("open", 100.0)] and vial_count(db, 5) == 20
    kinds = [k for k, in db.connect().execute(text("SELECT kind FROM stock_moves WHERE order_id = :o ORDER BY id"),
                                              {"o": order})]
    assert kinds == ["decant", "decant", "return", "return", "decant", "decant", "return", "return"]
    assert "94.7" not in client.get("/stock").text and "decant" in client.get("/stock").text  # history


def test_open_bottle_first_then_the_sealed_one_and_blocked_when_short(shop, db, tmp_path, monkeypatch):  # noqa: F811
    client, token = shop
    stw = pid(db)
    add(db, stw, 100, remaining=3)
    order = paid_order(client, token, db, tmp_path, monkeypatch)
    tap(client, token, order, "packed")  # 5.3 ml needed, 3 ml open: blocked, nothing changes
    assert status(db, order) == "paid" and bottles(db, stw) == [("open", 3.0)]
    assert "Not enough stock" in client.get("/orders").text
    add(db, stw, 50)
    tap(client, token, order, "packed")
    assert bottles(db, stw) == [("empty", 0.0), ("open", 47.7)]  # the old one emptied, the sealed one opened


def test_full_bottle_sale_and_give_back_sealed(shop, db):  # noqa: F811
    stw = pid(db)
    add(db, stw, 100)
    with SessionLocal.begin() as s:
        s.execute(text("INSERT INTO customers (channel, external_user_id, display_name) VALUES ('telegram', '9', 'x')"))
        cid = s.execute(text("SELECT id FROM customers WHERE external_user_id = '9'")).scalar()
        oid = s.execute(text("INSERT INTO orders (customer_id, status, phones, order_no, total_mmk, paid_at) VALUES "
                             "(:c, 'packed', '{}', 5001, 380000, now()) RETURNING id"), {"c": cid}).scalar()
        s.execute(text("INSERT INTO order_items (order_id, product_id, size_ml, is_full_bottle, quantity, unit_price_mmk) "
                       "VALUES (:o, :p, NULL, true, 1, 380000)"), {"o": oid, "p": stw})
    from app.models import Order
    with SessionLocal.begin() as s:
        stock.sync(s, s.get(Order, oid), None)
    assert bottles(db, stw) == [("empty", 0.0)]
    with SessionLocal.begin() as s:
        order = s.get(Order, oid)
        order.status = "cancelled"
        stock.sync(s, order, None)
    assert bottles(db, stw) == [("sealed", 100.0)]


def test_stock_page_adjust_import_preview_and_low_stock_alert(shop, db):  # noqa: F811
    client, token = shop
    stw = pid(db)
    page = client.get("/stock").text
    assert "No bottles yet" in page and 'action="/stock/bottles"' in page
    client.post("/stock/bottles", data={"csrf": token, "product_id": str(stw), "size_ml": "100", "count": "1",
                                        "cost_mmk": "250000"})
    bottle = scalar(db, "SELECT id FROM bottles")
    r = client.post(f"/stock/bottles/{bottle}/adjust", data={"csrf": token, "remaining_ml": "8", "reason": ""})
    assert scalar(db, "SELECT remaining_ml FROM bottles") == 100  # a reason is required
    client.post(f"/stock/bottles/{bottle}/adjust", data={"csrf": token, "remaining_ml": "8", "reason": "count"})
    assert bottles(db, stw) == [("open", 8.0)]
    page = client.get("/stock").text
    assert 'id="reorder"' in page and "Stronger With You Intensely" in page.split('id="reorder"')[1][:600]
    assert "20,000" in page  # value at cost: 8/100 x 250,000
    with SessionLocal() as s:
        assert stock.low_lines(s) == ["Stronger With You Intensely: 8 ml left"]
        from app.alerts import service as alerts
        assert "Low stock: Stronger With You Intensely: 8 ml left" in alerts.daily_summary(s, datetime.now(UTC))
    wb = Workbook()
    ws = wb.active
    ws.title = "Bottles"
    ws.append(("brand", "name", "bottle_ml", "remaining_ml", "cost_mmk"))
    ws.append(("Dior", "Sauvage Eau de Parfum", 100, 60, 300000))
    ws.append(("Nobody", "Unknown Perfume", 50, None, None))
    v = wb.create_sheet("Vials")
    v.append(("size_ml", "count", "cost_each_mmk"))
    v.append((5, 30, 400))
    buf = io.BytesIO()
    wb.save(buf)
    page = client.post("/stock/import", data={"csrf": token},
                       files={"file": ("s.xlsx", buf.getvalue(), "application/octet-stream")}).text
    assert "Unknown Perfume" in page and "not in the product list" in page and 'name="payload"' not in page
    ws.delete_rows(3)
    buf = io.BytesIO()
    wb.save(buf)
    page = client.post("/stock/import", data={"csrf": token},
                       files={"file": ("s.xlsx", buf.getvalue(), "application/octet-stream")}).text
    payload = page.split('name="payload" value="')[1].split('"')[0]
    assert scalar(db, "SELECT count(*) FROM bottles") == 1  # preview only
    client.post("/stock/import/confirm", data={"csrf": token, "payload": payload})
    assert bottles(db, pid(db, "Sauvage Eau de Parfum")) == [("open", 60.0)] and vial_count(db, 5) == 30
    assert client.get("/stock/export.xlsx").status_code == 200


def test_staff_sees_stock_but_cannot_change_it(shop, db):  # noqa: F811
    from tests.test_v4_roles import staff_client

    staff, token = staff_client(db)
    page = staff.get("/stock")
    assert page.status_code == 200 and 'action="/stock/bottles"' not in page.text
    assert staff.post("/stock/vials", data={"csrf": token, "size_ml": "5", "change": "10"}).status_code == 403
