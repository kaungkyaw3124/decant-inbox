"""docs/SPEC-v4.10-interruptions.md acceptance tests J1-J6: interruptions while the shop waits for
something, the resume line, and LOCKED paid orders. Customer messages in -> exact replies out -> DB
state checked (fake Telegram client, auto mode ON)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.learning import patterns
from app.orders import auto
from app.parser.worker import run_batch
from tests.matrix_v410 import MESSAGES, OLD_ADDRESS, STATES, make_state, send
from tests.test_after_payment import auto_on
from tests.test_cart import PAYMENT_FOOTER, deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, scalar
from tests.test_payments import downloaded, photo, waiting_for_payment
from tests.test_prices import run_import, xlsx
from tests.test_v4_teaching import staff_client
from tests.test_web import client, log_in  # noqa: F401  (fixture)

STW_5, SAUVAGE_10, SAUVAGE_5 = ("• Stronger With You Intensely 5ml – 18,000 ကျပ်", "• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်",
                                "• Sauvage Eau de Parfum 5ml – 20,000 ကျပ်")
RETURNING = f"ဖုန်း 09111222333၊ လိပ်စာ {OLD_ADDRESS} ကိုပဲ ပို့ပေးရမလား။"
ASK_PHONE_CART = "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"
ASK_ADDRESS = "ပို့ပေးရမယ့် လိပ်စာ ပို့ပေးပါနော်။"
ASK_NEW_ADDRESS = "ပို့ပေးရမယ့် လိပ်စာအသစ် ပို့ပေးပါနော်။"
RESUME_PAY = "ငွေလွှဲပြီးရင် transaction id ပါတဲ့ screenshot ပို့ပေးပါနော်။"
HOLD = "စစ်ပြီး ပြန်ပြောပေးပါမယ်နော်။"
LOCKED = ("Order #1001 က ငွေလွှဲပြီး အတည်ပြုပြီးသားဖြစ်လို့ ပြင်ဆင်လို့ မရတော့ပါဘူးနော်။ အကူအညီလိုရင် ခဏစောင့်ပေးပါ၊ "
          "ပြန်ဆက်သွယ်ပေးပါမယ်။")
LOCKED_NEW = "Order #1001 ကတော့ အတည်ပြုပြီးသားပါ။ ဒါကို order အသစ်အနေနဲ့ ယူပေးပါမယ်နော်။"
PRICE = "Sauvage Eau de Parfum 5ml က 20,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"
OFFER = "ဒီ order ထဲ ထည့်ပေးရမလား။"
FAQ = "အားလုံး authentic (original) ပစ္စည်းတွေ ကနေ ခွဲထည့်ပေးတာပါနော်။"
CANCELLED = "အော်ဒါ cancel လုပ်ပြီးပါပြီ။ နောက်မှ ပြန်မှာချင်ရင် ပြောပေးပါနော်။"
ASK_SCREENSHOT = "transaction id ပါတဲ့ screenshot လေး ပို့ပေးပါနော်။"
CHOOSE = ("အရင်က ယူထားတာတွေပါ –\n1. Stronger With You Intensely 5ml\n2. Sauvage Eau de Parfum 10ml\n"
          "ဘယ်ဟာလဲ နံပါတ်လေး ပြောပေးပါနော်။")
CART_LIST = f"{STW_5}\n{SAUVAGE_10}\nစုစုပေါင်း 56,000 ကျပ်ပါ။"
PAYMENT_56 = f"{CART_LIST}\n{PAYMENT_FOOTER}"
ADDRESS_NEW = "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5"
# the step the shop waits for, by state: the resume line added after an answer to something else
RESUME = {"cart": RETURNING, "need_phone": ASK_PHONE_CART, "need_address": ASK_ADDRESS,
          "waiting_new_info": ASK_NEW_ADDRESS, "waiting_payment": RESUME_PAY}
GREETING = {
    "browsing": "ဘာကူညီပေးရမလဲ။", "delivered": "ဘာကူညီပေးရမလဲ။",
    "cart": f"ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n{CART_LIST}\n{RETURNING}",
    "need_phone": f"ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n{CART_LIST}\n{ASK_PHONE_CART}",
    "need_address": f"ခြင်းထဲမှာ ဒါတွေ ရှိပါတယ် –\n{CART_LIST}\n{ASK_ADDRESS}",
    "waiting_new_info": ASK_NEW_ADDRESS,
    "waiting_payment": "Stronger With You Intensely 5ml, Sauvage Eau de Parfum 10ml အတွက် စုစုပေါင်း 56,000 ကျပ် "
                       f"{RESUME_PAY.replace('ငွေလွှဲပြီးရင်', 'လွှဲပြီးရင်')} ဘာများ ထပ်ကူညီပေးရမလဲ။",
    "photo_received": "ငွေလွှဲ screenshot ရပါပြီ၊ စစ်ပြီး အကြောင်းပြန်ပေးပါမယ်နော်။",
    "paid": "Order #1001 ကို ပြင်ဆင်နေပါတယ်။ ဘာများ ထပ်ကူညီပေးရမလဲ။",
    "packed": "Order #1001 ကို ပြင်ဆင်နေပါတယ်။ ဘာများ ထပ်ကူညီပေးရမလဲ။",
}

# J1: the expected outcome of every (message, state) cell. Codes are explained in OUTCOMES below.
TABLE = """
message        browsing cart     need_phone need_address waiting_new_info waiting_payment photo_received paid     packed   sent_out delivered
buy_known      add      add      add        add          add              pay+            hold           new      new      new      add
buy_unknown    card     card     card       card         card             holdcard        holdcard       card     card     card     card
remove         none     remove   remove     remove       remove           pay-            hold           locked   locked   locked   locked
cancel_order   unans    cancel   cancel     cancel       cancel           cancel          keep           keep     keep     keep     unans
ask_price      price    price    price      price        price            offer           price          price    price    price    price
ask_stock      price    price    price      price        price            offer           price          price    price    price    price
faq            faq      faq      faq        faq          faq              faq             faq            faq      faq      faq      faq
question       ask      ask      ask        ask          ask              ask             ask            ask      ask      ask      ask
greeting       greet    greet    greet      greet        greet            greet           greet          greet    greet    sent     greet
address        none     pay      askphone   pay          changed          addr            hold           locked   locked   locked   locked
phone          none     pay      phone      phone        pay              phone+          hold           locked   locked   locked   locked
change_info    none     asknew   asknew     asknew       asknew           asknew          hold           locked   locked   locked   locked
paid_no_photo  unans    unans    unans      unans        unans            shot            check          unans    unans    unans    unans
photo          name     name     name       unans        name             photo           unans          unans    unans    unans    name
previous_item  card     choose   choose     choose       choose           choose          hold           choose   choose   choose   choose
ask_delivery   unans    unans    unans      unans        unans            unans           unans          status   status   status   unans
"""
OUTCOMES = {
    # code: what the customer gets (exact reply, None = nothing) and what changes
    "add": "the cart list with Sauvage 5ml added + the closing question of the step",
    "pay+": "same order, still waiting for payment, new total 76,000 + payment info again",
    "pay-": "same order, still waiting for payment, new total 38,000 + payment info again",
    "hold": "“we'll check” + Needs you request; nothing changed (payment screenshot being checked)",
    "holdcard": "“we'll check” + teaching card for the unknown item; nothing changed",
    "new": "paid order locked: “Order #1001 ... order အသစ်” + a NEW cart with the item",
    "card": "no reply; teaching card in Needs you",
    "none": "no reply; nothing changed",
    "unans": "no reply; unanswered in Needs you after 2 min",
    "remove": "Stronger With You removed: list of what is left + the step's question",
    "locked": "order_locked reply + Needs you request; the paid order is unchanged",
    "cancel": "the order is cancelled + cancel reply",
    "keep": "no reply (money involved: the admin decides); order unchanged",
    "price": "the price + the resume line of the step",
    "offer": "the price + “add it to this order?” + the resume line",
    "faq": "the FAQ answer + the resume line of the step",
    "ask": "no reply; teaching card + unanswered (a person answers)",
    "greet": "the 4.9 greeting for the state",
    "sent": "the 4.9 greeting with the sent-out date",
    "askphone": "address saved; ask the phone",
    "pay": "contact complete: payment info",
    "changed": "“address changed” + payment info (4.8)",
    "addr": "“address changed” + the resume line (payment info not sent again)",
    "phone": "phone saved + ask the address",
    "phone+": "phone added + the resume line",
    "asknew": "ask for the new address (4.8)",
    "shot": "“send the screenshot”",
    "check": "“we'll check” (the screenshot is in Payments)",
    "photo": "no reply; a payment check to do",
    "name": "“which perfume? write the name” (docs/SPEC-v4.20 A2: a photo when no payment is due)",
    "choose": "numbered list of earlier items",
    "status": "the delivery status of the paid order",
}


def _cells() -> list[tuple[str, str, str]]:
    rows = [line.split() for line in TABLE.strip().splitlines()]
    header = rows[0][1:]
    assert tuple(header) == STATES
    cells = [(row[0], state, code) for row in rows[1:] for state, code in zip(header, row[1:], strict=True)]
    assert sorted({m for m, _, _ in cells}) == sorted(MESSAGES)  # every message x every state
    assert {c for _, _, c in cells} <= set(OUTCOMES)
    return cells


def _resumed(first: str, state: str) -> str:
    return f"{first}\n{RESUME[state]}" if state in RESUME else first


def check(state: str, message: str, code: str, r) -> None:
    open_before = {"browsing": None, "need_address": "confirmed", "waiting_payment": "waiting_payment",
                   "photo_received": "photo_received"}.get(state, None if state in ("paid", "packed", "sent_out",
                                                                                     "delivered") else "cart")
    paid = state in ("paid", "packed", "sent_out", "delivered")
    one = r.replies[0] if len(r.replies) == 1 else None
    if code in ("card", "none", "unans", "ask", "keep", "photo"):
        assert r.replies == []
        assert r.card == (code in ("card", "ask"))
        assert r.unanswered == (code in ("unans", "ask"))
        assert r.requests == 0
        if code == "photo":
            assert r.payment_check and r.open_status == "photo_received"
        elif state != "browsing" and message not in ("photo",):
            assert r.open_status == open_before and r.open_items == (2 if open_before else 0)
    elif code == "name":
        assert r.replies == ["ဘယ် perfume လဲ နာမည်လေး ရေးပေးပါနော်။"] and not r.card and not r.requests
    elif code == "add":
        closing = {"browsing": RETURNING, "delivered": RETURNING, "need_address": ASK_ADDRESS}.get(state, RESUME.get(state))
        lines = [STW_5, SAUVAGE_10] if state not in ("browsing", "delivered") else []
        total = "76,000" if lines else "20,000"
        assert one == "\n".join([*lines, SAUVAGE_5, f"စုစုပေါင်း {total} ကျပ်ပါ။", closing])
        assert r.open_items == len(lines) + 1
    elif code in ("pay+", "pay-"):
        lines = [STW_5, SAUVAGE_10, SAUVAGE_5] if code == "pay+" else [SAUVAGE_10]
        total = "76,000" if code == "pay+" else "38,000"
        assert one == "\n".join([*lines, f"စုစုပေါင်း အသစ် {total} ကျပ်ပါ။", PAYMENT_FOOTER])
        assert (r.open_status, r.open_items) == ("waiting_payment", len(lines))
    elif code in ("hold", "holdcard"):
        assert one == HOLD
        assert (r.open_status, r.open_items, r.open_total) == (open_before, 2, 56000)  # nothing changed
        assert r.open_address == OLD_ADDRESS
        assert r.requests == (1 if state == "photo_received" else 0)
        assert r.card == (code == "holdcard")
    elif code == "new":
        assert one == "\n".join([LOCKED_NEW, SAUVAGE_5, "စုစုပေါင်း 20,000 ကျပ်ပါ။", RETURNING])
        assert (r.open_status, r.open_items, r.paid_items, r.paid_status) == ("cart", 1, 2, state)
    elif code == "locked":
        assert one == LOCKED
        assert (r.paid_status, r.paid_items, r.paid_address, r.requests, r.open_status) == (
            state, 2, OLD_ADDRESS, 1, None)
    elif code == "remove":
        closing = ASK_ADDRESS if state == "need_address" else RESUME[state]
        assert one == "\n".join([SAUVAGE_10, "စုစုပေါင်း 38,000 ကျပ်ပါ။", closing])
        assert r.open_items == 1
    elif code == "cancel":
        assert one == CANCELLED and r.open_status is None
    elif code == "price":
        assert one == _resumed(PRICE, state)
        assert r.open_items == (2 if open_before else 0)
    elif code == "offer":
        assert one == f"{PRICE}\n{OFFER}\n{RESUME_PAY}"
        assert r.open_items == 2
    elif code == "faq":
        assert one == _resumed(FAQ, state)
    elif code == "greet":
        assert one == GREETING[state]
    elif code == "sent":
        assert one.startswith("Order #1001 ကို ") and one.endswith(" မှာ ပို့ပြီးပါပြီ။ ဘာများ ထပ်ကူညီပေးရမလဲ။")
    elif code == "askphone":
        assert one == "ဆက်သွယ်ရန် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"
        assert r.open_address == ADDRESS_NEW
    elif code == "pay":
        assert one == f"{PAYMENT_56}"
        assert r.open_status == "waiting_payment"
    elif code == "changed":
        assert one == f"လိပ်စာ ပြင်ပြီးပါပြီ – {ADDRESS_NEW}\n{PAYMENT_56}"
        assert (r.open_status, r.open_address) == ("waiting_payment", ADDRESS_NEW)
    elif code == "addr":
        assert one == f"လိပ်စာ ပြင်ပြီးပါပြီ – {ADDRESS_NEW}\n{RESUME_PAY}"
        assert (r.open_status, r.open_address) == ("waiting_payment", ADDRESS_NEW)
    elif code == "phone":
        assert one == f"ဖုန်းနံပါတ် 09444555666 ရပါပြီ။ {ASK_ADDRESS}"
        assert "09444555666" in r.open_phones
    elif code == "phone+":
        assert one == f"ဖုန်းနံပါတ် 09444555666 ကိုလည်း ထည့်ထားပါပြီ။\n{RESUME_PAY}"
        assert "09444555666" in r.open_phones and r.open_status == "waiting_payment"
    elif code == "asknew":
        assert one == ASK_NEW_ADDRESS
        assert r.open_status == open_before  # payment info waits for the new address
    elif code == "shot":
        assert one == ASK_SCREENSHOT
    elif code == "check":
        assert one == HOLD and r.payment_check
    elif code == "choose":
        assert one == CHOOSE
        assert r.paid_items == (2 if paid else 0)
    elif code == "status":
        assert one.startswith("Order #1001 ")
    else:
        raise AssertionError(code)


@pytest.mark.parametrize("message,state,code", _cells())
def test_j1_state_x_message(shop, db, message, state, code):
    make_state(db, state)
    auto_on(db)
    r = send(db, message)
    check(state, message, code, r)


# ---------- J2 the owner's story ----------

def _msg(db, n: int, body: str, customer="91", minutes=0) -> int:
    add(8000 + n, body, customer=customer, when=datetime.now(UTC) + timedelta(minutes=minutes, milliseconds=n))
    run_batch()
    auto.run_once(datetime.now(UTC) + timedelta(minutes=minutes, seconds=5))
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(8000 + n))


def _open(db, customer="91"):
    with db.connect() as c:
        return c.execute(text(
            "SELECT o.status, o.total_mmk, o.address, o.order_no, o.id FROM orders o JOIN customers c "
            "ON c.id = o.customer_id WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


def test_j2_owner_story(shop, db, tmp_path, monkeypatch):
    client, token = shop
    run_import(xlsx(["Armaf", "Liquid Brun", 100, 90000, None, 8000, 15000, "yes"],  # sold (the owner's case)
                    ["Emporio Armani", "Stronger With You", 100, 300000, None, 15000, 28000, "yes"]),
               {2: "new", 3: "new"})
    with db.begin() as c:
        for name, alias in (("Liquid Brun", "liquid brun"), ("Stronger With You", "swy")):
            c.execute(text("INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
                           "SELECT id, CAST(:a AS text), CAST(:a AS text), 'seed' FROM products WHERE name = :n AND NOT EXISTS "
                           "(SELECT 1 FROM product_aliases WHERE normalized_alias = CAST(:a AS text))"), {"n": name, "a": alias})
    waiting_for_payment(client, token, db)  # STW 5ml, 18,000; payment info sent
    auto_on(db)
    _msg(db, 1, "liquid brun 10ml လည်းယူမယ်")
    [text1] = deliver(db)
    assert text1 == ("• Stronger With You Intensely 5ml – 18,000 ကျပ်\n• Liquid Brun 10ml – 15,000 ကျပ်\n"
                     f"စုစုပေါင်း အသစ် 33,000 ကျပ်ပါ။\n{PAYMENT_FOOTER}")
    assert _open(db)[:2] == ("waiting_payment", 33000)
    _msg(db, 2, "လိပ်စာ ပြောင်းချင်ပါတယ်", minutes=1)
    assert deliver(db) == [ASK_NEW_ADDRESS]
    _msg(db, 3, "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅", minutes=2)
    [text3] = deliver(db)
    assert text3.startswith(f"လိပ်စာ ပြင်ပြီးပါပြီ – {ADDRESS_NEW}")
    assert _open(db)[2] == ADDRESS_NEW
    _msg(db, 4, "hi", minutes=3)
    [text4] = deliver(db)
    assert "စုစုပေါင်း 33,000 ကျပ်" in text4
    photo(1)
    check_id = scalar(db, "SELECT max(id) FROM payment_checks")
    client.get(f"/payments/{check_id}")
    downloaded(db, tmp_path, monkeypatch, check_id)
    page = client.post(f"/payments/{check_id}/approve", data={"csrf": token, "transaction_id": "TX1",
                                                              "amount": "18000", "method": "KPay"}).text
    assert "18,000 → 33,000 ကျပ်" in page  # old / new totals on the warning
    assert "Amount 18,000 ≠ order total 33,000 ကျပ်." in page
    client.post(f"/payments/{check_id}/reject", data={"csrf": token, "reason": "wrong_amount", "amount": "18000"})
    assert any("15,000" in t for t in deliver(db))  # asks the remaining amount
    photo(2, seconds_ago=0)
    check2 = scalar(db, "SELECT max(id) FROM payment_checks")
    client.get(f"/payments/{check2}")
    downloaded(db, tmp_path, monkeypatch, check2, content=b"\xff\xd8shot2")
    client.post(f"/payments/{check2}/approve", data={"csrf": token, "transaction_id": "TX2", "amount": "33000",
                                                     "method": "KPay", "confirmed": "1"})
    deliver(db)
    status, total, address, order_no, paid_id = _open(db)
    assert (status, order_no) == ("paid", 1001)
    _msg(db, 5, "swy 5ml လည်းယူမယ်", minutes=10)
    [text5] = deliver(db)
    assert text5.startswith(LOCKED_NEW + "\n")
    assert _open(db)[0] == "cart" and _open(db)[4] != paid_id  # a NEW cart
    # docs/SPEC-v4.16 Q2: with a new cart open, only a message naming the paid order gets the locked reply
    _msg(db, 6, "Order #1001 ရဲ့ လိပ်စာပြောင်းချင်တယ်", minutes=11)
    assert deliver(db) == [LOCKED]
    with db.connect() as c:
        assert c.execute(text("SELECT address, total_mmk, status FROM orders WHERE id = :o"),
                         {"o": paid_id}).one() == (ADDRESS_NEW, 33000, "paid")  # nothing changed
    home = client.get("/").text
    assert "customer wants to change paid Order #1001" in home


# ---------- J3 resume line: at most every 10 min, never doubled ----------

def test_j3_resume_line_once_per_10_minutes(shop, db):
    make_state(db, "waiting_payment")
    auto_on(db)
    r = send(db, "faq")
    assert r.replies == [f"{FAQ}\n{RESUME_PAY}"]
    add(9101, "authentic လား", customer="91", when=datetime.now(UTC) + timedelta(minutes=5))
    run_batch()
    auto.run_once(datetime.now(UTC) + timedelta(minutes=5, seconds=5))
    assert deliver(db) == [FAQ]  # 5 min later: no resume line
    add(9102, "authentic လား", customer="91", when=datetime.now(UTC) + timedelta(minutes=12))
    run_batch()
    auto.run_once(datetime.now(UTC) + timedelta(minutes=12, seconds=5))
    assert deliver(db) == [f"{FAQ}\n{RESUME_PAY}"]  # 12 min after the first: again
    # the setting: 0 = every time
    with SessionLocal.begin() as s:
        patterns.set_settings(s, {**patterns.settings(s), "resume_line_minutes": 0}, None)
    add(9103, "authentic လား", customer="91", when=datetime.now(UTC) + timedelta(minutes=13))
    run_batch()
    auto.run_once(datetime.now(UTC) + timedelta(minutes=13, seconds=5))
    assert deliver(db) == [f"{FAQ}\n{RESUME_PAY}"]


def test_j3_no_resume_when_the_reply_asks_for_the_step(shop, db):
    make_state(db, "waiting_payment")
    auto_on(db)
    r = send(db, "remove")  # payment info again: it already says "send the screenshot"
    assert r.replies[0].count(RESUME_PAY) == 1


def test_j3_admin_reply_gets_the_resume_line_as_suggestion(shop, db):
    client, _ = shop
    make_state(db, "waiting_payment")
    cid = scalar(db, "SELECT id FROM customers WHERE external_user_id = '91'")
    page = client.get(f"/chats/{cid}").text
    assert RESUME_PAY in page  # pre-filled in the editor; the admin may delete it
    assert "waiting payment" in page  # the step badge


# ---------- J4 photo_received: change requests wait for a person ----------

def test_j4_photo_received_add_item_changes_nothing(shop, db):
    client, token = shop
    make_state(db, "photo_received")
    auto_on(db)
    r = send(db, "buy_known")
    assert r.replies == [HOLD]
    assert (r.open_status, r.open_items, r.open_total, r.requests) == ("photo_received", 2, 56000, 1)
    home = client.get("/").text
    assert "add items after the payment screenshot" in home
    event = scalar(db, "SELECT id FROM order_events WHERE kind = 'request'")
    client.post(f"/orders/requests/{event}/done", data={"csrf": token, "back": "/"})
    assert "after the payment screenshot" not in client.get("/").text


# ---------- J5 the owner may edit a locked order (reason + audit); staff may not ----------

def test_j5_edit_locked_order(shop, db):
    client, token = shop
    make_state(db, "paid")
    order_id = scalar(db, "SELECT id FROM orders WHERE order_no = 1001")
    item = scalar(db, "SELECT min(id) FROM order_items WHERE order_id = :o", o=order_id)
    page = client.get("/orders?tab=all").text
    assert "🔒 #1001" in page and "Edit locked order" in page
    form = {"csrf": token, "address": "No. 9, Dagon", "phones": "09111222333", "remove_item": str(item),
            "back": "/orders?tab=all"}
    client.post(f"/orders/{order_id}/edit-locked", data={**form, "reason": ""})
    assert scalar(db, "SELECT address FROM orders WHERE id = :o", o=order_id) == OLD_ADDRESS  # no reason: no change
    client.post(f"/orders/{order_id}/edit-locked", data={**form, "reason": "customer moved, called the owner"})
    assert scalar(db, "SELECT address FROM orders WHERE id = :o", o=order_id) == "No. 9, Dagon"
    assert scalar(db, "SELECT total_mmk FROM orders WHERE id = :o", o=order_id) == 38000
    assert scalar(db, "SELECT details->>'reason' FROM audit_log WHERE action = 'order.edit_locked'") == \
        "customer moved, called the owner"
    staff, staff_token = staff_client(db)
    assert "Edit locked order" not in staff.get("/orders?tab=all").text
    r = staff.post(f"/orders/{order_id}/edit-locked", data={**form, "csrf": staff_token, "reason": "x y z"},
                   follow_redirects=False)
    assert r.status_code == 403
    assert scalar(db, "SELECT count(*) FROM audit_log WHERE action = 'order.edit_locked'") == 1


# ---------- J6 rules-certain messages never call the AI ----------

def test_j6_rules_certain_no_ai_call(shop, db):
    from app.ai import providers
    from app.ai.providers import FakeProvider
    from app.ai import settings as ai_settings

    fake = FakeProvider({})
    providers.use(fake)
    try:
        with SessionLocal.begin() as s:
            ai_settings.save(s, {**ai_settings.load(s), "mode": "auto"}, None)
        make_state(db, "waiting_payment")
        auto_on(db)
        r = send(db, "buy_known")
        assert r.open_total == 76000
        assert fake.requests == []
    finally:
        providers.use(None)
