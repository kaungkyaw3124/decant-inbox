"""Delivery addresses (docs/SPEC-v4.12-address-payment-ai.md N0, N1).

Our code has the final say over every saved address: validate() decides, whoever read it (the
rules, the AI or a person typing it in the dashboard).

  valid     township (from data/townships.csv) OR city + street, and real place words
  partial   says where in a street / ward / house, but no township (or city): ask for it
  invalid   too short, only keywords ("လိပ်စာ ပြောင်းချင်ပါတယ်"), or a township we don't know
  none      no address at all in the text

read_message() reads a customer message: the AI's split when the owner allows sending addresses
to the AI (switch ai_address) and the AI answered, else the rules. A phone number never ends up in
full_text.
"""
import csv
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from app.core.config import BASE_DIR
from app.parser.normalize import normalize, to_unicode
from app.parser.rules import _PHONE_RE, address_content

TOWNSHIPS_CSV = BASE_DIR / "data" / "townships.csv"
FIELDS = ("house_no", "street", "ward_or_quarter", "township", "city", "landmark")
MIN_CHARS = 8
SURE = 0.85  # the AI's address confidence needed to save without a person
PARTIAL_HOURS = 24  # a partial address waits this long for the township / city answer
# Shown to the admin (English; i18n_my.py has the Burmese)
REASONS = {
    "none": "No address in the message.",
    "keywords": "Only words like “address” / “change”, no place.",
    "short": "Too short to be an address.",
    "missing_township": "No township (or city + street).",
    "missing_city": "No city.",
    "unknown_township": "Township not in our list.",
    "unsure": "The AI is not sure about this address.",
}

_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
_DEPENDENT = re.compile("[ါ-ှၖ-ၙၞ-ၠၢ-ၤၧ-ၭၱ-ၴ"
                        "ႂ-ႍႏႚ-ႝ]")
_CONSONANT = re.compile("[က-ဪဿ၌-၏]")
_STREET_AFTER = re.compile(r"\s*(?:လမ်း|(?:road|rd|st|street|lane)(?![a-z]))", re.IGNORECASE)
# after a SHORT Burmese name ("ပြည်", "ဒလ", "အလုံ"): only these may follow, so "ပြည်သူ့ဆေးရုံ" is no township
_SHORT_AFTER = re.compile(r"$|[\s,.;:/\-–()\[\]#၊။0-9a-zA-Z]|မြို့|မှာ|က(?![ါ-ှ])|ကို|ထဲ|ဘက်|နား|ရှိ|ပါ|နော်")
SHORT_NAME = 5  # code points
_SUFFIX = re.compile(r"\s*(?:မြို့နယ်|မြို့|(?<![a-z])(?:township|tsp|town|city|region|division)\.?)\s*$",
                     re.IGNORECASE)
_NAMED_TOWNSHIP = re.compile(r"(\S{2,}?)\s*မြို့နယ်|(?<![a-z])([a-z][a-z' -]{2,30}?)\s+(?:township|tsp)(?![a-z])",
                             re.IGNORECASE)
_HOUSE = re.compile(r"အမှတ်\s*[\(\[]?\s*[\d၀-၉][\w/\-]*\s*[\)\]]?|(?<![a-z])(?:no|house|room|rm|apt|unit|bldg)\.?\s*[#:]?\s*"
                    r"[\d၀-၉][\w/\-]*|#\s*[\d၀-၉][\w/\-]*", re.IGNORECASE)
_STREET = re.compile(r"[\d၀-၉]+\s*လမ်း(?:မ)?(?:ကြီး)?|[^\s,၊။]*လမ်း(?:မ)?(?:ကြီး)?|(?<![a-z])(?:[\w.'-]+\s+){1,3}(?:street|st|road|rd|lane|avenue|ave)"
                     r"\.?(?![a-z])|[\d၀-၉]+\s*[x×]\s*[\d၀-၉]+", re.IGNORECASE)
_WARD = re.compile(r"[^\s,၊။]*ရပ်ကွက်(?:\s*\(?[\d၀-၉]+\)?)?|[\d၀-၉]+\s*(?:ward|qtr|quarter)(?![a-z])|"
                   r"(?<![a-z])(?:ward|qtr|quarter)\s*\(?[\d၀-၉]+\)?", re.IGNORECASE)
_PHONE_IN_TEXT = re.compile(r"(?:\+?95[\s-]?|0)9(?:[\s-]?\d){7,9}")


@dataclass(frozen=True)
class Township:
    my: str
    en: str
    city_my: str
    city_en: str
    names: tuple[str, ...]  # every spelling, lower case

    @property
    def label(self) -> str:
        return f"{self.my} ({self.en})"


