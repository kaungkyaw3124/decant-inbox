"""Synthetic payment screenshots for the 4.12 screenshot reader (docs/SPEC-v4.12-address-payment-ai.md N3):
KBZPay / AYA Pay / Wave-like receipts with made-up names, amounts and numbers (no real customer data),
plus pictures that are NOT receipts. Writes tests/fixtures/payment_screens/*.png and labels.csv
(the expected reading, used by tests and by scripts/ai_eval.py --screens).

Needs Pillow (only for this script): .venv/bin/pip install Pillow
Usage: .venv/bin/python -m scripts.make_payment_screens
"""
import csv
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from app.core.config import BASE_DIR

OUT = BASE_DIR / "tests" / "fixtures" / "payment_screens"
W, H = 720, 1440


@dataclass(frozen=True)
class Receipt:
    id: str
    app: str  # KBZPay | AYA Pay | Wave | other
    amount: int | None
    transaction_no: str | None
    time: str | None  # as printed
    receiver_name: str | None
    receiver_last4: str | None
    status_text: str | None
    is_receipt: bool
    note: str


RECEIPTS = (
    Receipt("s01", "KBZPay", 34000, "01003456789012345678", "17/10/2026 23:21:05", "Test Shop", "1234",
            "Payment Successful", True, "right amount, right receiver"),
    Receipt("s02", "KBZPay", 70000, "01003456789098765432", "17/10/2026 23:25:41", "Soe Htike Lwin", "7788",
            "Payment Successful", True, "live case: paid more, other receiver"),
    Receipt("s03", "AYA Pay", 18000, "AYA2610171844002931", "17-Oct-2026 18:44", "Test Shop", "1234",
            "Transfer Successful", True, "AYA right"),
    Receipt("s04", "Wave", 25500, "8811223344", "2026-10-16 09:12", "Test Shop", "1234",
            "Successful", True, "Wave right"),
    Receipt("s05", "KBZPay", 30000, "01003456781111222233", "17/10/2026 12:02:10", "Test Shop", "1234",
            "Payment Successful", True, "paid less"),
    Receipt("s06", "KBZPay", 34000, "01003456785555666677", "17/10/2026 13:40:00", "Test Shop", "1234",
            "Transaction Failed", True, "failed transfer"),
    Receipt("s07", "AYA Pay", 52000, "AYA2610090730118842", "09-Oct-2026 07:30", "Mya Mya", "5521",
            "Transfer Successful", True, "old receipt, other receiver"),
    Receipt("s08", "other", None, None, None, None, None, None, False, "not a receipt: a perfume photo"),
    Receipt("s09", "other", None, None, None, None, None, None, False, "not a receipt: a chat screenshot"),
    Receipt("s10", "Wave", 125000, "9900112233", "2026-10-17 20:05", "Test Shop", "1234",
            "Successful", True, "Wave six digits"),
)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def centered(d: ImageDraw.ImageDraw, y: int, text: str, size: int, fill) -> None:
    f = font(size)
    width = d.textlength(text, font=f)
    d.text(((W - width) / 2, y), text, font=f, fill=fill)


def rows(d: ImageDraw.ImageDraw, y: int, pairs: list[tuple[str, str]]) -> None:
    for label, value in pairs:
        d.text((48, y), label, font=font(26), fill=(120, 120, 120))
        f = font(26)
        d.text((W - 48 - d.textlength(value, font=f), y), value, font=f, fill=(20, 20, 20))
        d.line((48, y + 52, W - 48, y + 52), fill=(230, 230, 230), width=2)
        y += 76


def masked(last4: str) -> str:
    return "******" + last4


