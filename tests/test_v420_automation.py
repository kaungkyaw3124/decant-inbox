"""docs/SPEC-v4.20-automation-goal.md A2 unit checks (the flows themselves are the simulator scenarios in
tests/sim/scenarios, run by tests/sim/test_simulator.py)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.ai import checker
from app.ai.types import AIItem, AIResult
from app.core.db import SessionLocal
from app.models import Customer, Outbox
from app.orders import address, auto, cart, holding
from app.parser.normalize import normalize
from app.parser.rules import find_intent, find_quantity
from app.replies.faq import _found
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import add, scalar
from tests.test_after_payment import auto_on
from tests.test_web import client, log_in  # noqa: F401  (fixture)


@pytest.mark.parametrize("body, complaint, small", [
    ("ပစ္စည်းယိုနေတယ်", True, False), ("the bottle arrived broken", True, False), ("ပိုက်ဆံ ပြန်အမ်းပေးပါ", True, False),
    ("မှာတာနဲ့ ရတာ မတူဘူး", True, False), ("ကျေးဇူးပါ", False, True), ("Thank you so much 🙏", False, True),
    ("👍", False, True), ("ok ပါ", False, True), ("Hi", False, True), ("ဖုန်းနံပါတ်မှားနေတယ်", False, False),
    ("ok, eros 10ml", False, False), ("ခဏနော်", False, False)])
def test_complaint_and_small_talk(body, complaint, small):
    assert holding.is_complaint(body) is complaint and holding.is_small_talk(body) is small


@pytest.mark.parametrize("body, qty", [("acqua di gio 10ml ၂ဘူး ဝယ်မယ်", 2), ("stw 2ml လေး နှစ်ဘူး ဝယ်ချင်", 2),
                                       ("eros 5ml လေး ယူမယ်", 1), ("eros 10ml လေးခု", 4), ("မရှိဘူး", 1)])
def test_quantity_words(body, qty):
    assert find_quantity(normalize(body)) == qty


@pytest.mark.parametrize("body", ["66 str 28 str", "73 x 45", "between 73 & 74, 30 str"])
def test_street_grid_is_an_address(body):
    assert find_intent(normalize(body)) == "address"
    assert address.from_rules(body).valid and "Mandalay" in address.from_rules(body).parts.city


def test_address_after_the_order_words():
    check = address.from_rules("aventus 5ml ယူမယ် 09420003333 အမှတ် 12 ၊ အင်းလျားလမ်း ၊ ဗဟန်း")
    assert check.valid and check.parts.full_text == "အမှတ် 12၊ အင်းလျားလမ်း၊ ဗဟန်း" and "Bahan" in check.parts.township


def test_burmese_keyword_ends_on_a_syllable():
    assert _found("ပို့ခ", "ပို့ခ ဘယ်လောက်လဲ") and not _found("ပို့ခ", "တခြားနေရာ ပို့ချင်လို့")


def test_ai_item_gets_the_size_the_customer_said():
    result = AIResult("buy", (AIItem(20, None, 1, None, None),), (), 0.9, "15ml not listed", None)
    assert checker.said_size(result, "ysl y edp 15ml ဝယ်ချင်").items[0].size_ml == 15
    two = AIResult("buy", (AIItem(20, None, 1, None, None),), (), 0.9, "", None)
    assert checker.said_size(two, "5ml နဲ့ 10ml").items[0].size is None  # two sizes: not guessed


def test_no_size_is_never_the_full_bottle_price(shop, db):  # noqa: F811
    with SessionLocal() as s:
        stw = s.scalar(text("SELECT id FROM products WHERE name = 'Stronger With You Intensely'"))
        assert cart.price_of(s, stw, None, False) == (None, True)
        assert cart.price_of(s, stw, None, True)[0] == 380000


def test_new_order_offers_only_the_latest_phone(db):
    add(9201, "ဖုန်းနံပါတ်အသစ် 09420000009", customer="420")
    with SessionLocal.begin() as s:
        customer = s.scalar(text("SELECT id FROM customers WHERE external_user_id = '420'"))
        customer = s.get(Customer, customer)
        source = s.scalar(text("SELECT id FROM messages WHERE external_message_id = '9201'"))
        cart.set_customer_phones(s, customer, [("09420000002", None), ("09420000001", None)])
        assert cart.saved_phones(s, customer.id) == ["09420000002", "09420000001"]  # an admin's list: both
        cart.replace_phones(s, cart.open_cart(s, customer.id, create=True), customer, ["09420000009"], source)
        assert cart.customer_phones(s, customer.id)[:2] == ["09420000009", "09420000002"]
        assert cart.saved_phones(s, customer.id) == ["09420000009"]  # the replaced ones are not offered again


def test_watchdog_10_s_for_every_message_but_small_talk(shop, db):  # noqa: F811
    auto_on(db)
    now = datetime.now(UTC)
    add(9001, "ပစ္စည်းယိုနေတယ်", customer="401", when=now - timedelta(seconds=11))  # no order at all
    add(9002, "thank you", customer="402", when=now - timedelta(seconds=11))
    add(9003, "ဒီအနံ့က ဘယ်လိုလဲ", customer="403", when=now - timedelta(seconds=5))  # not 10 s yet
    from app.parser.worker import run_batch

    run_batch()
    auto.run_once(now)
    assert scalar(db, "SELECT reason FROM auto_runs r JOIN messages m ON m.id = r.message_id "
                      "WHERE m.external_message_id = '9001'") == "complaint: a person handles it"
    assert holding.run_once(now) == {"held": 1}
    with SessionLocal() as s:
        held = s.scalars(text("SELECT c.external_user_id FROM outbox o JOIN customers c ON c.id = o.customer_id "
                              "WHERE o.reply_kind = 'holding'")).all()
    assert held == ["401"]
    assert scalar(db, "SELECT count(*) FROM outbox WHERE reply_kind <> 'holding'") == 0  # never answered by itself


def test_media_replies(shop, db):  # noqa: F811
    auto_on(db)
    now = datetime.now(UTC)
    add(9101, "", customer="411", kind="other", when=now - timedelta(seconds=3))  # voice / sticker
    add(9102, "", customer="412", kind="photo", when=now - timedelta(seconds=3))  # a perfume photo, no order
    add(9103, "", customer="413", kind="other", when=now - timedelta(minutes=5))  # old (after a restart): no reply
    from app.parser.worker import run_batch

    run_batch()
    auto.run_once(now)
    with SessionLocal() as s:
        sent = dict(s.execute(text("SELECT c.external_user_id, o.text FROM outbox o JOIN customers c "
                                   "ON c.id = o.customer_id")).all())
    assert sent == {"411": "စာနဲ့ ရေးပေးပါနော်။", "412": "ဘယ် perfume လဲ နာမည်လေး ရေးပေးပါနော်။"}
    add(9104, "", customer="411", kind="other", when=now - timedelta(seconds=2))  # again within 10 min: once
    run_batch()
    auto.run_once(now)
    assert scalar(db, "SELECT count(*) FROM outbox") == 2 and Outbox
