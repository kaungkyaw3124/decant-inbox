"""Price list: Excel reading, preview, apply, history, export round trip, and the web flow."""
import io
import re
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import text

from app.core.db import SessionLocal
from app.pricing import excel
from app.pricing.prices import current_prices
from scripts.make_sample_prices import SAMPLE
from scripts.seed_catalog import seed
from tests.test_seed_catalog import write_csvs
from tests.test_web import client, log_in  # noqa: F401  (fixture)

HEADER = ["brand", "name", "full_size_ml", "full_price", "2ml", "5ml", "10ml", "in_stock"]
STW = ["Emporio Armani", "Stronger With You Intensely", 100, 380000, 8000, 18000, 33000, "yes"]
SAUVAGE = ["Dior", "Sauvage Eau de Parfum", 100, 420000, None, 20000, 38000, "yes"]


def xlsx(*rows, header=HEADER) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def run_import(data: bytes, choices: dict[int, str] | None = None) -> dict[str, int]:
    with SessionLocal.begin() as s:
        sheet = excel.read_sheet(data)
        assert not sheet.errors, sheet.errors
        return excel.apply_import(s, excel.plan_import(s, sheet), choices or {}, None)


def prices_of(name: str) -> dict:
    with SessionLocal() as s:
        pid = s.scalar(text("SELECT id FROM products WHERE name = :n"), {"n": name})
        return {p.size_ml: (p.price_mmk, p.in_stock) for p in current_prices(s, [pid]).get(pid, [])}


@pytest.fixture
def catalog(db, tmp_path):
    seed(write_csvs(tmp_path))


# ---------- reading (no DB) ----------

def test_read_sheet_parses_cells():
    sheet = excel.read_sheet(xlsx(
        ["Dior", "Sauvage Eau de Parfum", "100ml", "420,000 ကျပ်", "-", "၂၀၀၀၀", 38000.0, "NO"],
        [None, None, None, None, None, None, None, None],  # empty row skipped
        header=["Brand", "Name", "full_size_ml", "Full Price", "2 ml", "5ML", "10ml", "in_stock"]))
    assert sheet.errors == [] and sheet.warnings == []
    row = sheet.rows[0]
    assert (row.row, row.full_size_ml, row.in_stock) == (2, 100, False)
    assert row.prices == {"2": None, "5": 20000, "10": 38000, "full": 420000}


def test_read_sheet_reports_bad_cells_and_duplicates():
    sheet = excel.read_sheet(xlsx(
        ["Dior", "Sauvage Eau de Parfum", 100, 420000, "abc", 0, 18.5, "maybe"],
        ["dior", "sauvage eau de parfum", 100, 1, 1, 1, 1, "yes"],
        ["", "No Brand", None, None, None, None, None, None]))
    assert any(e.startswith("E2:") for e in sheet.errors)  # abc
    assert any(e.startswith("F2:") for e in sheet.errors)  # 0
    assert any(e.startswith("G2:") for e in sheet.errors)  # 18.5
    assert any(e.startswith("H2:") for e in sheet.errors)  # maybe
    assert any("already on row 2" in e for e in sheet.errors)
    assert any("Row 4" in e and "required" in e for e in sheet.errors)


def test_read_sheet_headers():
    with pytest.raises(excel.SheetError):
        excel.read_sheet(xlsx(["x", "y"], header=["brand", "product"]))
    with pytest.raises(excel.SheetError):
        excel.read_sheet(b"not a zip file")
    sheet = excel.read_sheet(xlsx(["Dior", "Sauvage Eau de Parfum", 1, 2, 3], header=["brand", "name", "15ml", "notes", "5ml"]))
    assert sheet.rows[0].prices == {"5": 3, "15": 1}
    assert len(sheet.warnings) == 1 and "notes" in sheet.warnings[0]
    sheet = excel.read_sheet(xlsx(["a", "b", 1, 2], header=["brand", "name", "5ml", "5 ml"]))
    assert any("appears twice" in e for e in sheet.errors)


def test_formula_without_cached_value_is_an_error():
    sheet = excel.read_sheet(xlsx(["Dior", "Sauvage Eau de Parfum", "=1000*18"], header=["brand", "name", "5ml"]))
    assert any("formula" in e for e in sheet.errors)


