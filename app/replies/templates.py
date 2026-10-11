"""Reply templates (docs/SPEC-orders.md). Defaults live here; Settings stores only the
templates the admin changed (reply_templates), and "Reset" deletes that row again.

Placeholders are plain {names}; each template allows only its own names.
"""
import string
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReplyTemplate


@dataclass(frozen=True)
class TemplateDef:
    key: str
    label: str
    default: str
    example: dict[str, str]  # placeholder -> example value (also the allowed placeholders)


_ITEMS = "• Stronger With You Intensely 5ml – 18,000 ကျပ်\n• Aventus 10ml – 65,000 ကျပ်"

TEMPLATES: tuple[TemplateDef, ...] = (
    TemplateDef("greeting", "Greeting (added in front if we haven't messaged them for 6 h)",
                "မင်္ဂလာပါ။", {}),
    TemplateDef("price_one", "Price: one size",
                "{product} {size} က {price} ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။",
                {"product": "Stronger With You Intensely", "size": "5ml", "price": "18,000"}),
    TemplateDef("price_list_header", "Price: all sizes – first line", "{product}",
                {"product": "Stronger With You Intensely"}),
    TemplateDef("price_list_line", "Price: all sizes – one line per size", "• {size} – {price} ကျပ်",
                {"size": "Full 100ml", "price": "280,000"}),
    TemplateDef("cart_line", "Cart / order: one line per item", "• {product} {size} – {price} ကျပ်",
                {"product": "Aventus", "size": "10ml", "price": "65,000"}),
    TemplateDef("cart_total", "Cart: total line",
                "စုစုပေါင်း {total} ကျပ်ပါ။ အဆင်ပြေရင် confirm လုပ်ပေးပါနော်။", {"total": "83,000"}),
    TemplateDef("ask_address", "Ask address and phone",
                "ပို့ပေးရမယ့် လိပ်စာနဲ့ ဖုန်းနံပါတ် ပို့ပေးပါနော်။", {}),
    TemplateDef("payment_total", "Payment info: total line", "စုစုပေါင်း {total} ကျပ်ပါ။", {"total": "83,000"}),
    TemplateDef("payment_method_line", "Payment info: one line per payment method",
                "{name} – {account_number} ({account_name})",
                {"name": "KPay", "account_number": "09 123 456 789", "account_name": "Daw Example"}),
    TemplateDef("payment_info_footer", "Payment info: last line",
                "ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။", {}),
    TemplateDef("several_photos", "Several photos sent at once",
                "transaction id ပါတဲ့ screenshot တစ်ပုံတည်း ပို့ပေးပါနော်။", {}),
    TemplateDef("order_confirmed", "Payment approved: order confirmation",
                "✅ Order #{id} အတည်ပြုပြီးပါပြီ။\n{items}\nစုစုပေါင်း {total} ကျပ် (ငွေရရှိပြီး)\n"
                "ဖုန်း: {phone}\nလိပ်စာ: {address}\nပို့ခကို ပစ္စည်းရောက်မှ ပေးချေရပါမယ်။\nကျေးဇူးတင်ပါတယ်။",
                {"id": "1001", "items": _ITEMS, "total": "83,000", "phone": "09 987 654 321",
                 "address": "No. 12, Bahan, Yangon"}),
    TemplateDef("reject_not_received", "Payment rejected: money not received",
                "ငွေမဝင်သေးပါဘူး။ ပြန်စစ်ပေးပါနော်။", {}),
    TemplateDef("reject_wrong_screenshot", "Payment rejected: wrong screenshot",
                "ပို့ပေးတဲ့ screenshot က ဒီအော်ဒါနဲ့ မကိုက်ညီပါဘူး။ transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။", {}),
    TemplateDef("reject_wrong_amount", "Payment rejected: amount too low",
                "ကျန်ငွေ {remaining} ကျပ် ထပ်လွှဲပေးပါနော်။", {"remaining": "5,000"}),
    TemplateDef("out_of_stock", "Out of stock",
                "{product} {size} လောလောဆယ် ကုန်နေပါတယ်နော်။", {"product": "Aventus", "size": "10ml"}),
    TemplateDef("not_stocked", "Product we don't have",
                "ဒီ product လောလောဆယ် မရှိသေးပါဘူးနော်။", {}),
)
BY_KEY = {t.key: t for t in TEMPLATES}
MAX_LENGTH = 2000


def placeholders(text: str) -> list[str]:
    """Placeholder names in text. ValueError for broken braces or anything but plain {name}."""
    names = []
    for _, name, spec, conversion in string.Formatter().parse(text):
        if name is None:
            continue
        if not name.isidentifier() or spec or conversion:
            raise ValueError(f"'{{{name}}}' is not a valid placeholder")
        names.append(name)
    return names


def validate(key: str, text: str) -> str:
    """Cleaned text, or ValueError with a message for the admin."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("The text can't be empty.")
    if len(text) > MAX_LENGTH:
        raise ValueError(f"Too long (max {MAX_LENGTH} characters).")
    try:
        names = placeholders(text)
    except ValueError as exc:
        raise ValueError(f"{exc}. Use {{{{ and }}}} for a literal brace.") from exc
    allowed = BY_KEY[key].example
    unknown = sorted(set(names) - set(allowed))
    if unknown:
        hint = ", ".join(f"{{{n}}}" for n in allowed) or "none"
        raise ValueError(f"Unknown placeholder {', '.join(f'{{{n}}}' for n in unknown)}. Allowed here: {hint}.")
    return text


def load(session: Session) -> dict[str, str]:
    """Current text of every template (admin edits over defaults)."""
    texts = {t.key: t.default for t in TEMPLATES}
    texts.update({r.key: r.text for r in session.scalars(select(ReplyTemplate)) if r.key in texts})
    return texts


def render(text: str, **values: str) -> str:
    return text.format(**values)