@lru_cache(maxsize=1)
def townships() -> tuple[Township, ...]:
    out = []
    with TOWNSHIPS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names = {row["township_my"], row["township_en"].lower(),
                     *(v.strip().lower() for v in row["variants"].split("|") if v.strip())}
            out.append(Township(row["township_my"], row["township_en"], row["city_my"], row["city_en"],
                                tuple(sorted(names, key=len, reverse=True))))
    return tuple(out)


@lru_cache(maxsize=1)
def _cities() -> dict[str, tuple[str, str]]:
    """Every spelling of a city -> (Burmese, English)."""
    cities = {}
    for t in townships():
        cities[t.city_my] = cities[t.city_en.lower()] = (t.city_my, t.city_en)
    for alias, city in (("ygn", "Yangon"), ("mdy", "Mandalay"), ("npt", "Naypyitaw"), ("nay pyi taw", "Naypyitaw"),
                        ("rangoon", "Yangon")):
        cities[alias] = next(v for v in cities.values() if v[1] == city)
    return cities


def _boundary(text: str, start: int, end: int, name: str) -> bool:
    if name.isascii():
        return (start == 0 or not text[start - 1].isalnum()) and (end == len(text) or not text[end].isalnum())
    if start > 0 and text[start - 1] == "္":
        return False  # stacked under the previous consonant: inside a word
    if end < len(text):
        nxt = text[end]
        if _DEPENDENT.match(nxt):
            return False
        if _CONSONANT.match(nxt) and end + 1 < len(text) and text[end + 1] in "်္":
            return False  # "ဒလ" in "ဒလမ်း": the next consonant belongs to this syllable
    if len(name) < SHORT_NAME and not _SHORT_AFTER.match(text, end):
        return False
    return True


def _find(text: str, names: list[tuple[str, object]]):
    """The longest name found in text (a street named after a township does not count)."""
    lower = text.lower()
    for name, value in sorted(names, key=lambda x: len(x[0]), reverse=True):
        start = lower.find(name)
        while start >= 0:
            end = start + len(name)
            if _boundary(lower, start, end, name) and not _STREET_AFTER.match(lower, end):
                return value
            start = lower.find(name, start + 1)
    return None


def find_township(text: str) -> Township | None:
    return _find(text, [(n, t) for t in townships() for n in t.names])


def find_city(text: str) -> tuple[str, str] | None:
    return _find(text, list(_cities().items()))


def lookup_township(name: str | None) -> Township | None:
    """A township the AI proposed ("Yankin", "ရန်ကင်း", "Yankin Township"): only names in our list."""
    key = _SUFFIX.sub("", to_unicode(name or "").strip()).strip().lower()
    if not key:
        return None
    return next((t for t in townships() if key in t.names), None)


def lookup_city(name: str | None) -> tuple[str, str] | None:
    key = _SUFFIX.sub("", to_unicode(name or "").strip()).strip().lower()
    return _cities().get(key) if key else None


def strip_phones(text: str) -> str:
    """Removes phone numbers (Burmese digits too) without touching the other digits."""
    probe = text.translate(_DIGITS)
    spans = [m.span() for m in _PHONE_IN_TEXT.finditer(probe)] + [m.span() for m in _PHONE_RE.finditer(probe)]
    for start, end in sorted(set(spans), reverse=True):
        text = text[:start] + " " + text[end:]
    return text


def clean(text: str) -> str:
    """The address only: no phone numbers, no "ကိုပို့ပေးပါ" / "ဒီလိပ်စာကို…" / "new address:" words."""
    from app.orders import cart  # late import: cart imports this module

    text = strip_phones(to_unicode(text or ""))
    text = re.sub(r"(?i)(?:ဖုန်းနံပါတ်|ဖုန်း|(?<![a-z])(?:phone(?:\s*no)?|ph(?:\s*no)?|tel)(?![a-z])\.?)\s*[:：-]?\s*(?=[,၊။\s]|$)",
                  " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", ", ", text)
    text = re.sub(r"(?:\s*[,၊]\s*){2,}", ", ", text).strip(" ,၊-–\n")
    text = cart.LEADING_ASK.sub("", cart.TRAILING_ASK.sub("", text), count=1)
    return text.strip(" ,၊-–\n")[:500]


@dataclass
class Parts:
    full_text: str = ""
    house_no: str | None = None
    street: str | None = None
    ward_or_quarter: str | None = None
    township: str | None = None  # "ရန်ကင်း (Yankin)" when in our list, else the words as written
    city: str | None = None
    landmark: str | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v}


