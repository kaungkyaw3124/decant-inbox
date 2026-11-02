"""docs/SPEC-v5.1-inventory.md: stock as Excel, for the first count (same upload -> preview -> confirm as prices).

Sheet "Bottles": brand | name | bottle_ml | remaining_ml | cost_mmk     (one row per bottle; remaining =
bottle_ml or empty -> sealed; less -> open). Sheet "Vials": size_ml | count | cost_each_mmk.
Importing ADDS what the file lists (purchase moves); it never deletes stock. Export = what is in stock now.
"""
import io
from dataclasses import asdict, dataclass

from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bottle, Product, Vial

BOTTLE_HEAD = ("brand", "name", "bottle_ml", "remaining_ml", "cost_mmk")
VIAL_HEAD = ("size_ml", "count", "cost_each_mmk")


class SheetError(Exception):
    pass


@dataclass
class BottleRow:
    line: int
    product_id: int
    label: str
    bottle_ml: int
    remaining_ml: float
    cost_mmk: int | None


@dataclass
class VialRow:
    line: int
    size_ml: int
    count: int
    cost_each_mmk: int | None


def export(session: Session) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Bottles"
    ws.append(BOTTLE_HEAD)
    for b, p in session.execute(select(Bottle, Product).join(Product, Product.id == Bottle.product_id)
                                .where(Bottle.status != "empty").order_by(Product.brand, Product.name, Bottle.id)):
        ws.append((p.brand, p.name, b.size_ml, float(b.remaining_ml), b.cost_mmk))
    vs = wb.create_sheet("Vials")
    vs.append(VIAL_HEAD)
    for v in session.scalars(select(Vial).order_by(Vial.size_ml)):
        vs.append((v.size_ml, v.count, v.cost_each_mmk))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _number(value, line: int, column: str, errors: list[str], whole: bool = True, empty=None):
    if value in (None, ""):
        return empty
    try:
        n = float(str(value).replace(",", "").strip())
    except ValueError:
        errors.append(f"row {line}: {column} '{value}' is not a number.")
        return None
    if n < 0 or (whole and n != int(n)):
        errors.append(f"row {line}: {column} must be {'a whole number' if whole else 'a number'} of 0 or more.")
        return None
    return int(n) if whole else n


def read(session: Session, data: bytes) -> tuple[list[BottleRow], list[VialRow], list[str]]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise SheetError("Not an Excel file (.xlsx).") from None
    products = {(p.brand.strip().lower(), p.name.strip().lower()): p for p in session.scalars(select(Product))}
    bottles, vials, errors = [], [], []
    if "Bottles" in wb.sheetnames:
        rows = list(wb["Bottles"].iter_rows(values_only=True))
        if not rows or tuple(str(c or "").strip().lower() for c in rows[0][:5]) != BOTTLE_HEAD:
            raise SheetError("Sheet Bottles: the first row must be " + " | ".join(BOTTLE_HEAD) + ".")
        for line, row in enumerate(rows[1:], start=2):
            row = tuple(row) + (None,) * 5
            if not any(row[:5]):
                continue
            p = products.get((str(row[0] or "").strip().lower(), str(row[1] or "").strip().lower()))
            if p is None:
                errors.append(f"row {line}: '{row[0]} {row[1]}' is not in the product list (add it there first).")
                continue
            size = _number(row[2], line, "bottle_ml", errors)
            if not size:
                if row[2] in (None, "") or size == 0:  # (a non-number already has its own error)
                    errors.append(f"row {line}: bottle_ml is needed (more than 0).")
                continue
            remaining = _number(row[3], line, "remaining_ml", errors, whole=False, empty=size)
            if remaining is None:
                continue
            if remaining > size:
                errors.append(f"row {line}: remaining_ml {remaining} is more than the bottle ({size} ml).")
                continue
            cost = _number(row[4], line, "cost_mmk", errors)
            bottles.append(BottleRow(line, p.id, f"{p.brand} {p.name}", size, remaining, cost))
    if "Vials" in wb.sheetnames:
        rows = list(wb["Vials"].iter_rows(values_only=True))
        if rows and tuple(str(c or "").strip().lower() for c in rows[0][:3]) != VIAL_HEAD:
            raise SheetError("Sheet Vials: the first row must be " + " | ".join(VIAL_HEAD) + ".")
        for line, row in enumerate(rows[1:], start=2):
            row = tuple(row) + (None,) * 3
            if not any(row[:3]):
                continue
            size, count = _number(row[0], line, "size_ml", errors), _number(row[1], line, "count", errors)
            if size and count is not None:
                vials.append(VialRow(line, size, count, _number(row[2], line, "cost_each_mmk", errors)))
    if not bottles and not vials and not errors:
        raise SheetError("Nothing to import: fill the Bottles and / or Vials sheet (download the file first).")
    return bottles, vials, errors


def to_payload(bottles: list[BottleRow], vials: list[VialRow]) -> dict:
    return {"bottles": [asdict(b) for b in bottles], "vials": [asdict(v) for v in vials]}


def from_payload(data: dict) -> tuple[list[BottleRow], list[VialRow]]:
    return [BottleRow(**b) for b in data["bottles"]], [VialRow(**v) for v in data["vials"]]
