"""AI payment-screenshot reader (docs/SPEC-v4.12-address-payment-ai.md N3).

Only when the owner turned the switch ai_screenshot ON (/ai): screenshots contain names and account
numbers. The picture is read AFTER an admin opened the payment card (photos are downloaded only
then; CLAUDE.md), once per payment check, in the parser worker. Same daily cap and monthly budget as
the message AI; any error -> the card works as before (nothing blocks).

The reading pre-fills the card (amount, transaction no., method) and our code checks it:
not a receipt, amount ≠ total (paid more / less), receiver not one of our accounts, transaction no.
already used, receipt older than the payment info or than 3 days, status not successful.
Every warning needs the existing second confirm to approve. Never approves, never messages the
customer: the admin decides and uses the reject reasons.
"""
import csv
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import providers
from app.ai import settings as ai_settings
from app.ai.providers import AIError
from app.core.config import BASE_DIR, get_settings
from app.core.db import SessionLocal
from app.models import MediaDownload, Order, PaymentCheck, PaymentMethod
from app.models.outbox import MEDIA_DIR
from app.pricing.prices import format_mmk

log = logging.getLogger("ai.screens")
APPS = ("KBZPay", "AYA Pay", "Wave", "CB Pay", "other")
MAX_AGE = timedelta(days=3)
CLOCK_SKEW = timedelta(minutes=10)  # phone clocks: a receipt a few minutes "before" the payment info is fine
NAME_MATCH = 80  # rapidfuzz token_set_ratio, receiver name vs our account name
SUCCESS_RE = re.compile(r"success|completed|ပြီးဆုံး|အောင်မြင်", re.IGNORECASE)
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
FIXTURES = BASE_DIR / "tests" / "fixtures" / "payment_screens"

INSTRUCTIONS = """\
You read ONE picture that a customer of a small perfume shop in Myanmar sent after the shop asked them
to pay. Answer with JSON only. You never talk to the customer; the shop's staff decides.

- is_payment_receipt: true only if the picture is a money-transfer / payment result screen of a mobile
  banking or wallet app (KBZPay, AYA Pay, Wave Money, CB Pay, ...). A product photo, a chat, a price list,
  a bank QR code or a blank screen is NOT a receipt (then every other field is null).
- app: KBZPay, AYA Pay, Wave, CB Pay or other.
- amount: the transferred amount as a whole number of kyats (70,000.00 Ks -> 70000; "-34,000" -> 34000).
  Fees are not part of it. null if you cannot read it.
- currency: as shown (Ks, MMK, ကျပ်).
- transaction_no: the transaction number / ID exactly as printed (all digits / letters, no spaces).
- time: the transaction time exactly as printed; time_iso: the same time as YYYY-MM-DDTHH:MM (24 h).
- receiver_name: the name the money went TO (Transfer To / Receiver / To). receiver_account_last4: the
  last 4 digits of the receiver's number or account if shown, else null.
- status_text: the result text as printed ("Payment Successful", "Transaction Failed", ...).
- confidence 0-1: how sure you are that amount and transaction_no are read correctly.
Never guess digits you cannot see: use null.
"""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_payment_receipt", "app", "amount", "currency", "transaction_no", "time", "time_iso",
                 "receiver_name", "receiver_account_last4", "status_text", "confidence"],
    "properties": {
        "is_payment_receipt": {"type": "boolean"},
        "app": {"type": ["string", "null"], "enum": [*APPS, None]},
        "amount": {"type": ["integer", "null"]},
        "currency": {"type": ["string", "null"]},
        "transaction_no": {"type": ["string", "null"]},
        "time": {"type": ["string", "null"]},
        "time_iso": {"type": ["string", "null"]},
        "receiver_name": {"type": ["string", "null"]},
        "receiver_account_last4": {"type": ["string", "null"]},
        "status_text": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
    },
}


