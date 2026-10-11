import pytest

from app.parser.normalize import normalize
from app.parser.rules import Alias, find_quantity, find_sizes, parse

STW, SAUVAGE, YSL_Y, YSL_Y_EDT = 1, 2, 3, 4
ALIASES = [
    Alias(STW, "stronger with you intensely"),
    Alias(STW, "stw intensely"),
    Alias(STW, "stw intense"),
    Alias(SAUVAGE, "sauvage edp"),
    Alias(SAUVAGE, "dior sauvage"),
    Alias(YSL_Y, "ysl y edp"),
    Alias(YSL_Y, "ysl y"),
    Alias(YSL_Y_EDT, "ysl y"),  # same alias on two products -> ambiguous
    Alias(YSL_Y_EDT, "ysl y edt"),
]


def p(raw: str):
    return parse(normalize(raw), ALIASES)


@pytest.mark.parametrize(
    ("raw", "intent", "product", "size"),
    [
        # The two examples from CLAUDE.md.
        ("5ml stronger with you intensely ရှိလား", "ask_stock", STW, 5),
        ("stw intensely ၅ ml ဝယ်ချင်လို့ပါ", "buy", STW, 5),
        # Zawgyi-encoded version of the second one.
        ("stw intensely ၅ ml ဝယ္ခ်င္လို႔ပါ", "buy", STW, 5),
        ("Dior Sauvage 10mL ဘယ်လောက်လဲ", "ask_price", SAUVAGE, 10),
        ("sauvage edp price?", "ask_price", SAUVAGE, None),
        ("STW Intense ၁၀ မီလီ ယူမယ်", "buy", STW, 10),
        ("ysl y edp 3ml order", "buy", YSL_Y, 3),
        ("ysl y edt ရလား", "ask_stock", YSL_Y_EDT, None),
        # fuzzy: typo
        ("stronger with you intensly 5ml ရှိလား", "ask_stock", STW, 5),
        # buy wins over price/stock when both appear
        ("stw intensely ရှိလား ဝယ်ချင်လို့", "buy", STW, None),
    ],
)
def test_parse(raw, intent, product, size):
    r = p(raw)
    assert (r.intent, r.product_id, r.size_ml) == (intent, product, size)


def test_full_match_is_confident():
    r = p("stw intensely ၅ ml ဝယ်ချင်လို့ပါ")
    assert r.confidence == 1.0 and not r.needs_review


def test_chit_chat_is_other_and_not_flagged():
    r = p("ကျေးဇူးပါ ခင်ဗျာ")
    assert (r.intent, r.product_id, r.size_ml) == ("other", None, None)
    assert not r.needs_review


def test_product_without_intent_is_unknown_and_needs_review():
    r = p("stw intensely 5ml")
    assert (r.intent, r.product_id, r.size_ml) == ("unknown", STW, 5)
    assert r.needs_review


def test_intent_without_product_needs_review():
    r = p("10ml ရှိလား")
    assert (r.intent, r.product_id, r.size_ml) == ("ask_stock", None, 10)
    assert r.needs_review


def test_shared_alias_is_ambiguous():
    r = p("ysl y ရှိလား")
    assert r.product_id is None and r.needs_review


def test_alias_not_matched_inside_longer_word():
    assert p("ysl yellow ရှိလား").product_id is None


def test_two_products_split_into_items():  # rules-2: "နဲ့" separates items
    r = p("dior sauvage နဲ့ stw intensely ဝယ်ချင်")
    assert r.product_id == SAUVAGE and [i.product_id for i in r.items] == [SAUVAGE, STW]


def test_two_products_in_one_part_takes_first_but_needs_review():
    r = p("dior sauvage stw intensely ဝယ်ချင်")
    assert r.product_id == SAUVAGE and r.needs_review


@pytest.mark.parametrize(
    ("raw", "sizes"),
    [("5ml", [5]), ("5 ml and 10ml", [5, 10]), ("100ml", [100]), ("1.5ml", []), ("5mls", [5]),
     ("5mlx", []), ("stw", [])],
)
def test_sizes(raw, sizes):
    assert find_sizes(normalize(raw)) == sizes


@pytest.mark.parametrize(
    ("raw", "qty"),
    [("5ml", 1), ("5ml ၂ ခု", 2), ("5ml 3ဗူး", 3), ("5ml x2", 2), ("2 pcs", 2), ("sauvage xy", 1)],
)
def test_quantity(raw, qty):
    assert find_quantity(normalize(raw)) == qty
