"""Check the parser against labelled messages (columns: message_id,text,intent,product,size_ml
and optional items, phone).

items (rules-2): "; "-separated, each "Name size" / "Name full" / "?unknown text size" /
"? size" (no product), with " xN" for quantity; empty = not checked. Bottle sizes come
from scripts/make_sample_prices.py, so "100ml" of a 100ml bottle is a full bottle.

- tests/fixtures/synthetic_messages.csv: made-up messages, committed, always run.
- data/sample_messages.csv: the owner's labelled real messages. It holds customer
  messages, so it is git-ignored and skipped where it does not exist. Make it with
  scripts/export_samples.py, then correct the intent/product/size_ml columns.
Products are matched by name against data/products.csv + data/aliases.csv.
"""
import csv
from pathlib import Path

import pytest

from app.parser.normalize import normalize
from app.parser.rules import Alias, parse
from scripts.make_sample_prices import SAMPLE

DATA = Path(__file__).parent.parent / "data"
SAMPLES = DATA / "sample_messages.csv"
SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic_messages.csv"


def load_samples(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("intent")]


def load_aliases() -> tuple[list[Alias], dict[int, str]]:
    with (DATA / "products.csv").open(newline="", encoding="utf-8-sig") as f:
        names = [r["name"].strip() for r in csv.DictReader(f)]
    ids = {name: i for i, name in enumerate(names, 1)}
    with (DATA / "aliases.csv").open(newline="", encoding="utf-8-sig") as f:
        aliases = [Alias(ids[r["product_name"].strip()], normalize(r["alias"]))
                   for r in csv.DictReader(f) if r["product_name"].strip() in ids]
    return aliases, {i: n for n, i in ids.items()}


SYNTHETIC_ROWS = load_samples(SYNTHETIC)
SAMPLE_ROWS = load_samples(SAMPLES)


def full_sizes(names: dict[int, str]) -> dict[int, int]:
    by_name = {name: ml for _, name, ml, *_ in SAMPLE}
    return {pid: by_name[name] for pid, name in names.items() if name in by_name}


def describe(item, names: dict[int, str]) -> str:
    name = names.get(item.product_id) or (f"?{item.unknown_text}" if item.unknown_text else "?")
    size = "full" if item.is_full_bottle else str(item.size_ml or "")
    qty = f" x{item.quantity}" if item.quantity > 1 else ""
    return " ".join(p for p in (name, size) if p) + qty


def check(row: dict) -> None:
    aliases, names = load_aliases()
    r = parse(normalize(row["text"], keep_newlines=True), aliases, full_sizes(names))
    got = (r.intent, names.get(r.product_id, ""), str(r.size_ml or ""))
    assert got == (row["intent"], row["product"], row["size_ml"])
    if row.get("items"):
        assert "; ".join(describe(i, names) for i in r.items) == row["items"]
    if row.get("phone") is not None:
        assert (r.phone or "") == row["phone"]


def test_synthetic_fixture_is_not_empty():
    assert len(SYNTHETIC_ROWS) >= 30


@pytest.mark.parametrize("row", SYNTHETIC_ROWS, ids=[r["message_id"] for r in SYNTHETIC_ROWS])
def test_synthetic(row):
    check(row)


@pytest.mark.skipif(not SAMPLE_ROWS, reason="no labelled data/sample_messages.csv on this machine")
@pytest.mark.parametrize("row", SAMPLE_ROWS, ids=[r["message_id"] for r in SAMPLE_ROWS])
def test_sample(row):
    check(row)
