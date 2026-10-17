"""docs/SPEC-v4.8-change-info.md acceptance tests H1-H8: changing the delivery address / phone.
H1 is the live bug: "လိပ်စာ ပြောင်းချင်ပါတယ်" was taken as an address = agreement, and payment info went
out (the order's address even became that sentence). Customer messages in -> exact replies out ->
DB state checked (fake Telegram client)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.ai import providers, service
from app.ai.providers import FakeProvider
from app.orders import auto
from app.parser.worker import run_batch
from tests.test_after_payment import auto_on, paid_order, tap as status_tap
from tests.test_cart import PAYMENT_FOOTER, button, deliver, order_row, phones, shop, tap  # noqa: F401
from tests.test_messaging import add, scalar
from tests.test_payments import waiting_for_payment
from tests.test_web import client, log_in  # noqa: F401  (fixture)

OLD = "No. 5, Sanchaung"
LIST_END = f"ဖုန်း 09111222333၊ လိပ်စာ {OLD} ကိုပဲ ပို့ပေးရမလား။"
STW_10 = "• Stronger With You Intensely 10ml – 33,000 ကျပ်\nစုစုပေါင်း 33,000 ကျပ်ပါ။\n"
PAYMENT = STW_10 + PAYMENT_FOOTER
ASK_ADDRESS = "ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။"
ASK_PHONE = "ဖုန်းနံပါတ်အသစ် ပို့ပေးပါနော်။"
ASK_BOTH = "လိပ်စာအသစ်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါနော်။"
_n = {"next": 0}


def reply(db, body: str, customer: str = "92") -> int:
    """A customer message right now (after our last list), parsed. Returns its id."""
    _n["next"] += 1
    ext = 7000 + _n["next"]
    add(ext, body, customer=customer, when=datetime.now(UTC) + timedelta(milliseconds=_n["next"]))
    run_batch()
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(ext))


def intent(db, mid: int) -> str:
    return scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid)


def customer_address(db, customer="92") -> str:
    return scalar(db, "SELECT address FROM customers WHERE external_user_id = :e", e=customer)


def change_wanted(db, customer="92"):
    return scalar(db, "SELECT o.change_wanted FROM orders o JOIN customers c ON c.id = o.customer_id "
                      "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1", e=customer)


@pytest.fixture
def returning(shop, db):
    """A returning customer (saved phone + address) with the cart list just sent:
    "…ဖုန်း 09111222333၊ လိပ်စာ No. 5, Sanchaung ကိုပဲ ပို့ပေးရမလား။"."""
    client, token = shop
    _n["next"] = 0
    with db.begin() as c:
        cid = c.execute(text("INSERT INTO customers (channel, external_user_id, address, phone) VALUES "
                             "('telegram', '92', :a, '09111222333') RETURNING id"), {"a": OLD}).scalar()
        c.execute(text("INSERT INTO customer_phones (customer_id, phone, position) VALUES (:c, '09111222333', 1)"),
                  {"c": cid})
    add(6999, "stw intensely 10ml ယူမယ်", customer="92", when=datetime.now(UTC) - timedelta(minutes=5))
    run_batch()
    tap(client, token, scalar(db, "SELECT id FROM messages WHERE external_message_id = '6999'"))
    assert deliver(db)[0].endswith(LIST_END)
    return client, token, cid


# ---------- H1 the live bug ----------

def test_h1_live_bug_change_address_then_new_address(returning, db):
    client, token, cid = returning
    mid = reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်")
    assert intent(db, mid) == "change_info"
    label, _, _ = button(client, mid)
    assert label == "📍 Ask for the new address"
    tap(client, token, mid)
    assert deliver(db) == [ASK_ADDRESS]  # NO payment info
    assert order_row(db, "92") == ("cart", 33000, None, [])  # not confirmed, old address NOT used
    assert change_wanted(db) == "address" and customer_address(db) == OLD
    assert "Waiting for the new address from the customer" in client.get(f"/chats/{cid}?tab=cart").text

    new = reply(db, "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅")
    assert intent(db, new) == "address"
    assert button(client, new)[0] == "✅ 📍 Replace address + 💳 send payment info"
    tap(client, token, new)
    assert deliver(db) == ["လိပ်စာ ပြင်ပြီးပါပြီ – ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5\n" + PAYMENT]
    assert order_row(db, "92") == ("waiting_payment", 33000, "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5", ["09111222333"])
    assert customer_address(db) == "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5" and change_wanted(db) is None
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert f"address changed at" in page and f"(old: {OLD})" in page


def test_h1_live_bug_in_auto_mode(returning, db):
    auto_on(db)
    reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်")
    auto.run_once(datetime.now(UTC) + timedelta(seconds=5))
    assert deliver(db) == [ASK_ADDRESS]
    reply(db, "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅")
    auto.run_once(datetime.now(UTC) + timedelta(seconds=5))
    assert deliver(db) == ["လိပ်စာ ပြင်ပြီးပါပြီ – ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5\n" + PAYMENT]


def test_h1_undo_restores_everything(returning, db):
    client, token, _ = returning
    tap(client, token, reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်"))
    deliver(db)
    new = reply(db, "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅")
    tap(client, token, new)
    action = scalar(db, "SELECT id FROM quick_actions WHERE message_id = :m", m=new)
    client.post(f"/quick/{action}/undo", data={"csrf": token})
    assert order_row(db, "92") == ("cart", 33000, None, [])
    assert customer_address(db) == OLD and change_wanted(db) == "address"
    assert scalar(db, "SELECT count(*) FROM order_events WHERE kind = 'contact'") == 0


def test_h1_ok_while_waiting_never_sends_payment_info(returning, db):
    client, token, _ = returning
    tap(client, token, reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်"))
    deliver(db)
    ok = reply(db, "ok")
    tap(client, token, ok)
    assert deliver(db) == [ASK_ADDRESS]  # asked again; never payment info with the old address
    assert order_row(db, "92")[0] == "confirmed" and change_wanted(db) == "address"


@pytest.mark.parametrize("body,kind", [
    ("လိပ်စာပြောင်း", "address"), ("လိပ်စာ ပြောင်းချင်", "address"), ("လိပ်စာအသစ်", "address"),
    ("လိပ်စာ မှားနေ", "address"), ("တခြားလိပ်စာ", "address"), ("ဒီလိပ်စာ မဟုတ်ဘူး", "address"),
    ("ဖုန်းပြောင်း", "phone"), ("ဖုန်းနံပါတ်ပြောင်း", "phone"), ("ဖုန်းအသစ်", "phone"), ("change address", "address"),
    ("new address", "address"), ("change phone", "phone"), ("wrong address", "address"),
    ("လိပ်စာနဲ့ ဖုန်း ပြောင်းချင်တယ်", "both"), ("ပြောင်းမယ်", "unclear")])
def test_h_seed_phrases(body, kind):
    from app.parser.normalize import normalize
    from app.parser.rules import change_kind, parse

    text = normalize(body)
    assert parse(text, []).intent == "change_info" and change_kind(text) == kind


@pytest.mark.parametrize("body", ["no", "မဟုတ်ပါ", "မဟုတ်ဘူးရှင့်", "ပြောင်းမယ်"])
def test_h4_negative_answers(returning, db, body):
    assert intent(db, reply(db, body)) == "change_info"


# ---------- H2 "send it to THIS address" ----------

def test_h2_this_address_replaces_without_asking(returning, db):
    client, token, _ = returning
    mid = reply(db, "ဒီလိပ်စာကိုပို့ပေးပါ - လှိုင် ပြည်လမ်း ၁၀")
    assert intent(db, mid) == "address"
    tap(client, token, mid)
    assert deliver(db) == ["လိပ်စာ ပြင်ပြီးပါပြီ – လှိုင် ပြည်လမ်း 10\n" + PAYMENT]
    assert order_row(db, "92")[:3] == ("waiting_payment", 33000, "လှိုင် ပြည်လမ်း 10")
    assert customer_address(db) == "လှိုင် ပြည်လမ်း 10"


# ---------- H3 keywords alone ----------

@pytest.mark.parametrize("body", ["လိပ်စာ", "ပို့ပေးပါ", "address", "လိပ်စာ ပို့ပေးပါ"])
def test_h3_keyword_only_is_no_address_and_no_agreement(returning, db, body):
    client, token, _ = returning
    auto_on(db)
    mid = reply(db, body)
    assert intent(db, mid) != "address"
    assert button(client, mid) is None
    auto.run_once(datetime.now(UTC) + timedelta(seconds=5))
    assert deliver(db) == []  # no payment info
    assert order_row(db, "92") == ("cart", 33000, None, []) and customer_address(db) == OLD


# ---------- H4 "no" to the returning question ----------

def test_h4_no_then_phone_and_address(returning, db):
    client, token, _ = returning
    mid = reply(db, "မဟုတ်ဘူး")
    assert intent(db, mid) == "change_info"
    tap(client, token, mid)
    assert deliver(db) == [ASK_BOTH] and change_wanted(db) == "unclear"
    new = reply(db, "09444555666 ဗဟန်း ၅လမ်း အမှတ် ၇")
    tap(client, token, new)
    assert deliver(db) == ["လိပ်စာ ပြင်ပြီးပါပြီ – ဗဟန်း 5လမ်း အမှတ် 7\nဖုန်းနံပါတ် ပြင်ပြီးပါပြီ – 09444555666\n"
                           + PAYMENT]
    assert order_row(db, "92") == ("waiting_payment", 33000, "ဗဟန်း 5လမ်း အမှတ် 7", ["09444555666"])
    assert phones(db, "92") == ["09444555666", "09111222333"] and customer_address(db) == "ဗဟန်း 5လမ်း အမှတ် 7"


def test_h4_no_without_the_question_is_not_a_change(shop, db):
    _n["next"] = 0
    mid = reply(db, "မဟုတ်ဘူး", customer="93")
    assert intent(db, mid) == "other"


# ---------- H5 after payment info ----------

def test_h5_change_after_payment_info_no_resend(shop, db, tmp_path, monkeypatch):
    client, token = shop
    _n["next"] = 0
    cid = waiting_for_payment(client, token, db)  # "No. 12, Bahan", payment info sent
    sent_at = scalar(db, "SELECT payment_info_sent_at FROM orders")
    tap(client, token, reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်", customer="91"))
    assert deliver(db) == [ASK_ADDRESS]
    tap(client, token, reply(db, "ဒဂုံ ၃လမ်း အမှတ် ၉", customer="91"))
    # the line + the resume line (4.10), payment info NOT again
    assert deliver(db) == ["လိပ်စာ ပြင်ပြီးပါပြီ – ဒဂုံ 3လမ်း အမှတ် 9\nငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။"]
    assert order_row(db, "91")[:3] == ("waiting_payment", 18000, "ဒဂုံ 3လမ်း အမှတ် 9")
    assert scalar(db, "SELECT payment_info_sent_at FROM orders") == sent_at
    # the order confirmation (after the payment is approved) shows the NEW address
    from tests.test_payments import downloaded, photo

    photo(1)
    check = scalar(db, "SELECT max(id) FROM payment_checks")
    client.get(f"/payments/{check}")
    downloaded(db, tmp_path, monkeypatch, check)
    client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "18000",
                                                     "confirmed": "1"})
    [confirmation] = deliver(db)
    assert "လိပ်စာ: ဒဂုံ 3လမ်း အမှတ် 9" in confirmation and "Bahan" not in confirmation
    assert cid


# ---------- H6 after payment / after sending ----------

LOCKED = ("Order #1001 က ငွေလွှဲပြီး အတည်ပြုပြီးသားဖြစ်လို့ ပြင်ဆင်လို့ မရတော့ပါဘူးနော်။ အကူအညီလိုရင် ခဏစောင့်ပေးပါ၊ "
          "ပြန်ဆက်သွယ်ပေးပါမယ်။")


def test_h6_change_after_paid_is_locked(shop, db, tmp_path, monkeypatch):
    """docs/SPEC-v4.10-interruptions.md overrides 4.8 rule 6: a paid order is locked."""
    client, token = shop
    _n["next"] = 0
    order_id = paid_order(client, token, db, tmp_path, monkeypatch)
    tap(client, token, reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်", customer="91"))
    assert deliver(db) == [LOCKED]
    assert scalar(db, "SELECT status || ' ' || address FROM orders WHERE id = :o", o=order_id) == "paid No. 12, Bahan"
    page = client.get("/").text
    assert "customer wants to change paid Order #1001: change address / phone" in page
    request = scalar(db, "SELECT id FROM order_events WHERE kind = 'request'")
    client.post(f"/orders/requests/{request}/done", data={"csrf": token})
    assert "customer wants to change paid Order #1001" not in client.get("/").text


def test_h6_change_after_sent_out_is_locked(shop, db, tmp_path, monkeypatch):
    client, token = shop
    _n["next"] = 0
    auto_on(db)
    order_id = paid_order(client, token, db, tmp_path, monkeypatch)
    status_tap(client, token, order_id, "packed")
    status_tap(client, token, order_id, "sent_out")
    deliver(db)
    reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ်", customer="91")
    auto.run_once(datetime.now(UTC) + timedelta(seconds=5))
    assert deliver(db) == [LOCKED]  # the locked reply; nothing is changed
    assert scalar(db, "SELECT address FROM orders WHERE id = :o", o=order_id) == "No. 12, Bahan"
    assert "customer wants to change paid Order #1001: change address / phone" in client.get("/").text


# ---------- H7 phone ----------

def test_h7_change_phone_replaces_then_plain_number_adds(returning, db):
    client, token, _ = returning
    mid = reply(db, "ဖုန်းပြောင်းချင်တယ်")
    assert intent(db, mid) == "change_info"
    tap(client, token, mid)
    assert deliver(db) == [ASK_PHONE] and change_wanted(db) == "phone"
    tap(client, token, reply(db, "09444555666"))
    assert deliver(db) == ["ဖုန်းနံပါတ် ပြင်ပြီးပါပြီ – 09444555666\n" + PAYMENT]
    assert order_row(db, "92") == ("waiting_payment", 33000, OLD, ["09444555666"])
    assert phones(db, "92") == ["09444555666", "09111222333"]  # new = phone 1, old kept as phone 2
    # a plain new number without change words is ADDED (as before)
    tap(client, token, reply(db, "09777888999"))
    assert deliver(db) == ["ဖုန်းနံပါတ် 09777888999 ကိုလည်း ထည့်ထားပါပြီ။\nငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။"]  # + resume line (4.10)
    assert phones(db, "92") == ["09444555666", "09111222333", "09777888999"]


# ---------- H8 regression ----------

def test_h8_rules_certain_no_ai_call(returning, db):
    fake = FakeProvider(answer={"intent": "other"})
    providers.use(fake)
    service._not_needed.clear()
    try:
        for body in ("လိပ်စာ ပြောင်းချင်ပါတယ်", "ဖုန်းပြောင်းချင်တယ်", "change address", "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅"):
            reply(db, body)
        service.run_once()
        assert fake.requests == []
    finally:
        providers.use(None)


def test_h8_teaching_card_can_answer_change_info(shop, db):
    client, token = shop
    _n["next"] = 0
    mid = reply(db, "တခြားနေရာ ပို့ချင်လို့", customer="94")  # not a seed phrase: the card asks
    page = client.get(f"/messages/{mid}").text
    assert 'value="change_info"' in page and "လိပ်စာ / ဖုန်း ပြောင်းချင်" in page
