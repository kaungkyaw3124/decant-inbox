"""docs/SPEC-v4.13-hotfix.md acceptance tests R1-R5 (R6 = the whole suite): the two live messages of
2026-10-18 02:04, never silence (holding reply + watchdog), order_start, address cleaning, "no place
words = not an address", Mandalay grid addresses."""
import logging
import re

import pytest
from sqlalchemy import text

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
                                                                     "No 5", confidence=0.8)}
    now_msg(db, "No 5, 45 လမ်း, mandalay")  # the rules read Mandalay, the AI Yankin
    assert open_order(db)[1] is None


# ---------- R3 / Q1: never silence ----------

from datetime import UTC, datetime, timedelta  # noqa: E402

from app.orders import auto, holding  # noqa: E402
from app.parser.worker import run_batch  # noqa: E402
from tests.test_messaging import add, customer_id, scalar  # noqa: E402
from tests.test_v4_teaching import auto_on  # noqa: E402

HOLDING = "ခဏစောင့်ပေးပါနော်၊ စစ်ပြီး ပြန်ပြောပေးပါမယ်။"


def stuck(db, n: int, body: str, seconds_ago: float, customer="91") -> int:
    add(8000 + n, body, customer=customer, when=datetime.now(UTC) - timedelta(seconds=seconds_ago))
    run_batch()
    auto.run_once()
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(8000 + n))


def test_r3_watchdog_holding_reply_once_and_needs_you(shop, db, caplog):
    client, token = shop
    auto_on(db)
    cart_for(client, token, db)  # an open cart
    mid = stuck(db, 1, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", seconds_ago=30)  # a question: no automatic answer
    assert holding.run_once() == {} and deliver(db) == []  # not 60 s yet
    with db.begin() as c:
        c.execute(text("UPDATE messages SET received_at = now() - interval '90 seconds' WHERE id = :m"), {"m": mid})
    logging.getLogger("holding").disabled = False  # alembic's fileConfig (test DB setup) disables older loggers
    with caplog.at_level("WARNING", logger="holding"):
        assert holding.run_once() == {"held": 1}
    assert f"silent message caught message={mid}" in caplog.text
    assert ungreet(deliver(db)[0]) == HOLDING
    page = client.get("/").text
    assert f'id="waiting-{mid}"' in page and "customer waiting" in page
    assert page.index(f'id="waiting-{mid}"') < page.index("Needs you") + 2000  # at the top of the list
    assert holding.run_once() == {}  # the same message: never again
    mid2 = stuck(db, 2, "ဘယ်နေ့ ရနိုင်မလဲ", seconds_ago=-1)  # another one after the holding reply, within 10 min:
    later = datetime.now(UTC) + timedelta(seconds=90)
    assert holding.run_once(later) == {"caught": 1} and deliver(db) == []  # caught, no 2nd reply
    assert f'id="waiting-{mid2}"' in client.get("/").text
    # an admin answers -> the customer is no longer waiting
    page = client.get(f"/chats/{customer_id(db, '91')}").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    client.post(f"/chats/{customer_id(db, '91')}/send", data={"csrf": token, "key": key, "text": "ok"})
    assert "customer waiting" not in client.get("/").text


def test_r3_no_holding_reply_when_answered_handled_or_not_waiting(shop, db):
    client, token = shop
    auto_on(db)
    stuck(db, 1, "thanks", seconds_ago=90, customer="70")  # no order, not a buy / price message
    cart_for(client, token, db, customer="71")
    with db.begin() as c:  # a person replied from the phone 5 minutes ago
        cid = c.execute(text("SELECT id FROM customers WHERE external_user_id = '71'")).scalar()
    add(8100, "ok ပါ", customer="71", direction="out", when=datetime.now(UTC) - timedelta(minutes=5))
    stuck(db, 2, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", seconds_ago=90, customer="71")
    assert holding.run_once() == {"caught": 1} and deliver(db) == []  # caught (Needs you), no reply
    assert scalar(db, "SELECT count(*) FROM outbox WHERE reply_kind = 'holding'") == 0
    with db.begin() as c:
        c.execute(text("UPDATE customers SET auto_reply_off = true WHERE id = :c"), {"c": cid})
    stuck(db, 3, "price?", seconds_ago=90, customer="71")
    assert holding.run_once() == {}


def test_r3_auto_reply_off_means_no_watchdog(shop, db):
    client, token = shop
    cart_for(client, token, db)
    stuck(db, 1, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", seconds_ago=90)
    assert holding.run_once() == {}
