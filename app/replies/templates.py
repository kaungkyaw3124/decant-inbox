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
    TemplateDef("greeting_reply", "Reply to a message that is only a greeting (“hi”): no open order",
                "မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။", {}),
    # docs/SPEC-v4.9-greeting.md: the reply to "hi" follows where the customer is (the leading
    # "မင်္ဂလာပါ။" is left out when we messaged them in the last 6 h)
    TemplateDef("greeting_cart", "Reply to “hi”: open cart ({next_step} = the next question: phone / address / same as last time)",
                "မင်္ဂလာပါ။ ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n{items}\nစုစုပေါင်း {total} ကျပ်ပါ။\n{next_step}",
                {"items": _ITEMS, "total": "83,000", "next_step": "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"}),
    TemplateDef("greeting_waiting_payment", "Reply to “hi”: payment info sent, waiting for the payment",
                "မင်္ဂလာပါ။ {items_short} အတွက် စုစုပေါင်း {total} ကျပ် လွှဲပြီးရင် transaction id ပါတဲ့ screenshot "
                "ပို့ပေးပါနော်။ ဘာများ ထပ်ကူညီပေးရမလဲ။",
                {"items_short": "Stronger With You Intensely 5ml, Aventus 10ml", "total": "83,000"}),
    TemplateDef("greeting_photo_received", "Reply to “hi”: payment screenshot received, not checked yet",
                "မင်္ဂလာပါ။ ငွေလွှဲ screenshot ရပါပြီ၊ စစ်ပြီး အကြောင်းပြန်ပေးပါမယ်နော်။", {}),
    TemplateDef("greeting_preparing", "Reply to “hi”: order paid / packed",
                "မင်္ဂလာပါ။ Order #{order_no} ကို ပြင်ဆင်နေပါတယ်။ ဘာများ ထပ်ကူညီပေးရမလဲ။", {"order_no": "1001"}),
    TemplateDef("greeting_sent", "Reply to “hi”: order sent out",
                "မင်္ဂလာပါ။ Order #{order_no} ကို {sent_date} မှာ ပို့ပြီးပါပြီ။ ဘာများ ထပ်ကူညီပေးရမလဲ။",
                {"order_no": "1001", "sent_date": "17/10/2026"}),
    TemplateDef("price_one", "Price: one size",
                "{product} {size} က {price} ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။",
                {"product": "Stronger With You Intensely", "size": "5ml", "price": "18,000"}),
    TemplateDef("price_list_header", "Price: all sizes – first line", "{product}",
                {"product": "Stronger With You Intensely"}),
    TemplateDef("price_list_line", "Price: all sizes – one line per size", "• {size} – {price} ကျပ်",
                {"size": "Full 100ml", "price": "280,000"}),
    TemplateDef("cart_line", "Cart / order: one line per item", "• {product} {size} – {price} ကျပ်",
                {"product": "Aventus", "size": "10ml", "price": "65,000"}),
    TemplateDef("cart_total", "Cart: total line", "စုစုပေါင်း {total} ကျပ်ပါ။", {"total": "83,000"}),
    TemplateDef("cart_ask_phone", "Cart list: last line when we have no phone yet",
                "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။", {}),
    TemplateDef("cart_returning", "Cart list: last line for a customer with saved phone + address",
                "ဖုန်း {phones}၊ လိပ်စာ {address} ကိုပဲ ပို့ပေးရမလား။",
                {"phones": "09777123456", "address": "No. 12, Bahan"}),
    TemplateDef("unknown_items_note", "Cart: items we must check (not in the list / no price)",
                "{names} ကိုတော့ စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။", {"names": "hawas ice 10ml"}),
    TemplateDef("ask_phone", "Ask phone number", "ဆက်သွယ်ရန် ဖုန်းနံပါတ် ပို့ပေးပါနော်။", {}),
    TemplateDef("ask_address", "Ask address", "ပို့ပေးရမယ့် လိပ်စာ ပို့ပေးပါနော်။", {}),
    TemplateDef("phone_saved_ask_address", "Phone received, ask address",
                "ဖုန်းနံပါတ် {phones} ရပါပြီ။ ပို့ပေးရမယ့် လိပ်စာ ပို့ပေးပါနော်။", {"phones": "09 777 123 456"}),
    TemplateDef("phone_added", "Another phone number added",
                "ဖုန်းနံပါတ် {phone} ကိုလည်း ထည့်ထားပါပြီ။", {"phone": "09 444 555 666"}),
    # docs/SPEC-v4.8-change-info.md: the customer wants to change the address / phone
    TemplateDef("ask_new_address", "Customer wants to change the address: ask the new one",
                "ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။", {}),
    TemplateDef("ask_new_phone", "Customer wants to change the phone: ask the new one",
                "ဖုန်းနံပါတ်အသစ် ပို့ပေးပါနော်။", {}),
    TemplateDef("ask_new_contact", "Customer wants to change something (not clear what): ask both",
                "လိပ်စာအသစ်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါနော်။", {}),
    TemplateDef("address_updated", "New address saved (before payment info, or alone if it was sent already)",
                "လိပ်စာ ပြင်ပြီးပါပြီ – {address}", {"address": "No. 5, Shwegondaing Rd, Bahan"}),
    TemplateDef("phone_updated", "New phone saved (before payment info, or alone if it was sent already)",
                "ဖုန်းနံပါတ် ပြင်ပြီးပါပြီ – {phone}", {"phone": "09444555666"}),
    TemplateDef("payment_total", "Payment info: total line", "စုစုပေါင်း {total} ကျပ်ပါ။", {"total": "83,000"}),
    TemplateDef("payment_method_line", "Payment info: one line per payment method",
                "{name} – {account_number} ({account_name})",
                {"name": "KPay", "account_number": "09 123 456 789", "account_name": "Daw Example"}),
    TemplateDef("payment_info_footer", "Payment info: last line",
                "ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။", {}),
    # docs/SPEC-v4.10-interruptions.md: interruptions while we wait for something; locked paid orders
    TemplateDef("resume_payment", "Resume line while waiting for the payment (added after other answers)",
                "ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။", {}),
    TemplateDef("cart_total_changed", "Payment info again after the order changed: total line",
                "စုစုပေါင်း အသစ် {total} ကျပ်ပါ။", {"total": "101,000"}),
    TemplateDef("offer_add", "After a price, while waiting for the payment: offer to add it",
                "ဒီ order ထဲ ထည့်ပေးရမလား။", {}),
    TemplateDef("ask_screenshot", "“I paid” without a screenshot",
                "transaction id ပါတဲ့ screenshot လေး ပို့ပေးပါနော်။", {}),
    TemplateDef("hold_check", "We must check first (unknown item, or a change after the payment screenshot)",
                "စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။", {}),
    TemplateDef("locked_new_order", "Paid order is locked: the new items become a NEW order (first line)",
                "Order #{order_no} ကတော့ အတည်ပြုပြီးသားပါ။ ဒါကို order အသစ်အနေနဲ့ ယူပေးပါမယ်နော်။", {"order_no": "1004"}),
    TemplateDef("order_locked", "Paid order is locked: the customer asked to change it",
                "Order #{order_no} က ငွေလွှဲပြီး အတည်ပြုပြီးသားဖြစ်လို့ ပြင်ဆင်လို့ မရတော့ပါဘူးနော်။ အကူအညီလိုရင် "
                "ခဏစောင့်ပေးပါ၊ ပြန်ဆက်သွယ်ပေးပါမယ်။", {"order_no": "1004"}),
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
    TemplateDef("not_stocked_item", "One asked item we don't have (added to the reply)",
                "{name} ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။", {"name": "hawas ice"}),
    TemplateDef("not_stocked", "Product we don't have",
                "ဒီ product လောလောဆယ် မရှိသေးပါဘူးနော်။", {}),
    # docs/SPEC-v3.md Step 6
    TemplateDef("order_sent_out", "Order sent out ({deli_line} = the Deli line below, only when given)",
                "Order #{order_no} ကို ပို့လိုက်ပါပြီ။{deli_line}\nပို့ခကို ပစ္စည်းရောက်မှ ပေးချေပေးပါနော်။",
                {"order_no": "1001", "deli_line": "\nDeli: Ko Min 09 555 111 222"}),
    TemplateDef("deli_line", "Deli line (own line; only when a deli name or phone is given)",
                "Deli: {deli_name} {deli_phone}", {"deli_name": "Ko Min", "deli_phone": "09 555 111 222"}),
    TemplateDef("order_delivered", "Order delivered: thank-you (only if switched on in Orders & payments)",
                "ပစ္စည်းရရှိပြီဖြစ်လို့ ကျေးဇူးတင်ပါတယ်။ နောက်လည်း အားပေးပါဦးနော်။", {}),
    TemplateDef("delivery_preparing", "“When will it arrive?” – order paid / packed",
                "Order #{order_no} ကို ပြင်ဆင်နေပါတယ်။ ပို့လိုက်တာနဲ့ အကြောင်းကြားပေးပါမယ်နော်။", {"order_no": "1001"}),
    TemplateDef("delivery_sent", "“When will it arrive?” – order sent out",
                "Order #{order_no} ကို {sent_date} မှာ ပို့ပြီးပါပြီ။{deli_line}",
                {"order_no": "1001", "sent_date": "15/10/2026", "deli_line": "\nDeli: Ko Min 09 555 111 222"}),
    TemplateDef("payment_reminder", "Payment reminder (once, when no screenshot came)",
                "Order အတွက် ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။ စုစုပေါင်း {total} ကျပ်ပါ။",
                {"total": "83,000"}),
    TemplateDef("order_auto_cancelled", "Order cancelled because no payment came",
                "ငွေလွှဲမှု မရရှိသေးတဲ့အတွက် အော်ဒါကို cancel လုပ်ထားပါတယ်။ ပြန်မှာချင်ရင် ပြောပေးပါနော်။", {}),
    # docs/SPEC-v4.md 4.3
    TemplateDef("previous_item_line", "“The previous one”: line added to the cart list when we found one item",
                "{product} {size} (အရင်ယူထားတဲ့ဟာ) ဟုတ်တယ်နော်။ မဟုတ်ရင် ပြောပေးပါ။",
                {"product": "Good Girl", "size": "5ml"}),
    TemplateDef("choose_previous", "“The previous one”: several earlier items – ask which ({options} = numbered lines)",
                "အရင်က ယူထားတာတွေပါ –\n{options}\nဘယ်ဟာလဲ နံပါတ်လေး ပြောပေးပါနော်။",
                {"options": "1. Good Girl 5ml\n2. Aventus 10ml"}),
    TemplateDef("order_cancelled", "Customer cancelled the order",
                "အော်ဒါ cancel လုပ်ပြီးပါပြီ။ နောက်မှ ပြန်မှာချင်ရင် ပြောပေးပါနော်။", {}),
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
