"""Rule-based parser: normalized text + alias list -> intent, product, size, quantity.

Pure functions, no database access, so tests and reparse runs are cheap.
Bump PARSER_VERSION whenever the rules or scoring change.
"""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

PARSER_VERSION = "rules-1"
NEEDS_REVIEW_BELOW = 0.6  # dashboard shows results under this as "needs review"
FUZZY_THRESHOLD = 88      # rapidfuzz partial_ratio, 0-100
FUZZY_MIN_ALIAS_LEN = 5   # shorter aliases match too much by accident

# Checked in this order: the first intent with a keyword wins.
# Text is already normalized (Unicode, lowercase), so keywords are lowercase Unicode.
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "buy": ("ဝယ်ချင်", "ဝယ်မယ်", "ယူမယ်", "ယူချင်", "မှာမယ်", "မှာချင်", "order", "buy"),
    "ask_price": ("ဘယ်လောက်", "ဈေး", "စျေး", "price", "how much"),
    "ask_stock": ("ရှိလား", "ရှိသေးလား", "ရလား", "instock", "in stock", "available", "avai"),
}

# Size: a number directly followed by "ml" (normalize() already unified the unit).
_SIZE_RE = re.compile(r"(?<![\d.])(\d{1,3})\s*mls?(?![a-z])")
# Quantity: "2 ခု", "၂ဗူး" (digits already converted), "2 pcs", "x2".
_QTY_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*(?:ခု|ဗူး|pcs|pc|bottles?)(?![a-z])|(?<![a-z])x\s*(\d{1,2})(?!\d)")


@dataclass(frozen=True)
class Alias:
    product_id: int
    normalized_alias: str


@dataclass(frozen=True)
class ParseOutcome:
    intent: str
    product_id: int | None
    size_ml: int | None
    quantity: int
    confidence: float

    @property
    def needs_review(self) -> bool:
        return self.confidence < NEEDS_REVIEW_BELOW


def find_intent(text: str) -> str | None:
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            return intent
    return None


def find_sizes(text: str) -> list[int]:
    return list(dict.fromkeys(int(m) for m in _SIZE_RE.findall(text) if int(m) > 0))


def find_quantity(text: str) -> int:
    m = _QTY_RE.search(text)
    if not m:
        return 1
    qty = int(m.group(1) or m.group(2))
    return qty if qty > 0 else 1


def _exact_spans(text: str, alias: str) -> list[tuple[int, int]]:
    """Positions where alias occurs, not glued to other Latin letters/digits
    ("ysl y" must not match inside "ysl yellow")."""
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])")
    return [m.span() for m in pattern.finditer(text)]


def find_product(text: str, aliases: list[Alias]) -> tuple[int | None, str]:
    """Return (product_id, how) where how is exact | fuzzy | ambiguous | multiple | none.

    Exact: longest aliases claim text first, so "stw intensely" beats a shorter
    "stw" alias. An alias shared by two products, or two different products in one
    message, cannot be resolved by rules.
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


_PRODUCT_SCORE = {"exact": 0.5, "fuzzy": 0.35, "multiple": 0.25, "ambiguous": 0.0, "none": 0.0}


def parse(normalized_text: str, aliases: list[Alias]) -> ParseOutcome:
    text = normalized_text
    intent = find_intent(text)
    product_id, how = find_product(text, aliases)
    sizes = find_sizes(text)
    size_ml = sizes[0] if sizes else None
    quantity = find_quantity(text)

    if intent is None:
        if product_id is None and size_ml is None and how != "ambiguous":
            # Nothing product-related: chit-chat, thanks, addresses...
            return ParseOutcome("other", None, None, 1, 0.7)
        intent_score, intent = 0.0, "unknown"
    else:
        intent_score = 0.3

    confidence = intent_score + _PRODUCT_SCORE[how] + (0.2 if size_ml else 0.0)
    if len(sizes) > 1:
        confidence -= 0.15  # several sizes, we only store the first
    if intent == "unknown":
        confidence = min(confidence, 0.5)  # always ask a human
    return ParseOutcome(intent, product_id, size_ml, quantity, round(max(confidence, 0.0), 2))
