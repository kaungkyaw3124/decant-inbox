"""docs/SPEC-v4.12-address-payment-ai.md N0: find saved addresses that the validator does not accept
(e.g. "လိပ်စာ ပြောင်းချင်ပါတယ်", text shorter than 8 characters, only keywords, no township) and mark them
address_invalid = true. Nothing is rewritten: the dashboard shows a red badge, payment info /
approval / the confirmation are blocked for those orders, and a person fixes the address (cart
panel, or "Edit locked order" for a paid one). Valid addresses get their split (address_parts).

Prints ids and reasons only (never the address text). Run again any time: it is idempotent.
Usage: .venv/bin/python -m scripts.repair_addresses [--dry-run]
"""
import argparse
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Customer, Order
from app.orders import address


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="only print, change nothing")
    args = parser.parse_args()
    bad = 0
    with SessionLocal.begin() as session:
        rows = [("order", o, f"#{o.order_no}" if o.order_no else "no order ID", o.status)
                for o in session.scalars(select(Order).where(Order.address.is_not(None), Order.address != "").order_by(Order.id))]
        rows += [("customer", c, "", "") for c in session.scalars(
            select(Customer).where(Customer.address.is_not(None), Customer.address != "").order_by(Customer.id))]
        for kind, row, number, status in rows:
            check = address.validate(row.address)
            if check.valid:
                if not args.dry_run:
                    row.address_parts, row.address_invalid = row.address_parts or check.parts.to_json(), False
                continue
            bad += 1
            print(f"{kind} id={row.id} {number} {status}: invalid ({check.reason})".replace("  ", " "))
            if not args.dry_run:
                row.address_invalid = True
        if args.dry_run:
            session.rollback()
    print(f"{bad} invalid address(es){' (dry run, nothing changed)' if args.dry_run else ' marked'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
