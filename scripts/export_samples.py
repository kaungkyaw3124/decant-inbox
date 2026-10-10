"""Write stored messages to data/sample_messages.csv for the owner to label.

Columns: message_id,text,intent,product,size_ml. intent/product/size_ml are
pre-filled with the parser's current guess; the owner corrects them, and
tests/test_parser_samples.py then checks the parser against the labels.
The file contains customer messages: it is git-ignored and must stay on the server.

Usage: .venv/bin/python -m scripts.export_samples [--limit 300] [--out data/sample_messages.csv]
"""
import argparse
import csv
import os
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Message, ParseResult, Product

COLUMNS = ["message_id", "text", "intent", "product", "size_ml"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--out", type=Path, default=Path("data/sample_messages.csv"))
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; move it away first so labels are not lost")

    with SessionLocal() as session:
        rows = session.execute(
            select(Message.id, Message.raw_text, ParseResult.intent, Product.name, ParseResult.size_ml)
            .outerjoin(ParseResult, (ParseResult.message_id == Message.id) & ParseResult.is_current)
            .outerjoin(Product, Product.id == ParseResult.product_id)
            .order_by(Message.received_at.desc())
            .limit(args.limit)
        ).all()
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for mid, text, intent, product, size in rows:
            writer.writerow([mid, text, intent or "", product or "", size or ""])
    print(f"wrote {len(rows)} rows to {args.out} (mode 600, git-ignored)")


if __name__ == "__main__":
    main()
