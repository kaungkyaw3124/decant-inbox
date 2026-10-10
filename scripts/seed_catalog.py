"""Sync products and seed aliases from data/products.csv and data/aliases.csv.

Safe to re-run: products are upserted on (brand, name) and seed aliases on
(product_id, normalized_alias). The CSVs are the source of truth for the seed:
- products missing from products.csv are set active=false (never deleted;
  messages and parse results may reference them),
- aliases with source='seed' missing from aliases.csv are deleted.
Learned aliases (source='learned') are never touched.

Usage: python -m scripts.seed_catalog [--data-dir data]
"""
import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.models import Product, ProductAlias
from app.parser.normalize import normalize


def read_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            sys.exit(f"{path}: header must be {','.join(columns)}, got {reader.fieldnames}")
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    return [r for r in rows if all(r.values())]


def seed(data_dir: Path) -> dict[str, int]:
    products = read_csv(data_dir / "products.csv", ["brand", "name"])
    aliases = read_csv(data_dir / "aliases.csv", ["product_name", "alias"])

    with SessionLocal.begin() as session:
        keys = {(p["brand"], p["name"]) for p in products}
        if keys:
            session.execute(
                insert(Product)
                .values([{"brand": b, "name": n, "active": True} for b, n in sorted(keys)])
                .on_conflict_do_update(index_elements=["brand", "name"], set_={"active": True})
            )
        deactivated = session.execute(
            update(Product)
            .where(Product.active, tuple_(Product.brand, Product.name).not_in(keys or {("", "")}))
            .values(active=False)
        ).rowcount

        by_name: dict[str, list[int]] = {}
        for p in session.execute(select(Product).where(Product.active)).scalars():
            by_name.setdefault(p.name, []).append(p.id)

        wanted: dict[tuple[int, str], str] = {}
        for a in aliases:
            ids = by_name.get(a["product_name"])
            if not ids:
                sys.exit(f"aliases.csv: product_name {a['product_name']!r} is not in products.csv")
            if len(ids) > 1:
                sys.exit(f"aliases.csv: product_name {a['product_name']!r} matches several brands")
            wanted[(ids[0], normalize(a["alias"]))] = a["alias"]

        if wanted:
            stmt = insert(ProductAlias).values([
                {"product_id": pid, "normalized_alias": norm, "alias_text": text, "source": "seed"}
                for (pid, norm), text in wanted.items()
            ])
            session.execute(stmt.on_conflict_do_update(
                index_elements=["product_id", "normalized_alias"],
                set_={"alias_text": stmt.excluded.alias_text},
            ))
        removed = session.execute(
            delete(ProductAlias).where(
                ProductAlias.source == "seed",
                tuple_(ProductAlias.product_id, ProductAlias.normalized_alias)
                .not_in(set(wanted) or {(0, "")}),
            )
        ).rowcount

        return {
            "products_in_csv": len(keys),
            "products_deactivated": deactivated,
            "seed_aliases_in_csv": len(wanted),
            "seed_aliases_removed": removed,
            "active_products_total": session.scalar(
                select(func.count()).select_from(Product).where(Product.active)),
            "aliases_total": session.scalar(select(func.count()).select_from(ProductAlias)),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    for key, value in seed(parser.parse_args().data_dir).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