def test_sample_file_is_valid():
    sheet = excel.read_sheet((Path(__file__).parent.parent / "data" / "sample_prices.xlsx").read_bytes())
    assert sheet.errors == [] and sheet.warnings == []
    assert [(r.brand, r.name) for r in sheet.rows] == [(b, n) for b, n, *_ in SAMPLE]
    products_csv = (Path(__file__).parent.parent / "data" / "products.csv").read_text().splitlines()[1:]
    assert sorted(f"{r.brand},{r.name}" for r in sheet.rows) == sorted(products_csv)


# ---------- preview + apply ----------

def test_preview_writes_nothing_and_apply_writes_prices(catalog, db):
    with SessionLocal() as s:
        plan = excel.plan_import(s, excel.read_sheet(xlsx(STW, SAUVAGE)))
    assert [r.status for r in plan.rows] == ["changed", "changed"]
    assert "5ml: not sold → 18,000" in plan.rows[0].changes
    assert plan.untouched == ["Yves Saint Laurent Y Eau de Parfum"]
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM product_prices")).scalar() == 0

    stats = run_import(xlsx(STW, SAUVAGE))
    assert stats == {"products_added": 0, "products_updated": 2, "prices_written": 7}
    assert prices_of("Stronger With You Intensely") == {
        2: (8000, True), 5: (18000, True), 10: (33000, True), None: (380000, True)}
    assert None in prices_of("Sauvage Eau de Parfum") and 2 not in prices_of("Sauvage Eau de Parfum")
    with db.connect() as c:
        assert c.execute(text("SELECT full_size_ml FROM products WHERE name = 'Sauvage Eau de Parfum'")).scalar() == 100

    # Same file again: nothing changes, nothing written.
    with SessionLocal() as s:
        assert [r.status for r in excel.plan_import(s, excel.read_sheet(xlsx(STW, SAUVAGE))).rows] == ["same", "same"]
    assert run_import(xlsx(STW, SAUVAGE))["prices_written"] == 0


def test_history_removal_stock_and_missing_columns(catalog, db):
    run_import(xlsx(STW))
    # price change, 2ml removed (empty cell), out of stock
    changed = ["Emporio Armani", "Stronger With You Intensely", 100, 380000, None, 20000, 33000, "no"]
    with SessionLocal() as s:
        row = excel.plan_import(s, excel.read_sheet(xlsx(changed))).rows[0]
    assert row.changes == ["2ml: 8,000 → not sold", "5ml: 18,000 → 20,000", "in stock: yes → no"]
    run_import(xlsx(changed))
    assert prices_of("Stronger With You Intensely") == {5: (20000, False), 10: (33000, False), None: (380000, False)}
    with db.connect() as c:  # old rows kept: 4 first + 2ml removal + 5ml + stock rows for 10ml and full
        assert c.execute(text("SELECT count(*) FROM product_prices")).scalar() == 8
        assert c.execute(text("SELECT price_mmk FROM product_prices WHERE size_ml = 5 ORDER BY id")).scalars().all() == [18000, 20000]

    # A file with only brand, name and 5ml leaves other sizes and stock alone.
    run_import(xlsx(["Emporio Armani", "Stronger With You Intensely", 21000], header=["brand", "name", "5ml"]))
    assert prices_of("Stronger With You Intensely") == {5: (21000, False), 10: (33000, False), None: (380000, False)}


