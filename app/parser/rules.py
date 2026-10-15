"""Rule-based parser: normalized text + alias list -> intent, items (product, size,
full bottle, quantity), phone.

Pure functions, no database access, so tests and reparse runs are cheap. The service
passes in what needs the database: bottle sizes per product and the customer's last
product (24 h context).
Bump PARSER_VERSION whenever the rules or scoring change.

rules-2 (docs/SPEC-orders.md "Parser v2"): multi-item, polite buy words, full bottle,
intents remove/confirm/done/address, phone numbers, 24 h context, unknown product text.
rules-3 (docs/SPEC-v3.md 6.1, 6.4): ask_delivery ("ဘယ်တော့ရောက်မလဲ", "deli"), cancel_order (a
cancel word WITHOUT a product: the whole order; with a product it stays remove).
rules-4 (docs/SPEC-v4.md 4.1): an alias with extra unknown Latin words attached ("hawas for him"
with alias "hawas") is NOT a match: match="partial", unknown_text = the whole name, the
alias' product kept as candidate_id (a suggestion only, never auto).
"""
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

PARSER_VERSION = "rules-4"
NEEDS_REVIEW_BELOW = 0.6  # dashboard shows results under this as "needs review"
FUZZY_THRESHOLD = 88      # rapidfuzz partial_ratio, 0-100
FUZZY_MIN_ALIAS_LEN = 5   # shorter aliases match too much by accident


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(patterns))


# Latin words must stand alone ("ok" not inside "book"); Burmese has no word spaces.
def _w(word: str) -> str:
    return r"(?<![a-z])" + word + r"(?![a-z])"


REMOVE_RE = _rx("မယူတော့", "ဖြုတ်ပေး", "ဖြုတ်လိုက်", "ဖြုတ်ပါ", "မလိုတော့", "မဝယ်တော့", "မမှာတော့", _w("cancel"))
# The same words without a product name = cancel the whole order.
CANCEL_ORDER_RE = _rx("မယူတော့", "မမှာတော့", "မဝယ်တော့", _w("cancel"))
# The polite particle ပါ may sit inside: ယူပါမယ်, ဝယ်ပါမယ်, မှာပါမယ်, ယူပါရစေ.
BUY_RE = _rx("ဝယ်ချင်", "ဝယ်(?:ပါ)?မယ်", "ယူ(?:ပါ)?မယ်", "ယူချင်", "ယူ(?:ပါ)?ရစေ", "မှာ(?:ပါ)?မယ်",
             "မှာချင်", _w("order"), _w("buy"))
ASK_PRICE_RE = _rx("ဘယ်လောက်", "ဈေး", "စျေး", _w("price"), _w("how much"))
ASK_STOCK_RE = _rx("ရှိလား", "ရှိသေးလား", "ရလား", _w("instock"), _w("in stock"), _w("available"), _w("avai"))
# "ပေးပါ(နော်)" = buy, but only when a product or size is named; "ပို့ပေးပါ" = address.
POLITE_BUY_RE = re.compile("(?<!ပို့)ပေးပါ")
TOWNSHIPS = (
    "ဗဟန်း", "ကမာရွတ်", "လှိုင်", "စမ်းချောင်း", "တာမွေ", "ရန်ကင်း", "သင်္ဃန်းကျွန်း", "ဥက္ကလာပ",
    "အင်းစိန်", "မရမ်းကုန်း", "လှိုင်သာယာ", "ဒဂုံ", "ဗိုလ်တထောင်", "ပုဇွန်တောင်", "မင်္ဂလာတောင်ညွန့်",
    "လမ်းမတော်", "လသာ", "ကျောက်တံတား", "ပန်းဘဲတန်း", "အလုံ", "ကြည့်မြင်တိုင်", "သာကေတ", "ဒေါပုံ",
    "မင်္ဂလာဒုံ", "ရွှေပြည်သာ", "မန္တလေး", "နေပြည်တော်", "တောင်ကြီး", "မော်လမြိုင်", "ပဲခူး", "ပုသိမ်",
    "မုံရွာ", "မြစ်ကြီးနား", "လားရှိုး", "ပြင်ဦးလွင်",
)
TOWNSHIPS_LATIN = (
    "bahan", "kamayut", "kamaryut", "hlaing", "sanchaung", "tamwe", "yankin", "thingangyun", "okkalapa",
    "insein", "mayangone", "mayangon", "hlaing thar yar", "hlaingthaya", "dagon", "botahtaung",
    "pazundaung", "lanmadaw", "latha", "kyauktada", "pabedan", "ahlone", "kyimyindaing", "thaketa",
    "dawbon", "mingaladon", "shwepyithar", "yangon", "mandalay", "naypyitaw", "nay pyi taw",
    "taunggyi", "mawlamyine", "bago", "pathein", "monywa", "myitkyina", "lashio", "pyin oo lwin",
)
ADDRESS_RE = _rx("ပို့ပေး", "လိပ်စာ", "မြို့နယ်", "ရပ်ကွက်", "လမ်း", _w("address"), _w("township"),
                 _w("street"), _w("road"), *TOWNSHIPS, *(_w(t) for t in TOWNSHIPS_LATIN))