@dataclass
class Check:
    status: str  # valid | partial | invalid | none
    reason: str | None  # key of REASONS
    parts: Parts
    missing: tuple[str, ...] = ()  # ("township",) / ("city",)
    source: str = "rules"  # rules | ai | admin
    confidence: float = 1.0
    is_change_request: bool = False
    township: Township | None = field(default=None, repr=False)

    @property
    def valid(self) -> bool:
        return self.status == "valid"

    @property
    def sure(self) -> bool:
        """Saved without a person: valid, and (for the AI) confident."""
        return self.valid and (self.source != "ai" or self.confidence >= SURE)

    @property
    def ask(self) -> str | None:
        """The template that asks the customer for the missing part."""
        if self.status != "partial":
            return None
        return "ask_city" if self.missing == ("city",) else "ask_township"

    @property
    def why(self) -> str:
        if self.status == "valid" and not self.sure:
            return REASONS["unsure"]
        return REASONS.get(self.reason or "", "")


def _first(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0).strip(" ,") if m else None


def validate(full_text: str | None, parts: dict | None = None, *, source: str = "rules", confidence: float = 1.0,
             missing_hint: tuple[str, ...] = (), is_change_request: bool = False) -> Check:
    """The final say. parts: the AI's split (township / city it proposes are accepted only when they
    are in our list)."""
    parts = parts or {}
    text = clean(full_text or "")
    p = Parts(text, **{k: (str(parts[k]).strip() or None) if parts.get(k) else None for k in FIELDS})
    out = Check("none", "none", p, source=source, confidence=confidence, is_change_request=is_change_request)
    if not text:
        if (full_text or "").strip():  # only "ပို့ပေးပါ" / "လိပ်စာ ပြောင်းချင်" words were there
            out.status, out.reason = "invalid", "keywords"
        return out
    if address_content(normalize(text)) is None:
        out.status, out.reason = "invalid", "keywords"
        return out
    if parts.get("township"):
        township = lookup_township(parts["township"])
        if township is None:
            township = find_township(text)  # the AI's spelling is unusual but the text names a known one
        if township is None:
            out.status, out.reason = "invalid", "unknown_township"
            return out
    else:
        township = find_township(text)
        if township is None:
            named = _NAMED_TOWNSHIP.search(text)
            if named and lookup_township(named.group(1) or named.group(2)) is None:
                p.township = (named.group(1) or named.group(2)).strip()
                out.status, out.reason = "invalid", "unknown_township"
                return out
    city = lookup_city(parts.get("city")) or find_city(text)
    if township is not None:
        p.township, out.township = township.label, township
        city = city or (township.city_my, township.city_en)
    if city:
        p.city = f"{city[0]} ({city[1]})"
    p.house_no = p.house_no or _first(_HOUSE, text)
    p.street = p.street or _first(_STREET, text)
    p.ward_or_quarter = p.ward_or_quarter or _first(_WARD, text)
    if len(text) < MIN_CHARS:
        out.status, out.reason = "invalid", "short"
        return out
    if township is not None or (city and p.street):
        out.status, out.reason = "valid", None
        return out
    out.status = "partial"
    out.missing = ("city",) if missing_hint == ("city",) and not city else ("township",)
    out.reason = "missing_city" if out.missing == ("city",) else "missing_township"
    return out


def admin_check(text: str | None) -> Check:
    """An address a person typed in the dashboard (same validator)."""
    return validate(text, source="admin")


# ---------- reading a customer message ----------

def from_ai(data: dict | None) -> Check | None:
    """The AI's "address" answer -> Check (None = the AI saw no address)."""
    if not isinstance(data, dict) or not (data.get("full_text") or "").strip():
        return None
    missing = tuple(m for m in (data.get("missing") or []) if m in ("township", "city"))
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return validate(data["full_text"], {k: data.get(k) for k in FIELDS}, source="ai", confidence=confidence,
                    missing_hint=missing, is_change_request=bool(data.get("is_change_request")))


def from_rules(raw_text: str) -> Check | None:
    """The rules: the message without phones and "ကိုပို့ပေးပါ" / "ဒီလိပ်စာကို…" words."""
    from app.orders import cart  # late import: cart imports this module

    candidate = cart.address_from_message(raw_text or "")
    if not candidate:
        return None
    check = validate(candidate)
    return None if check.status == "none" or check.reason == "keywords" else check


def merge(partial: dict, check: Check) -> Check:
    """The answer to "which township?" + the partial address we kept (24 h)."""
    before = (partial or {}).get("full_text") or ""
    if not before:
        return check
    answer = check.parts.full_text
    if answer and normalize(answer) in normalize(before):
        combined = before
    elif answer and normalize(before) in normalize(answer):
        combined = answer  # the customer sent the whole address again
    else:
        combined = f"{before}, {answer}" if answer else before
    keep = {k: v for k, v in partial.items() if k in FIELDS and v}
    if check.township is not None:
        keep["township"] = check.township.my
    if check.parts.city:
        keep["city"] = check.parts.city.split(" (")[0]
    return validate(combined, keep, source=check.source, confidence=check.confidence,
                    is_change_request=check.is_change_request)


def read_message(session, message) -> Check | None:
    """The address in a customer message (None = none at all)."""
    return from_rules(message.raw_text or "")
