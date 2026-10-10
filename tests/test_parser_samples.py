"""Check the parser against the owner's labelled real messages.

data/sample_messages.csv holds customer messages, so it is git-ignored and this
test is skipped where the file does not exist. Make it with
scripts/export_samples.py, then correct the intent/product/size_ml columns.
Products are matched by name against data/products.csv + data/aliases.csv.
"""
import csv
from pathlib import Path

import pytest

from app.parser.normalize import normalize
from app.parser.rules import Alias, parse

DATA = Path(__file__).parent.parent / "data"
SAMPLES = DATA / "sample_messages.csv"


def load_samples() -> list[dict]:
    if not SAMPLES.exists():
        return []
    with SAMPLES.open(newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("intent")]


def load_aliases() -> tuple[list[Alias], dict[int, str]]:
    with (DATA / "products.csv").open(newline="", encoding="utf-8-sig") as f:
        names = [r["name"].strip() for r in csv.DictReader(f)]
    ids = {name: i for i, name in enumerate(names, 1)}
    with (DATA / "aliases.csv").open(newline="", encoding="utf-8-sig") as f:
        aliases = [Alias(ids[r["product_name"].strip()], normalize(r["alias"]))
                   for r in csv.DictReader(f) if r["product_name"].strip() in ids]
    return aliases, {i: n for n, i in ids.items()}


SAMPLE_ROWS = load_samples()


@pytest.mark.skipif(not SAMPLE_ROWS, reason="no labelled data/sample_messages.csv on this machine")
@pytest.mark.parametrize("row", SAMPLE_ROWS, ids=[r["message_id"] for r in SAMPLE_ROWS])
def test_sample(row):
    aliases, names = load_aliases()
    r = parse(normalize(row["text"]), aliases)
    got = (r.intent, names.get(r.product_id, ""), str(r.size_ml or ""))
    assert got == (row["intent"], row["product"], row["size_ml"])