# "When will it arrive?" Strong words win over address words; a bare "deli" only counts when
# nothing else matched and there is no phone number (an address message may say "deli").
ASK_DELIVERY_RE = _rx("ဘယ်တော့ရောက်", "ရောက်ပြီလား", "ရောက်ပြီလဲ", "ပို့ပြီးပြီလား", "ပို့ပြီးပြီလဲ", "ဘယ်တော့ပို့")
DELI_WORD_RE = _rx(_w("deli"))
DONE_RE = _rx("ဒါပဲ", "ဒါပါပဲ", "ဒီလောက်ပါပဲ", "ဒီလောက်ပဲ", "ဒါတွေပဲ", "ဒါတွေပါပဲ")
CONFIRM_RE = _rx("အဆင်ပြေတယ်", "အဆင်ပြေပါတယ်", "ဟုတ်ကဲ့", "ရပါတယ်", _w("ok"), _w("okay"), _w("confirm"))
PRODUCT_INTENTS = ("buy", "ask_price", "ask_stock", "remove")

# Size: a number directly followed by "ml" (normalize() already unified the unit).
_SIZE_RE = re.compile(r"(?<![\d.])(\d{1,3})\s*mls?(?![a-z])")
# Quantity: "2 ခု", "၂ဗူး" (digits already converted), "2 pcs", "x2".
_QTY_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*(?:ခု|ဗူး|pcs|pc|bottles?)(?![a-z])|(?<![a-z])x\s*(\d{1,2})(?!\d)")
_FULL_RE = re.compile(r"(?<![a-z])full\s*(?:size|bottle)?(?![a-z])|fullbottle|ဗူးလိုက်|အပြည့်")
# Myanmar mobile numbers: 09..., +959..., 959... with 7-9 more digits, spaces/dashes allowed.
_PHONE_RE = re.compile(r"(?<![\d+])(?:\+?95[\s-]?|0)9(?:[\s-]?\d){7,9}(?![\d])")
# Item separators: , (not inside 18,000) ၊ ။ + & new line, နဲ့ / နှင့်, "and".
_SPLIT_RE = re.compile(r"(?<!\d),|,(?!\d)|[၊။+&\n]|နဲ့|နှင့်|(?<![a-z])and(?![a-z])")
# Words left over after removing sizes/intents that are not product names.
_FILLER_LATIN = {
    "hi", "hello", "sis", "bro", "pls", "plz", "please", "ok", "okay", "thanks", "thank", "you", "yes", "no",
    "size", "full", "bottle", "decant", "the", "a", "for", "and", "also", "want", "need", "one", "two",
    "pcs", "pc", "x", "ml", "mls", "edp", "edt", "parfum", "perfume", "can", "i", "get", "have", "do", "is",
    "it", "this", "that", "too", "more", "again", "sir", "ma", "admin", "brand", "new", "original",
    "my", "don't", "dont", "anymore", "sorry", "order", "all", "just",
}
_LATIN_WORD = re.compile(r"[a-z][a-z0-9'.-]*")


@dataclass(frozen=True)
class Alias:
    product_id: int
    normalized_alias: str


@dataclass(frozen=True)
class ParsedItem:
    product_id: int | None
    size_ml: int | None
    is_full_bottle: bool = False
    quantity: int = 1
    unknown_text: str | None = None  # product named but not in the catalog
    from_context: bool = False  # product taken from the customer's previous message (24 h)
    match: str = "none"  # exact | fuzzy | multiple | ambiguous | inherited | context | partial | none
    candidate_id: int | None = None  # partial: the product whose alias is inside the name


