"""docs/SPEC-v4.16-hotfix-new-order-after-paid.md acceptance tests R1-R6 (R7 = the full suite).

The live chat 2026-10-31 09:46: a paid (locked) order, then ONE message with a product, a NEW phone and a NEW
address; then the address again; then the test code. Customer 91 is in the 4.10 "paid" state (Order #1001,
saved phone 09111222333, saved address "No. 5, Sanchaung")."""
import re
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import get_settings
from app.orders import address, auto
from app.parser import worker
from tests.matrix_v410 import OLD_ADDRESS, OLD_PHONE, make_state
from tests.test_after_payment import auto_on
from tests.test_cart import PAYMENT_FOOTER, deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, scalar
from tests.test_v410_interruptions import LOCKED, LOCKED_NEW
from tests.test_v411_ai_first import auto_ai, full, now_msg, ungreet  # noqa: F401  (fixture)
from tests.test_v412_address_payment import addr
from tests.test_v46_ai import ai  # noqa: F401  (fixture)
from tests.test_web import client, log_in  # noqa: F401  (fixture)

# the live 09:46 message (with a product the rules know; "swy" is in the AI test)
LIVE_BUY = "hi sauvage edp 10 ml ဝယ်ချင်လို့ပါ\n09444555777\n66 str 29 str, mandalay ကို ပို့ပေးပါ"
LIVE_AI_BUY = "hi swy 10 ml ဝယ်ချင်လို့ပါ\n09444555777\n66 str 29 str, mandalay ကို ပို့ပေးပါ"
LIVE_ADDRESS = "လိပ်စာက 66 str, 28 str mandalay ပါ"  # 09:48
NEW_PHONE = "09444555777"
SAUVAGE_10 = "• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်"


def orders(db) -> list[tuple]:
    """(status, order_no, address, phones) of customer 91, oldest first."""
    with db.connect() as c:
        return [tuple(r) for r in c.execute(text(
            "SELECT o.status, o.order_no, o.address, o.phones FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE c.external_user_id = '91' ORDER BY o.id"))]


def sauvage(db) -> int:
    return scalar(db, "SELECT id FROM products WHERE name = 'Sauvage Eau de Parfum'")


@pytest.fixture
def paid(shop, db):
    make_state(db, "paid")
    auto_on(db)
    return shop


# ---------- R1 / Q1: the new phone + address in the buy message win ----------

def _check_r1(db, reply: str) -> None:
    assert ungreet(reply) == "\n".join([LOCKED_NEW, SAUVAGE_10, "စုစုပေါင်း 38,000 ကျပ်ပါ။",
                                        f"ဖုန်း {NEW_PHONE}၊ လိပ်စာ 66 str 29 str, mandalay ကိုပဲ ပို့ပေးရမလား။"])
    assert OLD_PHONE not in reply and OLD_ADDRESS not in reply
    paid_order, new = orders(db)
    assert paid_order == ("paid", 1001, OLD_ADDRESS, [OLD_PHONE])  # unchanged
    assert new == ("cart", None, "66 str 29 str, mandalay", [NEW_PHONE])  # only the new phone


def test_r1_live_buy_rules_path(paid, db):
    now_msg(db, LIVE_BUY)
    [reply] = deliver(db)
    _check_r1(db, reply)
    parts = scalar(db, "SELECT address_parts FROM orders ORDER BY id DESC LIMIT 1")
    assert parts["city"] == "မန္တလေး (Mandalay)" and parts["street"] == "66 str 29 str"


def test_r1_live_buy_ai_path(auto_ai, paid, db):
    """What the AI answered live (ai_calls 13), with the address it read."""
    auto_ai.answer = lambda _: {**full("buy", items=[(sauvage(db), "10ml", 1, None, None)], confidence=0.96),
                                "address": addr("66 str 29 str, mandalay", street="66 str 29 str", house_no="66",
                                                city="mandalay", confidence=0.9)}
    now_msg(db, LIVE_AI_BUY)
    [reply] = deliver(db)
    _check_r1(db, reply)


def test_r1_partial_new_address_asks_the_township_not_the_old_one(paid, db):
    now_msg(db, "sauvage edp 10ml ယူမယ်\nသုခလမ်း အမှတ် ၁၂")
    [reply] = deliver(db)
    assert ungreet(reply).endswith("\nဘယ်မြို့နယ်လဲ ပြောပေးပါနော်။") and OLD_ADDRESS not in reply
    assert orders(db)[1][2] is None and scalar(db, "SELECT address_partial FROM orders ORDER BY id DESC LIMIT 1")


