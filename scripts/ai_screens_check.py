"""docs/SPEC-v4.12-address-payment-ai.md N3 S0: can the configured model read images? One real call with a
synthetic receipt (tests/fixtures/payment_screens/s02.png, no customer data). The result is saved in the
AI settings and shown on /ai; when it fails, screenshot reading cannot be switched on there.

Usage: .venv/bin/python -m scripts.ai_screens_check   (exit 0 = reads images, 1 = not, 2 = no AI key)
"""
import sys
from datetime import UTC, datetime

from app.ai import providers, screens
from app.ai import settings as ai_settings
from app.ai.providers import AIError
from app.core.db import SessionLocal
from app.models import PaymentMethod


def main() -> int:
    provider = providers.get()
    if provider is None:
        print("AI provider is off or OPENAI_API_KEY is missing in .env")
        return 2
    with SessionLocal() as session:
        model, reasoning = ai_settings.load(session)["model"], ai_settings.load(session)["reasoning"]
    image = (screens.FIXTURES / "s02.png").read_bytes()
    methods = [PaymentMethod(name="KPay", account_number="09000001234", account_name="Test Shop")]
    ok, detail = False, ""
    try:
        reply = provider.read_image(screens.INSTRUCTIONS, screens.SCHEMA, screens.context_text(34000, methods), image,
                                    "image/png", model, reasoning)
        r = screens.Reading.from_json(reply.data)
        ok = r.is_payment_receipt and r.amount == 70000 and r.transaction_no == "01003456789098765432"
        detail = f"read {r.amount} / {r.transaction_no}"
    except AIError as exc:
        detail = f"{exc.kind} {exc.detail}".strip()
    except (KeyError, TypeError, ValueError) as exc:
        detail = f"bad answer ({type(exc).__name__})"
    result = {"model": model, "ok": ok, "at": datetime.now(UTC).isoformat(timespec="seconds"), "detail": detail[:120]}
    with SessionLocal.begin() as session:
        values = {"screenshot_check": result}
        if not ok:
            values["ai_screenshot"] = False  # not available with this model: keep N3 off
        ai_settings.save(session, values, None)
    print(f"model {model}: {'reads screenshots ✅' if ok else 'cannot read screenshots ❌'} ({detail})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