@dataclass(frozen=True)
class ParseOutcome:
    intent: str
    product_id: int | None  # first item, kept for v1 columns (inbox filter, badges)
    size_ml: int | None
    quantity: int
    confidence: float
    items: tuple[ParsedItem, ...] = field(default=())
    phone: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.confidence < NEEDS_REVIEW_BELOW


def find_intent(text: str, has_product_or_size: bool = False) -> str | None:
    for intent, pattern in (("remove", REMOVE_RE), ("buy", BUY_RE), ("ask_price", ASK_PRICE_RE),
                            ("ask_stock", ASK_STOCK_RE)):
        if pattern.search(text):
            return intent
    if has_product_or_size and POLITE_BUY_RE.search(text):
        return "buy"
    for intent, pattern in (("ask_delivery", ASK_DELIVERY_RE), ("address", ADDRESS_RE), ("done", DONE_RE),
                            ("confirm", CONFIRM_RE)):
        if pattern.search(text):
            return intent
    if DELI_WORD_RE.search(text) and not _PHONE_RE.search(text):
        return "ask_delivery"
    return None


def find_sizes(text: str) -> list[int]:
    return list(dict.fromkeys(int(m) for m in _SIZE_RE.findall(text) if int(m) > 0))


def find_quantity(text: str) -> int:
    m = _QTY_RE.search(text)
    if not m:
        return 1
    qty = int(m.group(1) or m.group(2))
    return qty if qty > 0 else 1


def find_phones(text: str) -> list[str]:
    """All Myanmar mobile numbers, as 09xxxxxxxx, in order, without duplicates."""
    phones = []
    for m in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        phone = "0" + digits[2:] if digits.startswith("95") else digits
        if phone not in phones:
            phones.append(phone)
    return phones


def find_phone(text: str) -> str | None:
    """First Myanmar mobile number, as 09xxxxxxxx."""
    phones = find_phones(text)
    return phones[0] if phones else None


def _exact_spans(text: str, alias: str) -> list[tuple[int, int]]:
    """Positions where alias occurs, not glued to other Latin letters/digits
    ("ysl y" must not match inside "ysl yellow")."""
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])")
    return [m.span() for m in pattern.finditer(text)]


def find_product(text: str, aliases: list[Alias]) -> tuple[int | None, str]:
    """Return (product_id, how) where how is exact | fuzzy | ambiguous | multiple | none.

    Exact: longest aliases claim text first, so "stw intensely" beats a shorter
    "stw" alias. An alias shared by two products, or two different products in one
    part of the message, cannot be resolved by rules.
    """
    taken: list[tuple[int, int]] = []
    found: dict[int, int] = {}  # product_id -> first position
    for alias in sorted(aliases, key=lambda a: len(a.normalized_alias), reverse=True):
        for start, end in _exact_spans(text, alias.normalized_alias):
            if any(start < e and s < end for s, e in taken if (s, e) != (start, end)):
                continue  # inside a longer alias already matched
            taken.append((start, end))
            found.setdefault(alias.product_id, start)
    if found:
        ambiguous = _shared_alias_spans(text, aliases)
        if len(found) == 1:
            return next(iter(found)), "exact"
        if ambiguous and all(span in ambiguous for span in taken):
            return None, "ambiguous"
        first = min(found, key=found.get)
        return first, "multiple"

    best: dict[int, float] = {}
    for alias in aliases:
        if len(alias.normalized_alias) < FUZZY_MIN_ALIAS_LEN:
            continue
        score = fuzz.partial_ratio(alias.normalized_alias, text)
        if score >= FUZZY_THRESHOLD:
            best[alias.product_id] = max(best.get(alias.product_id, 0), score)
    if not best:
        return None, "none"
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None, "ambiguous"
    return ranked[0][0], "fuzzy"


def _shared_alias_spans(text: str, aliases: list[Alias]) -> set[tuple[int, int]]:
    owners: dict[str, set[int]] = {}
    for a in aliases:
        owners.setdefault(a.normalized_alias, set()).add(a.product_id)
    spans: set[tuple[int, int]] = set()
    for alias, products in owners.items():
        if len(products) > 1:
            spans.update(_exact_spans(text, alias))
    return spans


