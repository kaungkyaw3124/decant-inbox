"""docs/SPEC-v4.17-hotfix-more-automatic.md acceptance tests S1-S6 (S7 = the full suite + evals).

The live chat 2026-10-31 10:27 (04:01 UTC): customer 91 has a paid Order #1001 and an unconfirmed cart from
40 min ago (Sauvage 10ml); ONE message asks for "swy intensely 20ml" (sold: 2 / 5 / 10 ml + full bottle) with
a new address and phone."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import Outbox
from app.orders import address, cart, holding
from app.parser.normalize import normalize
from app.parser.rules import parse
from tests.matrix_v410 import OLD_ADDRESS, make_state
from tests.test_after_payment import auto_on
from tests.test_cart import deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_v411_ai_first import auto_ai, full, now_msg, ungreet  # noqa: F401  (fixture)
from tests.test_v412_address_payment import addr
from tests.test_v46_ai import ai  # noqa: F401  (fixture)
from tests.test_web import client, log_in  # noqa: F401  (fixture)

LIVE = "Swy intensely 20ml ယူပါမယ်\n66 str 28 str ကိုပို့ပေးပါ\n09444555777"
NEW_PHONE = "09444555777"
SAUVAGE_10 = "• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်"
SIZES = "2ml – 8,000 / 5ml – 18,000 / 10ml – 33,000 / Full 100ml – 380,000 ကျပ်"
OLD_CART = "အရင်က ရွေးထားတာလည်း ပါပါတယ်၊ မလိုရင် ဖျက်ပေးပါ့မယ်။"


def ask_size(size="20ml", product="Stronger With You Intensely") -> str:
    return f"{product} က {size} မရှိပါဘူးနော်။ ရနိုင်တဲ့ size တွေ: {SIZES}။ ဘယ် size ယူမလဲ?"


def stw(db) -> int:
    return scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")


def cart_items(db) -> list[tuple]:
    with db.connect() as c:
        return [tuple(r) for r in c.execute(text(
            "SELECT p.name, i.size_ml, i.is_full_bottle FROM order_items i JOIN products p ON p.id = i.product_id "
            "JOIN orders o ON o.id = i.order_id WHERE o.order_no IS NULL AND i.removed_at IS NULL ORDER BY i.id"))]


def open_cart(db) -> tuple:
    with db.connect() as c:
        return c.execute(text("SELECT status, address, phones, address_parts FROM orders WHERE order_no IS NULL "
                              "ORDER BY id DESC LIMIT 1")).one()


@pytest.fixture
def live(shop, db):
    """The 10:27 state: paid #1001, an unconfirmed cart from 40 min ago, the "swy intensely" nickname."""
    make_state(db, "paid")
    with SessionLocal.begin() as s:
        cid = s.execute(text("SELECT id FROM customers WHERE external_user_id = '91'")).scalar()
        sauvage = s.execute(text("SELECT id FROM products WHERE name = 'Sauvage Eau de Parfum'")).scalar()
        s.execute(text("INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) SELECT id, "
                       "'swy intensely', 'swy intensely', 'seed' FROM products WHERE name = 'Stronger With You Intensely'"))
        order = cart.open_cart(s, cid, create=True)
        cart.add_items(s, order, [cart.WantedItem(sauvage, 10, False, 1, None)], None)
        order.created_at = order.list_sent_at = datetime.now(UTC) - timedelta(minutes=40)
    auto_on(db)
    return shop


def _check_s1(db, reply: str) -> None:
    assert ungreet(reply) == "\n".join([SAUVAGE_10, "စုစုပေါင်း 38,000 ကျပ်ပါ။", OLD_CART, ask_size()])
    assert "2ml –" in reply and "Stronger With You Intensely 2ml" not in reply  # no invented 2ml item
    assert cart_items(db) == [("Sauvage Eau de Parfum", 10, False)]
    status, saved, phones, parts = open_cart(db)
    assert (status, saved, phones) == ("cart", "66 str 28 str", [NEW_PHONE])
    assert parts["city"] == "မန္တလေး (Mandalay)" and parts["street"] == "66 str 28 str"


# ---------- S1 / P3 + P4: the exact 10:27 message ----------

def test_s1_live_message_rules_path(live, db):
    client, _ = live
    now_msg(db, LIVE)
    [reply] = deliver(db)
    _check_s1(db, reply)
    mid = scalar(db, "SELECT max(id) FROM messages WHERE direction = 'in'")
    assert scalar(db, "SELECT status FROM auto_runs WHERE message_id = :m", m=mid) == "replied"
    assert f'id="teach-{mid}"' not in client.get("/").text  # no Needs you card


def test_s1_live_message_ai_path(auto_ai, live, db):
    """The live AI answer (ai_calls for message 111): the product without a size (20ml is not in its list)."""
    auto_ai.answer = lambda _: {**full("buy", items=[(stw(db), None, 1, None, None)], confidence=0.88),
                                "address": addr("66 str 28 str", street="66 str 28 str", house_no="66",
                                                confidence=0.83)}
    now_msg(db, LIVE)
    [reply] = deliver(db)
    _check_s1(db, reply)