def test_r1_phone_only_in_the_buy_message(paid, db):
    now_msg(db, f"sauvage edp 10ml ယူမယ် {NEW_PHONE}")
    [reply] = deliver(db)
    assert f"ဖုန်း {NEW_PHONE}၊ လိပ်စာ {OLD_ADDRESS} ကိုပဲ" in reply  # no new address: the saved one is offered
    assert orders(db)[1][3] == [NEW_PHONE]


def test_r1_no_contact_in_the_message_is_unchanged(paid, db):
    now_msg(db, "sauvage edp 10ml ယူမယ်")
    [reply] = deliver(db)
    assert ungreet(reply).endswith(f"ဖုန်း {OLD_PHONE}၊ လိပ်စာ {OLD_ADDRESS} ကိုပဲ ပို့ပေးရမလား။")
    assert orders(db)[1][2:] == (None, [])


def test_r1_buy_address_undo(paid, db):
    client, token = paid
    now_msg(db, LIVE_BUY)
    action = scalar(db, "SELECT id FROM quick_actions ORDER BY id DESC LIMIT 1")
    client.post(f"/quick/{action}/undo", data={"csrf": token})
    with db.connect() as c:
        assert c.execute(text("SELECT address FROM customers WHERE external_user_id = '91'")).scalar() == OLD_ADDRESS
        assert [p for p, in c.execute(text("SELECT phone FROM customer_phones ORDER BY position"))] == [OLD_PHONE]


# ---------- R2-R4 / Q2: the open cart gets the change, not the locked order ----------

def test_r2_live_address_goes_to_the_new_cart(paid, db):
    now_msg(db, LIVE_BUY)
    deliver(db)
    now_msg(db, LIVE_ADDRESS, seconds=1)
    [reply] = deliver(db)
    assert reply != LOCKED and "Order #1001" not in reply
    assert ungreet(reply).endswith(PAYMENT_FOOTER)  # an address while "cart" = agreement (4.x): payment info
    paid_order, new = orders(db)
    assert paid_order == ("paid", 1001, OLD_ADDRESS, [OLD_PHONE])
    assert new[2] == "66 str, 28 str mandalay" and new[3] == [NEW_PHONE]


def test_r2_live_case_cart_showing_only_saved_contact(auto_ai, paid, db):
    """The exact live state: the new cart had no own contact (it only showed the saved one); the AI said
    change_info (ai_calls 15)."""
    now_msg(db, "sauvage edp 10ml ယူမယ်")
    deliver(db)
    auto_ai.answer = lambda _: {**full("change_info", confidence=0.97),
                                "address": addr("66 str, 28 str mandalay", street="66 str, 28 str", city="mandalay",
                                                change=True, confidence=0.95)}
    now_msg(db, LIVE_ADDRESS, seconds=1)
    [reply] = deliver(db)
    assert reply != LOCKED and "66 str, 28 str mandalay" in reply
    assert orders(db)[0][2] == OLD_ADDRESS and orders(db)[1][2] == "66 str, 28 str mandalay"


def test_r3_no_open_cart_change_is_still_locked(paid, db):
    now_msg(db, "လိပ်စာပြောင်းချင်တယ်")
    assert deliver(db) == [LOCKED]
    assert orders(db) == [("paid", 1001, OLD_ADDRESS, [OLD_PHONE])]


@pytest.mark.parametrize("body", ["Order #1001 လိပ်စာပြောင်းချင်တယ်", "1001 ရဲ့ လိပ်စာပြောင်းချင်တယ်",
                                  "ငွေလွှဲပြီးသား order ရဲ့ လိပ်စာပြောင်းချင်တယ်"])
def test_r4_naming_the_paid_order_is_locked_even_with_a_new_cart(paid, db, body):
    now_msg(db, "sauvage edp 10ml ယူမယ်")
    deliver(db)
    now_msg(db, body, seconds=1)
    assert deliver(db) == [LOCKED]
    assert orders(db)[0][2] == OLD_ADDRESS and orders(db)[1][0] == "cart"


def test_r4_a_phone_number_is_not_the_order_id(paid, db):
    from app.orders import steps
    from app.models import Order
    from app.core.db import SessionLocal

    with SessionLocal() as s:
        order = s.query(Order).filter(Order.order_no == 1001).one()
        assert not steps.names_order("09991001234", order) and steps.names_order("#1001", order)