# Latin words next to a product name that are not part of a name (4.1 partial matches).
_NOT_NAME_LATIN = _FILLER_LATIN | {
    "price", "how", "much", "buy", "available", "avai", "instock", "in", "stock", "cancel", "deli",
    "confirm", "address", "hey", "mingalarpar", "mingalaba", "mingalabar", "ko",
    "eau", "de", "toilette", "cologne", "spray", "decants", "vial", "same", "last", "time",
}
_RUN_TOKEN = re.compile(r"\S+")
_NAME_WORD = re.compile(r"[a-z][a-z'-]*[.?!]*")


def words_of(text: str) -> set[str]:
    return {w.strip(".'-?!") for w in _LATIN_WORD.findall(text)}


def known_words_of(products: list[tuple[int, str, str]], aliases: list[Alias]) -> dict[int, frozenset[str]]:
    """Per product: Latin words of its brand, its name and the aliases of every product of the
    same brand ("dior sauvage elixir" is still Sauvage Elixir; "hawas for him" is not Hawas).
    products: (id, normalized brand, normalized name)."""
    by_brand: dict[str, set[str]] = {}
    brand_of = {}
    for pid, brand, name in products:
        by_brand.setdefault(brand, set()).update(words_of(brand) | words_of(name))
        brand_of[pid] = brand
    for a in aliases:
        if a.product_id in brand_of:
            by_brand[brand_of[a.product_id]].update(words_of(a.normalized_alias))
    return {pid: frozenset(by_brand[brand]) for pid, brand in brand_of.items()}


def partial_name(part: str, aliases: list[Alias], product_id: int,
                 known: frozenset[str] | set[str] = frozenset()) -> str | None:
    """4.1: the product's alias sits inside a longer name ("hawas for him" with alias "hawas").
    Returns that whole name if Latin words that are not filler and not words of the product
    (its brand, name, aliases) are attached directly before or after the alias, else None.
    Expansion stops at anything that is not a Latin word (sizes, digits, Burmese, commas)."""
    spans = [span for a in sorted(aliases, key=lambda a: -len(a.normalized_alias)) if a.product_id == product_id
             for span in _exact_spans(part, a.normalized_alias)]
    if not spans:
        return None
    start, end = spans[0]
    tokens = [(m.start(), m.end(), m.group()) for m in _RUN_TOKEN.finditer(part)]
    inside = [n for n, (s, e, _) in enumerate(tokens) if s < end and start < e]
    if not inside:
        return None
    first, last = inside[0], inside[-1]
    while first > 0 and _NAME_WORD.fullmatch(tokens[first - 1][2]):
        first -= 1
    while last + 1 < len(tokens) and _NAME_WORD.fullmatch(tokens[last + 1][2]):
        last += 1
    own = known | {w for a in aliases if a.product_id == product_id for w in words_of(a.normalized_alias)}

    def name_word(token: str) -> bool:
        word = token.strip(".'-?!")
        return bool(word) and word not in _NOT_NAME_LATIN

    outside = [t for n, (_, _, t) in enumerate(tokens[first:last + 1], first) if n not in inside]
    if not any(name_word(t) and t.strip(".'-?!") not in own for t in outside):
        return None
    run = [t.strip("?!") for _, _, t in tokens[first:last + 1]]
    while run and not name_word(run[0]) and run[0] not in part[start:end]:
        run.pop(0)
    while run and not name_word(run[-1]):
        run.pop()
    return " ".join(run) or None


def unknown_product_text(part: str) -> str | None:
    """What is left of a part once sizes, quantities, intent and filler words are removed,
    if it looks like a (Latin-script) product name, e.g. "hawas ice"."""
    text = part
    for pattern in (_SIZE_RE, _QTY_RE, _FULL_RE, _PHONE_RE, REMOVE_RE, BUY_RE, ASK_PRICE_RE, ASK_STOCK_RE):
        text = pattern.sub(" ", text)
    words = [w.strip(".'-") for w in _LATIN_WORD.findall(text)]
    words = [w for w in words if w and w not in _FILLER_LATIN and not w.isdigit()]
    name = " ".join(words)
    return name if sum(c.isalpha() for c in name) >= 3 else None


def split_parts(text: str) -> list[str]:
    return [p.strip() for p in _SPLIT_RE.split(text) if p and p.strip()]