@dataclass(frozen=True)
class Reading:
    is_payment_receipt: bool
    app: str | None
    amount: int | None
    currency: str | None
    transaction_no: str | None
    time: str | None
    time_iso: str | None
    receiver_name: str | None
    receiver_account_last4: str | None
    status_text: str | None
    confidence: float

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Reading":
        """ValueError / TypeError / KeyError when the shape is wrong."""
        def text(key: str, limit: int = 80) -> str | None:
            value = data.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(f"{key}: not a string")
            return value.strip()[:limit] or None

        amount = data["amount"]
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int) or not
                                   0 < amount <= 100_000_000):
            raise ValueError("amount out of range")
        app = data.get("app")
        if app is not None and app not in APPS:
            raise ValueError("unknown app")
        number = text("transaction_no", 64)
        last4 = re.sub(r"\D", "", text("receiver_account_last4", 16) or "")[-4:] or None
        return cls(bool(data["is_payment_receipt"]), app, amount, text("currency", 16),
                   re.sub(r"\s+", "", number) if number else None, text("time", 40), text("time_iso", 25),
                   text("receiver_name"), last4, text("status_text"), float(data["confidence"]))

    @property
    def when(self) -> datetime | None:
        """The receipt time (shop time zone), if the AI could give it."""
        if not self.time_iso:
            return None
        try:
            value = datetime.fromisoformat(self.time_iso)
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=ZoneInfo(get_settings().timezone))


def context_text(total: int, methods: list[PaymentMethod]) -> str:
    """What we tell the AI besides the picture: the expected total and our accounts (name + last 4)."""
    accounts = "; ".join(f"{m.name}: {m.account_name} (…{re.sub(r'[^0-9]', '', m.account_number)[-4:]})"
                         for m in methods) or "(none)"
    return f"EXPECTED TOTAL: {total} Ks\nTHE SHOP'S ACCOUNTS: {accounts}\nRead the picture."


# ---------- checks (our code) ----------

@dataclass(frozen=True)
class Warning:
    kind: str  # not_receipt | paid_more | paid_less | receiver | duplicate | before_payment_info | old | status
    text: str


def _ours(reading: Reading, methods: list[PaymentMethod]) -> bool:
    for m in methods:
        digits = re.sub(r"\D", "", m.account_number or "")
        if reading.receiver_account_last4 and digits.endswith(reading.receiver_account_last4):
            return True
        if reading.receiver_name and m.account_name and fuzz.token_set_ratio(
                reading.receiver_name.lower(), m.account_name.lower()) >= NAME_MATCH:
            return True
    return False


def warnings(session: Session, check: PaymentCheck, order: Order, total: int) -> list[Warning]:
    """Warnings from the stored reading (empty when there is none). Recomputed every time: the total
    or the approved checks may have changed since the picture was read."""
    if not check.ai_read:
        return []
    try:
        r = Reading.from_json(check.ai_read)
    except (KeyError, TypeError, ValueError):
        return []
    if not r.is_payment_receipt or r.confidence < 0.3:
        return [Warning("not_receipt", "The screenshot does not look like a payment receipt (or it is unreadable).")]
    found = []
    if r.amount is not None and r.amount != total:
        more = r.amount > total
        found.append(Warning("paid_more" if more else "paid_less",
                             f"Screenshot amount {format_mmk(r.amount)} ≠ order total {format_mmk(total)} ကျပ်: paid "
                             f"{'more' if more else 'less'} ({format_mmk(abs(r.amount - total))} ကျပ် "
                             f"{'too much' if more else 'missing'})."))
    methods = list(session.scalars(select(PaymentMethod).where(PaymentMethod.active)))
    if (r.receiver_name or r.receiver_account_last4) and not _ours(r, methods):
        shown = " ".join(x for x in (r.receiver_name, f"(…{r.receiver_account_last4})" if r.receiver_account_last4
                                     else None) if x)
        found.append(Warning("receiver", f"Paid to {shown}: not one of our payment accounts."))
    if r.transaction_no:
        used = session.scalar(select(PaymentCheck).where(
            func.lower(PaymentCheck.transaction_id) == r.transaction_no.lower(), PaymentCheck.id != check.id,
            PaymentCheck.decision == "approved"))
        if used is not None:
            other = session.get(Order, used.order_id)
            found.append(Warning("duplicate", f"Transaction no. {r.transaction_no} from the screenshot was already "
                                              f"used for order #{other.order_no}."))
    when = r.when
    if when is not None:
        tz = ZoneInfo(get_settings().timezone)
        if order.payment_info_sent_at and when < order.payment_info_sent_at - CLOCK_SKEW:
            found.append(Warning("before_payment_info", f"Receipt time {when.astimezone(tz):%d %b %H:%M} is before we "
                                                        f"sent the payment info "
                                                        f"({order.payment_info_sent_at.astimezone(tz):%d %b %H:%M})."))
        elif when < check.created_at - MAX_AGE:
            found.append(Warning("old", f"Receipt time {when.astimezone(tz):%d %b %H:%M} is more than 3 days old."))
    if r.status_text and not SUCCESS_RE.search(r.status_text):
        found.append(Warning("status", f"Status on the screenshot: “{r.status_text}” (not successful)."))
    return found


