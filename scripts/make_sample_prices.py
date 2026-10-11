"""Write data/sample_prices.xlsx: TEST prices (not real) for the 20 products in
data/products.csv, to try the price-list upload.

Usage: python -m scripts.make_sample_prices [--out data/sample_prices.xlsx]
"""
import argparse
from pathlib import Path

from app.pricing.excel import write_workbook

# brand, name, bottle ml, full price, 2ml, 5ml, 10ml, in stock
SAMPLE = [
    ("Emporio Armani", "Stronger With You Intensely", 100, 380_000, 8_000, 18_000, 33_000, True),
    ("Emporio Armani", "Stronger With You", 100, 330_000, 7_000, 16_000, 30_000, True),
    ("Dior", "Sauvage Eau de Parfum", 100, 420_000, 9_000, 20_000, 38_000, True),
    ("Dior", "Sauvage Elixir", 60, 520_000, 12_000, 28_000, 52_000, True),
    ("Dior", "Miss Dior", 100, 450_000, 9_000, 21_000, 40_000, True),
    ("Chanel", "Bleu de Chanel Eau de Parfum", 100, 480_000, 10_000, 23_000, 43_000, True),
    ("Giorgio Armani", "Acqua di Gio Profumo", 75, 400_000, 10_000, 23_000, 43_000, True),
    ("Yves Saint Laurent", "Y Eau de Parfum", 100, 380_000, 8_000, 18_000, 34_000, True),
    ("Yves Saint Laurent", "Libre", 90, 420_000, 9_000, 21_000, 40_000, True),
    ("Versace", "Eros", 100, 260_000, 6_000, 14_000, 25_000, True),
    ("Paco Rabanne", "1 Million", 100, 270_000, 6_000, 14_000, 26_000, True),
    ("Jean Paul Gaultier", "Le Male Elixir", 125, 400_000, 8_000, 17_000, 32_000, True),
    ("Jean Paul Gaultier", "Ultra Male", 125, 330_000, 7_000, 15_000, 28_000, True),
    ("Creed", "Aventus", 100, 1_150_000, 28_000, 65_000, 125_000, True),
    ("Maison Francis Kurkdjian", "Baccarat Rouge 540", 70, 1_250_000, 35_000, 85_000, 165_000, True),
    ("Tom Ford", "Ombre Leather", 100, 650_000, 14_000, 32_000, 60_000, True),
    ("Valentino", "Born in Roma Uomo Intense", 100, 400_000, 8_000, 19_000, 36_000, False),
    ("Prada", "Luna Rossa Carbon", 100, 300_000, None, 15_000, 28_000, True),
    ("Carolina Herrera", "Good Girl", 80, 420_000, 9_000, 21_000, 40_000, True),
    ("Lancome", "La Vie Est Belle", 100, 400_000, 8_000, 19_000, 36_000, True),
]
SIZES = [2, 5, 10]


def sample_rows() -> list[dict]:
    return [
        {"brand": b, "name": n, "full_size_ml": ml, "full_price": full,
         "prices": {s: p for s, p in zip(SIZES, decants) if p}, "in_stock": stock}
        for b, n, ml, full, *decants, stock in SAMPLE
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("data/sample_prices.xlsx"))
    out = parser.parse_args().out
    out.write_bytes(write_workbook(sample_rows(), SIZES))
    print(f"wrote {out} ({len(SAMPLE)} products)")


if __name__ == "__main__":
    main()
