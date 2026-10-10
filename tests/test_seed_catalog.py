from pathlib import Path

from sqlalchemy import text

from scripts.seed_catalog import seed

REPO_DATA = Path(__file__).parent.parent / "data"


def write_csvs(tmp_path: Path, products: str, aliases: str) -> Path:
    (tmp_path / "products.csv").write_text("brand,name\n" + products)
    (tmp_path / "aliases.csv").write_text("product_name,alias\n" + aliases)
    return tmp_path


def catalog(engine) -> list[tuple]:
    with engine.connect() as c:
        return list(c.execute(text(
            "SELECT p.id, p.brand, p.name, p.active, a.id, a.normalized_alias, a.source "
            "FROM products p LEFT JOIN product_aliases a ON a.product_id = p.id "
            "ORDER BY p.id, a.id"
        )))


def test_seed_is_idempotent(db):
    seed(REPO_DATA)
    first = catalog(db)
    seed(REPO_DATA)
    assert catalog(db) == first
    assert len({row[0] for row in first}) == 3


def test_aliases_are_normalized(db, tmp_path):
    seed(write_csvs(tmp_path, "Emporio Armani,Stronger With You Intensely\n",
                    "Stronger With You Intensely,STW  Intensely ၁၀ မီလီ\n"))
    assert [row[5] for row in catalog(db)] == ["stw intensely 10 ml"]


def test_replacing_list_deactivates_products_and_drops_seed_aliases(db, tmp_path):
    seed(REPO_DATA)
    with db.begin() as c:  # an alias learned from the dashboard must survive
        c.execute(text(
            "INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
            "SELECT id, 'sauvage', 'sauvage', 'learned' FROM products WHERE brand = 'Dior'"
        ))
    stats = seed(write_csvs(tmp_path, "Creed,Aventus\n", "Aventus,aventus\n"))

    rows = catalog(db)
    active = {(r[1], r[2]) for r in rows if r[3]}
    aliases = {(r[2], r[5], r[6]) for r in rows if r[4] is not None}
    assert active == {("Creed", "Aventus")}
    assert aliases == {("Aventus", "aventus", "seed"), ("Sauvage Eau de Parfum", "sauvage", "learned")}
    assert stats["products_deactivated"] == 3
    assert stats["seed_aliases_removed"] == 7


def test_unknown_product_in_aliases_fails_cleanly(db, tmp_path):
    import pytest

    with pytest.raises(SystemExit, match="not in products.csv"):
        seed(write_csvs(tmp_path, "Creed,Aventus\n", "Sauvage,sauvage\n"))
    assert catalog(db) == []  # whole seed rolled back
