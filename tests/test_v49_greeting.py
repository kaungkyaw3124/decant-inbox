"""docs/SPEC-v4.9-greeting.md acceptance tests I1-I6: a message that is only a greeting always gets
an answer that follows the customer's order state; not again within 30 minutes (then Needs you).
I1 is the live case: payment info sent 01:47, "hi" at 02:31 -> no reply (old 6 h rule)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.orders import auto
from app.parser.worker import run_batch
from tests.test_after_payment import auto_off, auto_on, needs, paid_order, tap as status_tap
from tests.test_cart import button, deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_payments import photo, waiting_for_payment
from tests.test_web import client, log_in  # noqa: F401  (fixture)

WAITING = ("Stronger With You Intensely 5ml အတွက် စုစုပေါင်း 18,000 ကျပ် လွှဲပြီးရင် transaction id ပါတဲ့ screenshot "
           "ပို့ပေးပါနော်။ ဘာများ ထပ်ကူညီပေးရမလဲ။")
_n = {"next": 0}


def say(db, body: str, customer: str = "91") -> int:
    """A customer message right now, parsed."""
    _n["next"] += 1
    ext = 8000 + _n["next"]
    add(ext, body, customer=customer, when=datetime.now(UTC) + timedelta(milliseconds=_n["next"]))
    run_batch()
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(ext))


def run_auto() -> None:
    auto.run_once(datetime.now(UTC) + timedelta(seconds=5))


def earlier(db, minutes: float) -> None:
    """Everything so far happened `minutes` earlier (messages, replies, orders)."""
    with db.begin() as c:
        for sql in ("UPDATE messages SET received_at = received_at - make_interval(mins => :m)",
                    "UPDATE outbox SET created_at = created_at - make_interval(mins => :m), "
                    "send_after = send_after - make_interval(mins => :m)",
                    "UPDATE orders SET payment_info_sent_at = payment_info_sent_at - make_interval(mins => :m), "
                    "list_sent_at = list_sent_at - make_interval(mins => :m)"):
            c.execute(text(sql), {"m": minutes})


@pytest.fixture(autouse=True)
def counter():
    _n["next"] = 0


def no_double(reply: str) -> None:
    assert reply.count("မင်္ဂလာပါ") <= 1


# ---------- I1 the live case ----------

def test_i1_waiting_payment_hi_gets_answered(shop, db):
    client, token = shop
    waiting_for_payment(client, token, db)  # payment info sent
    earlier(db, 44)
    auto_on(db)
    say(db, "hi")
    run_auto()
    [reply] = deliver(db)
    assert reply == WAITING  # we messaged them 44 min ago: no leading "မင်္ဂလာပါ။"
    no_double(reply)


def test_i1_after_six_hours_starts_with_greeting(shop, db):
    client, token = shop
    waiting_for_payment(client, token, db)
    earlier(db, 7 * 60)
    auto_on(db)
    say(db, "hi")
    run_auto()
    [reply] = deliver(db)
    assert reply == "မင်္ဂလာပါ။ " + WAITING
    no_double(reply)


# ---------- I2 no order; 30 min repeat window ----------

def test_i2_no_order_repeat_window_and_needs_you(shop, db):
    auto_on(db)
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။"]
    earlier(db, 10)
    second = say(db, "hi")
    run_auto()
    assert deliver(db) == []  # a greeting reply went out 10 min ago
    assert needs(db, minutes=1)["unanswered"] == []
    assert [r.message_ids for r in needs(db, minutes=2.5)["unanswered"]] == [[second]]  # maybe waiting for a person
    earlier(db, 25)  # the greeting reply was 35 min ago now
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["ဘာကူညီပေးရမလဲ။"]  # answered again (we messaged them < 6 h ago: no "မင်္ဂလာပါ။")
    assert needs(db, minutes=3)["unanswered"] == []  # that reply answers the waiting "hi" too


def test_i2_repeat_window_is_a_setting(shop, db):
    client, token = shop
    client.post("/settings/learning", data={"csrf": token, "auto_approve_after": "3", "greeting": "1",
                                            "auto_not_stocked": "1", "greeting_repeat_minutes": "5"})
    auto_on(db)
    say(db, "hi")
    run_auto()
    deliver(db)
    earlier(db, 10)
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["ဘာကူညီပေးရမလဲ။"]


# ---------- I3 open cart ----------

def test_i3_open_cart_without_phone(shop, db):
    auto_on(db)
    say(db, "stw intensely 5ml ယူမယ်")
    run_auto()
    deliver(db)  # the cart list
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n• Stronger With You Intensely 5ml – 18,000 ကျပ်\n"
                           "စုစုပေါင်း 18,000 ကျပ်ပါ။\nဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]


def test_i3_auto_off_one_tap_same_text(shop, db):
    client, token = shop
    auto_off()
    cid = None
    say(db, "stw intensely 5ml ယူမယ်")
    cid = customer_id(db, "91")
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5"})
    earlier(db, 8 * 60)
    mid = say(db, "hi")
    label, tooltip, _ = button(client, mid)
    assert label == "👋 Reply greeting"
    assert tooltip.startswith("မင်္ဂလာပါ။ ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n• Stronger With You Intensely 5ml – 18,000 ကျပ်")
    assert tooltip.splitlines()[3] == "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"


# ---------- I4 paid / sent out / payment photo ----------

def test_i4_photo_received(shop, db):
    client, token = shop
    waiting_for_payment(client, token, db)
    photo(1)
    auto_on(db)
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["ငွေလွှဲ screenshot ရပါပြီ၊ စစ်ပြီး အကြောင်းပြန်ပေးပါမယ်နော်။"]


def test_i4_paid_then_sent_out(shop, db, tmp_path, monkeypatch):
    client, token = shop
    order_id = paid_order(client, token, db, tmp_path, monkeypatch)
    auto_on(db)
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["Order #1001 ကို ပြင်ဆင်နေပါတယ်။ ဘာများ ထပ်ကူညီပေးရမလဲ။"]
    status_tap(client, token, order_id, "packed")
    status_tap(client, token, order_id, "sent_out")
    deliver(db)
    earlier(db, 8 * 60)  # also: a new day for the greeting
    say(db, "hello")
    run_auto()
    sent = scalar(db, "SELECT to_char(sent_out_at AT TIME ZONE 'Asia/Yangon', 'DD/MM/YYYY') FROM orders")
    [reply] = deliver(db)
    assert reply == f"မင်္ဂလာပါ။ Order #1001 ကို {sent} မှာ ပို့ပြီးပါပြီ။ ဘာများ ထပ်ကူညီပေးရမလဲ။"
    no_double(reply)


# ---------- I5 waiting for a new address (4.8) ----------

def test_i5_waiting_new_address(shop, db):
    client, token = shop
    with db.begin() as c:
        cid = c.execute(text("INSERT INTO customers (channel, external_user_id, address, phone) VALUES "
                             "('telegram', '91', 'No. 5, Sanchaung', '09111222333') RETURNING id")).scalar()
        c.execute(text("INSERT INTO customer_phones (customer_id, phone, position) VALUES (:c, '09111222333', 1)"),
                  {"c": cid})
    auto_on(db)
    say(db, "stw intensely 10ml ယူမယ်")
    run_auto()
    deliver(db)
    say(db, "လိပ်စာ ပြောင်းချင်ပါတယ်")
    run_auto()
    assert deliver(db) == ["ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။"]
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။"]  # asked again, no payment info
    earlier(db, 7 * 60)
    with db.begin() as c:
        c.execute(text("UPDATE outbox SET created_at = created_at - interval '1 hour'"))
    say(db, "hi")
    run_auto()
    assert deliver(db) == ["မင်္ဂလာပါ။\nပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။"]
    assert scalar(db, "SELECT status FROM orders") == "cart"


# ---------- I6 greeting + something else ----------

def test_i6_greeting_with_a_question_is_the_question(shop, db):
    auto_on(db)
    with db.begin() as c:
        c.execute(text("INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
                       "SELECT id, 'swy', 'swy', 'seed' FROM products WHERE name = 'Stronger With You Intensely'"))
    say(db, "hi swy 5ml ဘယ်လောက်လဲ")
    run_auto()
    [reply] = deliver(db)
    assert reply == "မင်္ဂလာပါ။\nStronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"
    no_double(reply)
