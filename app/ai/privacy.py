"""Mask personal details before text leaves the server (docs/SPEC-v4.6-ai.md S1 PRIVACY).

docs/SPEC-v4.12-address-payment-ai.md: with the owner's switch ai_address ON, addresses are NOT
masked (keep_address): the text goes as written (Zawgyi converted, case and Burmese digits kept, so
the AI can copy the address exactly); phone numbers and long numbers are still masked.

Phone numbers -> [PHONE]; house numbers, street names, wards -> [ADDRESS]; any other run of
6+ digits (KPay transaction ids, account numbers) -> [NUMBER]. Sizes ("10ml"), quantities
("2 ခု") and prices up to 5 digits stay: the AI needs them. Township names stay too (they
tell the AI "this is an address" and identify nobody)."""
import re
import unicodedata

from app.orders import testpay
from app.parser.normalize import normalize, to_unicode
from app.parser.rules import _PHONE_RE

# International numbers too: + and 8+ digits, spaces or dashes allowed.
_ANY_PHONE_RE = re.compile(r"(?<![\w+])\+\d[\d\s-]{7,}\d(?!\d)")
_ADDRESS_RES = (
    re.compile(r"အမှတ်\s*[\(\[]?\s*[\d/\-]+\s*[\)\]]?(?:\s*/\s*[\d\-]+)?"),     # အမှတ် ၁၂ / အမှတ်(12)
    re.compile(r"(?<![a-z])(?:no|house|room|rm|apt|unit|bldg|building|blk|block)\.?\s*[#:]?\s*\d[\w/\-]*"),
    re.compile(r"#\s*\d[\w/\-]*"),
    re.compile(r"\S*လမ်း(?:မ)?(?:ကြီး)?"),                                        # သုခလမ်း, ၃၅လမ်း, ပြည်လမ်း
    re.compile(r"(?<![a-z])(?:[\w.'-]+\s+){0,2}(?:street|st|road|rd|lane|avenue|ave)\.?(?![a-z])"),
    re.compile(r"\d+\s*(?:ရပ်ကွက်|ward|qtr|quarter)|(?:ရပ်ကွက်)\s*\(?\d+\)?"),
    re.compile(r"\d+\s*(?:ထပ်|လွှာ|floor|fl)(?![a-z])|(?:တိုက်)\s*\(?\d+\)?"),
)
_LONG_NUMBER_RE = re.compile(r"(?<![\w])\d[\d\s\-]{4,}\d(?![\w])|\d{6,}")


_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")


def _mask_numbers_as_written(text: str) -> str:
    """Phones -> [PHONE], 6+ digit numbers -> [NUMBER], found on a 0-9 copy (same length), replaced in
    the text as written."""
    probe = text.translate(_DIGITS)
    spans = []
    for pattern, label in ((_PHONE_RE, "[PHONE]"), (_ANY_PHONE_RE, "[PHONE]"), (_LONG_NUMBER_RE, "[NUMBER]")):
        for m in pattern.finditer(probe):
            digits = len(re.sub(r"\D", "", m.group()))
            if (label == "[NUMBER]" and digits < 6) or (pattern is _ANY_PHONE_RE and digits < 9):
                continue
            if not any(s < m.end() and m.start() < e for s, e, _ in spans):
                spans.append((m.start(), m.end(), label))
    for start, end, label in sorted(spans, reverse=True):
        text = text[:start] + label + text[end:]
    return text


def mask(text: str, keep_address: bool = False) -> str:
    """Normalized text (Burmese digits as 0-9) with personal details replaced; keep_address: the text
    as written with only phones and long numbers replaced. The test payment code never reaches the AI."""
    text = testpay.hide(text or "")
    if keep_address:
        out = unicodedata.normalize("NFC", to_unicode(text or ""))
        out = re.sub(r"[^\S\n]+", " ", re.sub(r" *\n\s*", "\n", out))
        return _mask_numbers_as_written(out).strip()
    out = normalize(text or "", keep_newlines=True)
    out = _PHONE_RE.sub("[PHONE]", out)
    out = _ANY_PHONE_RE.sub(lambda m: "[PHONE]" if len(re.sub(r"\D", "", m.group())) >= 9 else m.group(), out)
    for pattern in _ADDRESS_RES:
        out = pattern.sub("[ADDRESS]", out)
    out = _LONG_NUMBER_RE.sub(lambda m: "[NUMBER]" if len(re.sub(r"\D", "", m.group())) >= 6 else m.group(), out)
    out = re.sub(r"(?:\[ADDRESS\]\s*){2,}", "[ADDRESS] ", out)
    return out.strip()
