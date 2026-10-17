"""docs/SPEC-v4.13-hotfix.md acceptance tests R1-R5 (R6 = the whole suite): the two live messages of
2026-10-18 02:04, never silence (holding reply + watchdog), order_start, address cleaning, "no place
words = not an address", Mandalay grid addresses."""
import pytest

from tests.test_cart import PAYMENT_FOOTER, deliver, shop  # noqa: F401  (fixture)
from tests.test_v411_ai_first import auto_ai, full, now_msg, ungreet  # noqa: F401  (fixture)
from tests.test_v412_address_payment import addr, cart_for, open_order
from tests.test_v46_ai import ai  # noqa: F401  (fixture)
from tests.test_web import client, log_in  # noqa: F401  (fixture)

LIVE_ADDRESS = "no(121) ,73, 45 လမ်း mandalay ကို ပို့ပေးပါဗျဖုန်းနံပါတ်က 09945827742"
LIVE_ORDER = "hi decant မှာချင်လို့ပါ"
# what the AI answered live (ai_calls id 4): valid for us, but its address confidence was 0.84
LIVE_AI = {**full("address", confidence=0.88), "address": addr(
    "no(121) ,73, 45 လမ်း mandalay", None, "73, 45 လမ်း", "no(121)", city="mandalay", missing=["township"],
    confidence=0.84)}


def test_q0_live_address_just_under_the_threshold_is_saved_when_the_rules_agree(auto_ai, shop, db):
    client, token = shop
    cart_for(client, token, db)  # the live state: a cart without phone / address
    auto_ai.answer = lambda _: LIVE_AI
    now_msg(db, LIVE_ADDRESS)
    status, saved, phones, parts, _ = open_order(db)
    assert saved == "no(121) ,73, 45 လမ်း mandalay" and phones == ["09945827742"]
    assert parts["city"] == "မန္တလေး (Mandalay)" and status == "waiting_payment"
    assert ungreet(deliver(db)[0]).endswith(PAYMENT_FOOTER)


def test_q0_disagreeing_readers_still_go_to_a_person(auto_ai, shop, db):
    client, token = shop
    cart_for(client, token, db, phone="09777123456")
    auto_ai.answer = lambda _: {**full("address"), "address": addr("No 5, 45 လမ်း, Yankin", "Yankin", "45 လမ်း",
                                                                     "No 5", confidence=0.7)}
    now_msg(db, "No 5, 45 လမ်း, mandalay")  # the rules read Mandalay, the AI Yankin
    assert open_order(db)[1] is None