def method_for(reading: Reading | None, methods: list[PaymentMethod]) -> str | None:
    """Our payment method that matches the app on the screenshot (KBZPay = KPay, AYA Pay = AYA ...)."""
    if reading is None or not reading.app or reading.app == "other":
        return None
    key = {"KBZPay": ("kbz", "kpay"), "AYA Pay": ("aya",), "Wave": ("wave",), "CB Pay": ("cb",)}[reading.app]
    return next((m.name for m in methods if any(k in m.name.lower() for k in key)), None)


def reading_of(check: PaymentCheck) -> Reading | None:
    try:
        return Reading.from_json(check.ai_read) if check.ai_read else None
    except (KeyError, TypeError, ValueError):
        return None


# ---------- reading (parser worker) ----------

def enabled(session: Session) -> bool:
    cfg = ai_settings.load(session)
    return bool(cfg["ai_screenshot"]) and cfg["mode"] != "off" and providers.get() is not None


def to_read(session: Session, now: datetime) -> list[int]:
    """Pending checks whose screenshot was downloaded (an admin opened the card) and not read yet."""
    return list(session.scalars(
        select(PaymentCheck.id).join(MediaDownload, MediaDownload.message_id == PaymentCheck.message_id)
        .where(PaymentCheck.decision == "pending", PaymentCheck.ai_status.is_(None), MediaDownload.status == "done",
               PaymentCheck.created_at >= now - MAX_AGE).order_by(PaymentCheck.id).limit(5)))


def read(check_id: int, now: datetime | None = None) -> str:
    """Read one screenshot (own transactions; the network call holds no DB locks)."""
    from app.ai import service  # late import: service imports a lot

    now = now or datetime.now(UTC)
    with SessionLocal() as session:
        cfg = ai_settings.load(session)
        check = session.get(PaymentCheck, check_id)
        shot = session.get(MediaDownload, check.message_id)
        order = session.get(Order, check.order_id)
        if check.ai_status is not None or shot is None or not shot.path:
            return "done already"
        limit = None
        if service.calls_today(session, now) >= cfg["daily_cap"]:
            limit = "cap"
        elif service.cost_this_month(session, now) >= cfg["monthly_budget_usd"]:
            limit = "budget"
        methods = list(session.scalars(select(PaymentMethod).where(PaymentMethod.active)
                                       .order_by(PaymentMethod.sort_order, PaymentMethod.id)))
        from app.orders import cart  # late import: orders -> ai

        user_input = context_text(cart.view(session, order).total, methods)
        path = MEDIA_DIR / shot.path.rsplit("/", 1)[-1]
    if limit is None:
        try:
            image = path.read_bytes()
        except OSError:
            limit = "no file"
    if limit is not None:
        _store(check_id, "skipped", error=limit)
        return limit
    try:
        reply = providers.get().read_image(INSTRUCTIONS, SCHEMA, user_input, image,
                                           MIME.get(path.suffix.lower(), "image/jpeg"), cfg["model"], cfg["reasoning"])
        reading = Reading.from_json(reply.data)
    except AIError as exc:
        _store(check_id, "error", error=exc.kind)
        return "error"
    except (KeyError, TypeError, ValueError):
        _store(check_id, "error", error="bad_output")
        return "error"
    except Exception as exc:  # an SDK surprise must not stop the worker
        log.warning("screenshot reader failed: %s", type(exc).__name__)
        _store(check_id, "error", error="other")
        return "error"
    _store(check_id, "done", reading, reply)
    return "done"


def _store(check_id: int, status: str, reading: Reading | None = None, reply=None, error: str | None = None) -> None:
    with SessionLocal.begin() as session:
        check = session.get(PaymentCheck, check_id)
        if check.ai_status is not None:
            return
        check.ai_status, check.ai_error, check.ai_read_at = status, error, datetime.now(UTC)
        check.ai_read = reading.to_json() if reading else None
        if reply is not None:
            check.ai_cost_usd = providers.cost_usd(reply.input_tokens, reply.cached_tokens, reply.output_tokens)