def _items(text: str, aliases: list[Alias], full_sizes: dict[int, int],
           context_product_id: int | None, allow_unknown: bool,
           known_words: dict[int, frozenset[str]]) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    for part in split_parts(text):
        product_id, how = find_product(part, aliases)
        sizes = find_sizes(part)
        full = bool(_FULL_RE.search(part))
        qty = find_quantity(part)
        unknown = None
        candidate = None
        if how == "exact":
            name = partial_name(part, aliases, product_id, known_words.get(product_id, frozenset()))
            if name is not None:  # "hawas for him": not Hawas Ice, only a suggestion
                product_id, how, unknown, candidate = None, "partial", name, product_id
        if product_id is None and how not in ("ambiguous", "partial"):
            unknown = unknown_product_text(part) if (allow_unknown or sizes or full) else None
            if unknown is None and (sizes or full):
                previous = next((i for i in reversed(items) if i.product_id), None)
                if previous is not None:  # "swy 5ml နဲ့ 10ml"
                    product_id, how = previous.product_id, "inherited"
                elif context_product_id is not None:  # "10ml ရော" after asking about a product
                    product_id, how = context_product_id, "context"
        if product_id is None and unknown is None and not sizes and not full and how != "ambiguous":
            continue  # nothing product-related in this part (e.g. "ယူပါမယ်" on its own line)
        bottle = full_sizes.get(product_id) if product_id else None
        if full or not sizes:
            sizes_for_part: list[int | None] = [None]
        else:
            sizes_for_part = list(sizes)
        for size in sizes_for_part:
            is_full = full or (size is not None and bottle is not None and size == bottle)
            items.append(ParsedItem(product_id, None if is_full else size, is_full, qty, unknown,
                                    how == "context", how, candidate))
    return items


_MATCH_SCORE = {"exact": 0.5, "inherited": 0.5, "fuzzy": 0.35, "multiple": 0.25, "context": 0.25,
                "ambiguous": 0.0, "partial": 0.0, "none": 0.0}


def parse(normalized_text: str, aliases: list[Alias], full_sizes: dict[int, int] | None = None,
          context_product_id: int | None = None,
          known_words: dict[int, frozenset[str]] | None = None) -> ParseOutcome:
    """known_words: per product, Latin words that may stand next to its alias without making
    the name a different one (brand, name, same-brand aliases); see partial_name()."""
    text = normalized_text
    phone = find_phone(text)
    full_sizes = full_sizes or {}
    keyword_intent = find_intent(text)
    items = _items(text, aliases, full_sizes, context_product_id,
                   allow_unknown=keyword_intent in PRODUCT_INTENTS, known_words=known_words or {})
    named = [i for i in items if i.match != "context"]
    intent = find_intent(text, has_product_or_size=any(i.product_id or i.size_ml or i.is_full_bottle for i in named))
    if intent is None and phone:
        intent = "address"  # contact details
    if intent not in PRODUCT_INTENTS and intent is not None:
        items = named  # no context guessing for address/confirm/done
    first = next((i for i in items if i.product_id), items[0] if items else None)
    product_id = first.product_id if first else None
    size_ml = first.size_ml if first else None
    quantity = first.quantity if first else 1
    items_t = tuple(items)

    if intent is None:
        if not items:
            # Nothing product-related: chit-chat, thanks...
            return ParseOutcome("other", None, None, 1, 0.7, (), phone)
        intent = "unknown"
    if intent == "remove" and not items and CANCEL_ORDER_RE.search(text):
        intent = "cancel_order"  # no product named: the whole order
    if intent in ("address", "confirm", "done", "ask_delivery", "cancel_order") or (intent == "remove" and not items):
        return ParseOutcome(intent, product_id, size_ml, quantity, 0.8, items_t, phone)

    intent_score = 0.0 if intent == "unknown" else 0.3
    product_score = min((_MATCH_SCORE[i.match] for i in items), default=0.0)
    if any(i.unknown_text for i in items):
        product_score = 0.0
    has_size = first is not None and (first.size_ml is not None or first.is_full_bottle)
    confidence = intent_score + product_score + (0.2 if has_size else 0.0)
    if intent == "unknown":
        confidence = min(confidence, 0.5)  # always ask a human
    return ParseOutcome(intent, product_id, size_ml, quantity, round(max(confidence, 0.0), 2), items_t, phone)