def test_new_and_ambiguous_products(catalog, db):
    new = ["Creed", "Aventus", 100, 1150000, 28000, 65000, 125000, "yes"]
    typo = ["Dior", "Sauvage Eau de Parfun", 100, 420000, 9000, 20000, 38000, "yes"]
    data = xlsx(new, typo)
    with SessionLocal() as s:
        plan = excel.plan_import(s, excel.read_sheet(data))
    assert [r.status for r in plan.rows] == ["new", "ambiguous"]
    sauvage_id = plan.rows[1].candidates[0][0]
    assert plan.rows[1].candidates[0][1] == "Dior Sauvage Eau de Parfum"

    with pytest.raises(ValueError, match="choose"):  # ambiguous row needs a decision
        run_import(data, {2: "new"})
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM products WHERE name = 'Aventus'")).scalar() == 0

    stats = run_import(data, {2: "new", 3: str(sauvage_id)})
    assert stats["products_added"] == 1 and stats["products_updated"] == 1
    assert prices_of("Aventus")[5] == (65000, True)
    assert prices_of("Sauvage Eau de Parfum")[2] == (9000, True)
    with db.connect() as c:
        assert c.execute(text("SELECT source FROM products WHERE name = 'Aventus'")).scalar() == "excel"
        assert c.execute(text("SELECT normalized_alias FROM product_aliases a JOIN products p ON p.id = a.product_id "
                              "WHERE p.name = 'Aventus'")).scalar() == "aventus"
        assert c.execute(text("SELECT count(*) FROM products WHERE name = 'Sauvage Eau de Parfun'")).scalar() == 0
        assert c.execute(text("SELECT active FROM products WHERE name = 'Aventus'")).scalar() is True


def test_export_round_trip(catalog, db):
    run_import(xlsx(STW, SAUVAGE, ["Creed", "Aventus", 100, 1150000, 28000, 65000, 125000, "no"]), {4: "new"})
    run_import(xlsx(["Creed", "Aventus", 99000], header=["brand", "name", "15ml"]))
    with SessionLocal() as s:
        rows, sizes = excel.export_rows(s)
    assert sizes == [2, 5, 10, 15]
    data = excel.write_workbook(rows, sizes)
    sheet = excel.read_sheet(data)
    assert sheet.errors == []
    assert [r.name for r in sheet.rows] == ["Aventus", "Sauvage Eau de Parfum", "Stronger With You Intensely",
                                            "Y Eau de Parfum"]
    assert sheet.rows[0].prices["15"] == 99000 and sheet.rows[0].in_stock is False
    with SessionLocal() as s:
        plan = excel.plan_import(s, sheet)
    assert [r.status for r in plan.rows] == ["same"] * 4


# ---------- web ----------

def test_prices_pages(client, db):  # noqa: F811
    token = log_in(client)
    assert "Download current prices" in client.get("/prices").text
    r = client.get("/prices/export.xlsx")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith('attachment; filename="prices-')
    assert len(excel.read_sheet(r.content).rows) == 3

    files = {"file": ("prices.xlsx", xlsx(STW), "application/octet-stream")}
    r = client.post("/prices/import", data={"csrf": token}, files=files)
    assert r.status_code == 200 and "5ml: not sold → 18,000" in r.text
    payload = re.search(r'name="payload" value="([^"]+)"', r.text).group(1)
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM product_prices")).scalar() == 0

    # tampered payload is refused
    r = client.post("/prices/import/confirm", data={"csrf": token, "payload": payload[:-2] + "xx"})
    assert r.status_code == 400 and "expired" in r.text

    r = client.post("/prices/import/confirm", data={"csrf": token, "payload": payload}, follow_redirects=False)
    assert r.status_code == 303
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM product_prices")).scalar() == 4
        assert c.execute(text("SELECT action FROM audit_log")).scalar() == "prices.import"
    page = client.get("/products").text
    assert "5ml 18,000" in page and "Full 100ml 380,000" in page
    with db.connect() as c:
        pid = c.execute(text("SELECT id FROM products WHERE name = 'Stronger With You Intensely'")).scalar()
    assert "380,000" in client.get(f"/products/{pid}").text

    # confirming the same preview again: the plan changed (now "same"), so it is refused
    r = client.post("/prices/import/confirm", data={"csrf": token, "payload": payload})
    assert r.status_code == 409


def test_import_with_errors_cannot_be_confirmed(client):  # noqa: F811
    token = log_in(client)
    files = {"file": ("bad.xlsx", xlsx(["Dior", "Sauvage Eau de Parfum", 100, "abc", 1, 2, 3, "yes"]), "x")}
    r = client.post("/prices/import", data={"csrf": token}, files=files)
    assert "Fix these in the file" in r.text and 'name="payload"' not in r.text
    r = client.post("/prices/import", data={"csrf": token}, files={"file": ("x.xlsx", b"junk", "x")})
    assert r.status_code == 400 and "not a valid .xlsx" in r.text


def test_prices_need_login(client):  # noqa: F811
    for path in ("/prices", "/prices/export.xlsx", "/settings"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