# ---------- R5 / Q3: Mandalay grid with "str" ----------

@pytest.mark.parametrize("body", ["66 str 29 str, mandalay", "66 str, 28 str mandalay", "66st x 28st mandalay",
                                  "၆၆ လမ်း ၂၈ လမ်း မန္တလေး", "66 str 29 str mdy"])
def test_r5_str_grid_is_valid(body):
    check = address.validate(body)
    assert check.valid and check.parts.city == "မန္တလေး (Mandalay)"
    assert len(re.findall(r"[\d၀-၉]+", check.parts.street or "")) == 2  # both streets of the grid


def test_r5_order_line_is_not_part_of_the_address():
    check = address.from_rules(LIVE_BUY)
    assert check.valid and check.parts.full_text == "66 str 29 str, mandalay"
    assert address.from_rules("sauvage edp 10ml ယူမယ် ဗဟန်း") is None  # an order line is never an address


# ---------- R6 / Q4: the test code too early (testers only) ----------

CODE = "Test2468x"
TOO_EARLY = "🧪 Test code ရပါတယ်၊ ဒါပေမဲ့ order ကို အရင် အတည်ပြုပေးပါ (ငွေလွှဲအချက်အလက် မပို့ရသေးပါ)။"


@pytest.fixture
def tester(paid, db, monkeypatch):
    client, token = paid
    monkeypatch.setattr(get_settings(), "test_pay_code", SecretStr(CODE))
    cid = scalar(db, "SELECT id FROM customers WHERE external_user_id = '91'")
    client.post(f"/customers/{cid}/tester", data={"csrf": token, "on": "1"})
    return client, token


def code_msg(db, n: int) -> None:
    add(7900 + n, CODE, customer="91", when=datetime.now(UTC) + timedelta(seconds=5 + n))
    worker.run_batch()
    worker.scan_payments()
    auto.run_once(datetime.now(UTC) + timedelta(seconds=30))


def test_r6_confirm_ready_order_gets_payment_info_and_the_test_check(tester, db):
    now_msg(db, LIVE_BUY)
    deliver(db)
    code_msg(db, 1)
    [reply] = deliver(db)
    assert reply.endswith(PAYMENT_FOOTER) and "38,000" in reply
    assert orders(db)[1][0] == "photo_received"
    assert scalar(db, "SELECT is_test FROM payment_checks WHERE decision = 'pending'") is True


def test_r6_incomplete_order_gets_too_early(tester, db):
    with db.begin() as c:  # no saved contact: the cart asks for the phone
        c.execute(text("DELETE FROM customer_phones"))
        c.execute(text("UPDATE customers SET address = NULL"))
    now_msg(db, "sauvage edp 10ml ယူမယ်")
    deliver(db)
    code_msg(db, 1)
    assert deliver(db) == [TOO_EARLY]
    assert orders(db)[1][0] == "cart" and scalar(db, "SELECT count(*) FROM payment_checks WHERE is_test") == 0


def test_r6_no_holding_reply_for_the_code(tester, db):
    from app.orders import holding

    with db.begin() as c:
        c.execute(text("DELETE FROM customer_phones"))
    now_msg(db, "sauvage edp 10ml ယူမယ်")
    deliver(db)
    code_msg(db, 1)
    deliver(db)
    with db.begin() as c:
        c.execute(text("UPDATE messages SET received_at = now() - interval '5 minutes' WHERE external_message_id = '7901'"))
    holding.run_once()
    assert deliver(db) == []


def test_r6_non_tester_gets_nothing_special(paid, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "test_pay_code", SecretStr(CODE))
    now_msg(db, LIVE_BUY)
    deliver(db)
    code_msg(db, 1)
    assert TOO_EARLY not in deliver(db)
    assert orders(db)[1][0] == "cart" and scalar(db, "SELECT count(*) FROM payment_checks") == 1  # the 4.10 one


def test_r1_phone_only_message_on_an_open_cart_uses_only_that_phone(paid, db):
    """Q1 last bullet: the same rule for a phone-only message while a cart is open."""
    now_msg(db, "sauvage edp 10ml ယူမယ်")
    deliver(db)
    now_msg(db, NEW_PHONE, seconds=1)
    assert orders(db)[1][3] == [NEW_PHONE]