def run_once(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    with SessionLocal() as session:
        if not enabled(session):
            return {}
        ids = to_read(session, now)
    stats: dict[str, int] = {}
    for check_id in ids:
        try:
            outcome = read(check_id, now)
        except Exception:
            log.exception("screenshot reading failed for check=%s", check_id)
            outcome = "error"
        stats[outcome] = stats.get(outcome, 0) + 1
    return stats


# ---------- scripts/ai_eval.py --screens ----------

def evaluate(provider, model: str, reasoning: str, only: set[str] | None = None) -> int:
    """Synthetic receipts (tests/fixtures/payment_screens/labels.csv). PASS: amount exact >= 95%,
    transaction_no exact >= 90% (receipts), is_payment_receipt correct 100% (all)."""
    from scripts.ai_eval import _save

    rows = [r for r in csv.DictReader((FIXTURES / "labels.csv").open(encoding="utf-8")) if not only or r["id"] in only]
    methods = [PaymentMethod(name="KPay", account_number="09000001234", account_name="Test Shop")]
    print(f"Screenshot evaluation: {len(rows)} pictures, model {model}, reasoning {reasoning}\n")
    receipts = amount_ok = number_ok = kind_ok = errors = 0
    cost, cases = 0.0, []
    for row in rows:
        image = (FIXTURES / f"{row['id']}.png").read_bytes()
        notes, reading = [], None
        try:
            reply = provider.read_image(INSTRUCTIONS, SCHEMA, context_text(34000, methods), image, "image/png", model,
                                        reasoning)
            reading = Reading.from_json(reply.data)
            cost += providers.cost_usd(reply.input_tokens, reply.cached_tokens, reply.output_tokens)
        except (AIError, KeyError, TypeError, ValueError) as exc:
            errors += 1
            notes.append(f"no result: {getattr(exc, 'kind', type(exc).__name__)}")
        is_receipt = row["is_receipt"] == "1"
        ok = reading is not None and reading.is_payment_receipt == is_receipt
        kind_ok += ok
        if reading is not None and not ok:
            notes.append(f"is_payment_receipt {reading.is_payment_receipt}")
        if is_receipt:
            receipts += 1
            if reading is not None and reading.amount == int(row["amount"]):
                amount_ok += 1
            else:
                ok = False
                notes.append(f"amount {reading.amount if reading else '-'} (want {row['amount']})")
            if reading is not None and reading.transaction_no == row["transaction_no"]:
                number_ok += 1
            else:
                ok = False
                notes.append(f"transaction_no {reading.transaction_no if reading else '-'} (want {row['transaction_no']})")
            if reading is not None and (reading.receiver_name or "").lower() != row["receiver_name"].lower():
                notes.append(f"receiver {reading.receiver_name} (want {row['receiver_name']})")  # shown only
        print(f"{'✅' if ok else '❌'} {row['id']:4} {row['note'][:40]:40} "
              f"{(reading.app or '-') if reading else '-':8} {reading.amount if reading else '-'!s:>8} "
              f"{(reading.transaction_no or '-') if reading else '-':22}" + ("" if not notes else "  <- " + "; ".join(notes)))
        cases.append({"id": row["id"], "ok": ok, "notes": notes, "reading": reading.to_json() if reading else None})
    amount_acc, number_acc = amount_ok / (receipts or 1), number_ok / (receipts or 1)
    kind_acc = kind_ok / (len(rows) or 1)
    passed = amount_acc >= 0.95 and number_acc >= 0.90 and kind_acc == 1.0 and errors < len(rows)
    summary = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "model": model, "reasoning": reasoning,
               "pictures": len(rows), "receipts": receipts, "amount_exact": round(amount_acc, 3),
               "transaction_no_exact": round(number_acc, 3), "is_payment_receipt_correct": round(kind_acc, 3),
               "errors": errors, "cost_usd": round(cost, 5), "passed": passed}
    print(f"\namount exact {amount_acc:.0%} (need 95%) · transaction_no exact {number_acc:.0%} (need 90%) · "
          f"is_payment_receipt {kind_acc:.0%} (need 100%) · errors {errors} · cost ${cost:.4f}")
    print("PASS ✅" if passed else "FAIL ❌")
    _save("ai_eval_screens", summary, cases)
    return 0 if passed else 1