def receipt(r: Receipt) -> Image.Image:
    colors = {"KBZPay": (13, 78, 166), "AYA Pay": (200, 30, 45), "Wave": (255, 210, 0)}
    head = colors[r.app]
    ink = (20, 20, 20) if r.app == "Wave" else (255, 255, 255)
    img = Image.new("RGB", (W, H), (245, 246, 250))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 160), fill=head)
    centered(d, 40, {"KBZPay": "KBZPay", "AYA Pay": "AYA PAY", "Wave": "Wave Money"}[r.app], 48, ink)
    centered(d, 104, "Transaction Detail", 26, ink)
    d.rounded_rectangle((32, 200, W - 32, H - 120), radius=24, fill=(255, 255, 255))
    ok = "Fail" not in (r.status_text or "")
    mark = (40, 170, 90) if ok else (220, 60, 60)
    d.ellipse((W / 2 - 50, 240, W / 2 + 50, 340), fill=mark)
    centered(d, 268, "OK" if ok else "X", 40, (255, 255, 255))
    centered(d, 370, r.status_text or "", 34, mark)
    centered(d, 430, f"-{r.amount:,}.00 Ks" if r.app == "KBZPay" else f"{r.amount:,} MMK", 60, (20, 20, 20))
    label_no = {"KBZPay": "Transaction No.", "AYA Pay": "Transaction ID", "Wave": "Trans ID"}[r.app]
    rows(d, 560, [
        ("Transaction Time", r.time or ""),
        (label_no, r.transaction_no or ""),
        ("Transaction Type", "Transfer"),
        ("Transfer To", r.receiver_name or ""),
        ("Account", masked(r.receiver_last4 or "0000")),
        ("Amount", f"{r.amount:,}.00 Ks" if r.app != "Wave" else f"{r.amount:,} MMK"),
        ("Notes", "decant"),
    ])
    centered(d, H - 90, "Share     Save Screenshot", 26, (120, 120, 120))
    return img


def perfume_photo() -> Image.Image:
    img = Image.new("RGB", (W, H), (230, 220, 205))
    d = ImageDraw.Draw(img)
    d.rectangle((260, 360, 460, 420), fill=(40, 40, 40))  # cap
    d.rounded_rectangle((180, 420, 540, 1000), radius=30, fill=(60, 90, 140))  # bottle
    d.rectangle((230, 600, 490, 760), fill=(240, 240, 240))
    centered(d, 640, "EAU DE PARFUM", 28, (20, 20, 20))
    centered(d, 690, "100 ml", 28, (20, 20, 20))
    centered(d, 1100, "new arrival  10ml decant", 30, (60, 60, 60))
    return img


def chat_screenshot() -> Image.Image:
    img = Image.new("RGB", (W, H), (220, 230, 240))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 120), fill=(80, 130, 180))
    d.text((40, 40), "Decant Shop", font=font(36), fill=(255, 255, 255))
    bubbles = [(False, "Sauvage 10ml ya la?"), (True, "Sauvage EDP 10ml - 24,000 Ks"),
               (False, "ok take 1"), (True, "Total 24,000 Ks. Phone please"), (False, "09-xxx-xxx")]
    y = 180
    for mine, text in bubbles:
        f = font(28)
        w = d.textlength(text, font=f) + 48
        x = W - 40 - w if mine else 40
        d.rounded_rectangle((x, y, x + w, y + 70), radius=20, fill=(220, 248, 198) if mine else (255, 255, 255))
        d.text((x + 24, y + 18), text, font=f, fill=(20, 20, 20))
        y += 110
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for r in RECEIPTS:
        img = receipt(r) if r.is_receipt else perfume_photo() if r.id == "s08" else chat_screenshot()
        img.save(OUT / f"{r.id}.png", optimize=True)
    with (OUT / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "app", "amount", "transaction_no", "time", "receiver_name", "receiver_last4",
                    "status_text", "is_receipt", "note"])
        for r in RECEIPTS:
            w.writerow([r.id, r.app, r.amount or "", r.transaction_no or "", r.time or "", r.receiver_name or "",
                        r.receiver_last4 or "", r.status_text or "", int(r.is_receipt), r.note])
    print(f"{len(RECEIPTS)} images in {OUT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