def test_s2_answer_10ml_adds_it_then_the_confirm_question(live, db):
    now_msg(db, LIVE)
    deliver(db)
    now_msg(db, "10ml", seconds=1)
    [reply] = deliver(db)
    assert cart_items(db) == [("Sauvage Eau de Parfum", 10, False), ("Stronger With You Intensely", 10, False)]
    assert ungreet(reply).endswith(f"ဖုန်း {NEW_PHONE}၊ လိပ်စာ 66 str 28 str ကိုပဲ ပို့ပေးရမလား။")
    assert OLD_ADDRESS not in reply


@pytest.mark.parametrize("answer,size", [("၁၀", 10), ("10", 10), ("ဒုတိယ", 5), ("5ml ပါ", 5), ("full", None)])
def test_s2_size_answers(live, db, answer, size):
    now_msg(db, LIVE)
    deliver(db)
    now_msg(db, answer, seconds=1)
    assert cart_items(db)[-1] == ("Stronger With You Intensely", size, size is None)


def test_s2_other_message_is_not_a_size_answer(live, db):
    now_msg(db, LIVE)
    deliver(db)
    now_msg(db, "20ml", seconds=1)  # not offered: no item, nothing invented
    assert cart_items(db) == [("Sauvage Eau de Parfum", 10, False)]


# ---------- S3 / P2: address and phone digits are never items ----------

@pytest.mark.parametrize("line", ["66 str 28 str ကိုပို့ပေးပါ", "no 12, bahan", "၆၆ လမ်း ၂၈ လမ်း", "73x45 mandalay",
                                  "28 str", "66 st x 28 st", "အမှတ် ၁၂ ရွှေဂုံတိုင်လမ်း", "35 street, mdy",
                                  "09444555777", "+959444555777", "between 73 & 74, mandalay", "no(121), 73, 45 လမ်း"])
def test_s3_address_and_phone_parts_make_no_items(line):
    result = parse(normalize(f"stw intensely 10ml ယူမယ်\n{line}", keep_newlines=True), [])
    assert [(i.unknown_text, i.size_ml) for i in result.items] == [("stw intensely", 10)]  # the order line only


def test_s3_ai_item_from_the_address_is_dropped():
    from app.ai import checker
    from app.ai.types import AIItem, AIResult

    result = AIResult("buy", (AIItem(1, "10ml", 1, None, None), AIItem(None, None, 1, "str", None)), (),
                      0.9, "r", None, address={"full_text": "66 str 28 str"})
    kept, dropped = checker.address_items(result)
    assert [i.product_id for i in kept.items] == [1] and len(dropped) == 1


def test_s3_grid_without_city_is_mandalay():
    check = address.validate("66 str 28 str")
    assert check.valid and check.parts.city == "မန္တလေး (Mandalay)"


# ---------- S4 / P1: never silent ----------

def test_s4_holding_reply_in_the_live_setup(live, db):
    """A message that goes to a person (unknown product), an earlier holding reply 40 min ago."""
    cid = scalar(db, "SELECT id FROM customers WHERE external_user_id = '91'")
    with SessionLocal.begin() as s:
        s.add(Outbox(customer_id=cid, text="(holding)", reply_kind="holding", status="sent",
                     idempotency_key="old-holding", created_at=datetime.now(UTC) - timedelta(minutes=40),
                     send_after=datetime.now(UTC) - timedelta(minutes=40)))
    deliver(db)
    mid = now_msg(db, "tobacco vanille 20ml ယူပါမယ်\n66 str 28 str ကိုပို့ပေးပါ")
    assert deliver(db) == []
    with db.begin() as c:
        c.execute(text("UPDATE messages SET received_at = now() - interval '61 seconds' WHERE id = :m"), {"m": mid})
    assert holding.run_once() == {"held": 1}
    assert ungreet(deliver(db)[0]) == "ခဏစောင့်ပေးပါနော်၊ စစ်ပြီး ပြန်ပြောပေးပါမယ်။"


# ---------- S5: full bottle without a price, unknown product ----------

def test_s5_full_bottle_without_a_price_asks_the_size(live, db):
    with db.begin() as c:
        c.execute(text("UPDATE product_prices SET price_mmk = NULL WHERE is_full_bottle AND product_id = "
                       "(SELECT id FROM products WHERE name = 'Stronger With You Intensely')"))
    now_msg(db, "stw intensely full bottle ယူမယ်")
    [reply] = deliver(db)
    assert "မရှိပါဘူးနော်" in reply and "2ml – 8,000 / 5ml – 18,000 / 10ml – 33,000 ကျပ်" in reply
    assert cart_items(db) == [("Sauvage Eau de Parfum", 10, False)]


def test_s5_unknown_product_still_goes_to_a_person(live, db):
    now_msg(db, "tobacco vanille 10ml ယူမယ်")
    assert deliver(db) == []


# ---------- S6 / P5: the old cart line ----------

def test_s6_old_cart_line_only_for_an_old_cart(live, db):
    now_msg(db, "stw intensely 5ml ယူမယ်")
    [reply] = deliver(db)
    assert OLD_CART in reply and SAUVAGE_10 in reply
    with db.begin() as c:
        c.execute(text("UPDATE orders SET created_at = now() WHERE order_no IS NULL"))
    now_msg(db, "sauvage edp 5ml ယူမယ်", seconds=2)
    assert OLD_CART not in deliver(db)[-1]
