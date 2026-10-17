"""docs/SPEC-v4.12-address-payment-ai.md acceptance tests P1-P10 (fake AI provider; no network).

N0 repair + guard, N1 AI address assistant, N2 address gates, N3 AI payment-screenshot reader,
N4 /ai switches and counts."""
import re
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.orders import address
from scripts import repair_addresses
from tests.test_cart import deliver, order_row, say, shop, tap  # noqa: F401  (fixture)
from tests.test_messaging import customer_id, scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)

BAD = "လိပ်စာ ပြောင်းချင်ပါတယ်"


def send_payment_info(client, token, cid: int) -> str:
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)
    r = client.post(f"/chats/{cid}/send", data={"csrf": token, "key": key, "reply_kind": "payment_info",
                                                 "text": "info"})
    return r.headers.get("location", "")


def confirmed_cart(client, token, db, customer="91", address_text="No. 12, Bahan") -> int:
    """A confirmed cart (Stronger With You Intensely 5ml) with a phone (and an address if given)."""
    say(db, 0, "hi", customer=customer)
    cid = customer_id(db, customer)
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(stw), "size": "5"})
    client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
    client.post(f"/chats/{cid}/cart/phones", data={"csrf": token, "phone": "09777123456"})
    if address_text:
        client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": address_text})
    return cid


def flags(db, customer="91") -> tuple:
    with db.connect() as c:
        return c.execute(text(
            "SELECT o.address_invalid, c.address_invalid FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


def repair(monkeypatch, capsys) -> str:
    monkeypatch.setattr(sys, "argv", ["repair_addresses"])
    assert repair_addresses.main() == 0
    return capsys.readouterr().out


# ---------- the validator ----------

@pytest.mark.parametrize("raw, status, township", [
    (BAD, "invalid", None),
    ("ဒီကိုပို့ပေးပါ ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅", "valid", "Bahan"),
    ("သုခလမ်း အမှတ် ၁၂", "partial", None),
    ("ရန်ကင်း", "invalid", "Yankin"),  # a township alone is shorter than 8 characters
    ("No 5, Bo Aung Kyaw St, Kyauktada Township, Yangon", "valid", "Kyauktada"),
    ("ပြည်လမ်း အမှတ် ၄၅ ကမာရွတ်", "valid", "Kamayut"),  # "ပြည်လမ်း" is a street, not Pyay
    ("ပြည်သူ့ဆေးရုံ နား အမှတ် 5", "partial", None),  # "ပြည်သူ့" is no township either
    ("35 လမ်း 80x81 ကြား မန္တလေး", "valid", None),  # city + street
    ("No 7 Shwe Taung Gyar Rd, Zigon township", "invalid", None),  # unknown township
    ("address", "invalid", None),
])
def test_validator(raw, status, township):
    check = address.validate(raw)
    assert check.status == status
    assert (check.township.en if check.township else None) == township
    assert "ပို့ပေးပါ" not in check.parts.full_text and "ဒီကို" not in check.parts.full_text


def test_validator_never_keeps_a_phone():
    check = address.validate("ဗဟန်း သုခလမ်း အမှတ် ၅ ဖုန်း ၀၉၇၇၇၁၂၃၄၅၆")
    assert check.valid and "၀၉၇" not in check.parts.full_text and "ဖုန်း" not in check.parts.full_text
    assert check.parts.full_text == "ဗဟန်း သုခလမ်း အမှတ် ၅"  # digits as written


# ---------- P1 N0: the live data case ----------

def test_p1_repair_marks_invalid_and_blocks_payment_info(shop, db, monkeypatch, capsys):
    client, token = shop
    cid = confirmed_cart(client, token, db, address_text=None)
    with db.begin() as c:  # left-over damage from the 4.8 bug (saved before the validator existed)
        c.execute(text("UPDATE orders SET address = :a"), {"a": BAD})
        c.execute(text("UPDATE customers SET address = :a WHERE external_user_id = '91'"), {"a": BAD})
    out = repair(monkeypatch, capsys)
    assert re.search(r"order id=\d+ no order ID confirmed: invalid \(keywords\)", out) and "customer id=" in out
    assert BAD not in out  # ids and reasons only
    assert flags(db) == (True, True)
    page = client.get(f"/chats/{cid}?tab=cart").text
    assert "⚠️ invalid address" in page and "Next: Send payment info" not in page
    assert "The address is not valid: fix it in the cart panel." in page
    page = client.get(f"/chats/{cid}?compose=payment_info").text
    assert "The address is not valid: fix it in the cart panel." in page and 'name="key"' not in page
    assert scalar(db, "SELECT count(*) FROM outbox WHERE reply_kind = 'payment_info'") == 0
    assert order_row(db)[0] == "confirmed"
    # the invalid address is never offered as "same as last time"
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": BAD})  # the validator refuses it
    assert flags(db) == (True, True)
    client.post(f"/chats/{cid}/cart/address", data={"csrf": token, "address": "No. 5, Sanchaung"})
    assert flags(db) == (False, False) and order_row(db)[2] == "No. 5, Sanchaung"
    assert "Next: Send payment info" in client.get(f"/chats/{cid}?tab=cart").text
    send_payment_info(client, token, cid)
    assert order_row(db)[0] == "waiting_payment"
    assert "0 invalid address(es) marked." in repair(monkeypatch, capsys)  # idempotent


def test_p1_paid_order_fixed_with_edit_locked_order(shop, db, monkeypatch, capsys):
    client, token = shop
    confirmed_cart(client, token, db, address_text=None)
    with db.begin() as c:
        c.execute(text("UPDATE orders SET address = :a, status = 'paid', order_no = 1001, paid_at = now()"),
                  {"a": BAD})
        c.execute(text("UPDATE customers SET address = :a WHERE external_user_id = '91'"), {"a": BAD})
    assert "#1001 paid: invalid (keywords)" in repair(monkeypatch, capsys)
    page = client.get("/orders?tab=all").text
    assert "⚠️ invalid address" in page
    oid = scalar(db, "SELECT id FROM orders")
    form = {"csrf": token, "address": BAD, "phones": "09777123456", "reason": "customer sent the new address",
            "back": "/orders?tab=all"}
    client.post(f"/orders/{oid}/edit-locked", data=form)
    assert flags(db) == (True, True)  # still invalid: refused
    client.post(f"/orders/{oid}/edit-locked", data={**form, "address": "No. 9, Thida St, Dagon"})
    assert flags(db) == (False, False)
    assert scalar(db, "SELECT address FROM customers WHERE external_user_id = '91'") == "No. 9, Thida St, Dagon"
    assert "⚠️ invalid address" not in client.get("/orders?tab=all").text


# ---------- P4: keyword-only / change requests never become an address ----------

@pytest.mark.parametrize("body", [BAD, "လိပ်စာ", "ပို့ပေးပါ", "address", "ဒီလိပ်စာကို ပို့ပေးပါ", "change address",
                                  "လိပ်စာ အသစ် ပို့ပေးမယ်နော်"])
def test_p4_keywords_never_an_address(shop, db, body):
    client, token = shop
    confirmed_cart(client, token, db, address_text=None)
    mid = say(db, 5, body)
    with SessionLocal() as s:
        from app.models import Message

        assert address.read_message(s, s.get(Message, mid)) is None
    from tests.test_cart import button

    b = button(client, mid)
    assert b is None or "Save address" not in b[0]
    assert order_row(db)[2] is None


# ---------- N1: the AI address assistant (fake provider, AUTO mode) ----------

from app.ai import service  # noqa: E402
from tests.test_cart import PAYMENT_FOOTER  # noqa: E402
from tests.test_v411_ai_first import auto_ai, full, now_msg, ungreet  # noqa: E402, F401  (fixture)
from tests.test_v46_ai import ai, calls, mode  # noqa: E402, F401  (fixture)
from tests.test_v4_teaching import auto_on  # noqa: E402

LIVE_P2 = "ဒီကိုပို့ပေးပါ ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅ ဖုန်း 09777123456"
ASK_TOWNSHIP = "ဘယ်မြို့နယ်လဲ ပြောပေးပါနော်။"


def addr(full_text, township=None, street=None, house_no=None, city=None, missing=(), change=False,
         confidence=0.95, ward=None) -> dict:
    return {"full_text": full_text, "house_no": house_no, "street": street, "ward_or_quarter": ward,
            "township": township, "city": city, "landmark": None, "missing": list(missing),
            "is_change_request": change, "confidence": confidence}


def answer_with(address_answer, intent="address", confidence=0.95) -> dict:
    return {**full(intent, confidence=confidence), "address": address_answer}


def open_order(db, customer="91") -> tuple:
    with db.connect() as c:
        return c.execute(text(
            "SELECT o.status, o.address, o.phones, o.address_parts, o.address_partial FROM orders o JOIN customers c "
            "ON c.id = o.customer_id WHERE c.external_user_id = :e ORDER BY o.id DESC LIMIT 1"), {"e": customer}).one()


def cart_for(client, token, db, customer="91", phone=None) -> int:
    """A cart from the chat (Stronger With You Intensely 5ml) made before auto mode answers anything."""
    from tests.test_v411_ai_first import cart_with

    cid = cart_with(client, token, db, customer, "Stronger With You Intensely", "5")
    if phone:
        client.post(f"/chats/{cid}/cart/confirm", data={"csrf": token})
        client.post(f"/chats/{cid}/cart/phones", data={"csrf": token, "phone": phone})
    return cid


def test_p2_ai_address_without_phone_and_ask_words(auto_ai, shop, db):
    client, token = shop
    cart_for(client, token, db)
    auto_ai.answer = lambda _: answer_with(addr("ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅", "ဗဟန်း", "ရွှေဂုံတိုင်လမ်း", "အမှတ် ၅"))
    now_msg(db, LIVE_P2)
    sent = auto_ai.requests[-1]
    assert "ရွှေဂုံတိုင်လမ်း အမှတ် ၅" in sent[1] and "[ADDRESS]" not in sent[1]  # ai_address ON: as written
    assert "09777123456" not in sent[1] and "[PHONE]" in sent[1] and "## address" in sent[0]
    status, saved, phones, parts, _ = open_order(db)
    assert saved == "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅" and phones == ["09777123456"]
    assert parts["township"] == "ဗဟန်း (Bahan)" and parts["house_no"] == "အမှတ် ၅"
    assert status == "waiting_payment" and ungreet(deliver(db)[0]).endswith(PAYMENT_FOOTER)
    page = client.get(f"/chats/{customer_id(db, '91')}?tab=cart").text
    assert "<b>ဗဟန်း (Bahan)</b>" in page and "✅" in page


def test_p2_the_ai_text_is_checked_too(auto_ai, shop, db):
    """Even if the AI copies the phone and the ask words, the saved address has neither."""
    client, token = shop
    cart_for(client, token, db)
    auto_ai.answer = lambda _: answer_with(addr("ဒီကိုပို့ပေးပါ ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅ [PHONE]", "ဗဟန်း"))
    now_msg(db, LIVE_P2)
    assert open_order(db)[1] == "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅"


@pytest.mark.parametrize("with_ai", [True, False])
def test_p3_missing_township_asked_then_merged(request, shop, db, with_ai):
    client, token = shop
    if with_ai:
        fake = request.getfixturevalue("auto_ai")
        fake.answer = lambda body: answer_with(
            addr("ရန်ကင်း", "ရန်ကင်း", missing=["street", "house_no"]) if "ရန်ကင်း" in body.split("CUSTOMER MESSAGE")[-1]
            else addr("သုခလမ်း အမှတ် ၁၂", None, "သုခလမ်း", "အမှတ် ၁၂", missing=["township"]))
    else:
        auto_on(db)
    cart_for(client, token, db, phone="09777123456")
    now_msg(db, "သုခလမ်း အမှတ် ၁၂")
    assert ungreet(deliver(db)[0]) == ASK_TOWNSHIP
    status, saved, _, _, partial = open_order(db)
    assert saved is None and partial["full_text"] in ("သုခလမ်း အမှတ် ၁၂", "သုခလမ်း အမှတ် 12")
    if with_ai:
        assert "WE ASKED: the township of this address: သုခလမ်း" in (now_msg(db, "ရန်ကင်း") and fake.requests[-1][1])
    else:
        now_msg(db, "ရန်ကင်း")
    status, saved, _, parts, partial = open_order(db)
    assert saved.startswith("သုခလမ်း အမှတ်") and saved.endswith(", ရန်ကင်း") and partial is None
    assert parts["township"] == "ရန်ကင်း (Yankin)" and status == "waiting_payment"
    assert deliver(db)[0].endswith(PAYMENT_FOOTER)


def test_p3_resume_line_asks_only_the_township(shop, db):
    client, token = shop
    auto_on(db)
    cart_for(client, token, db, phone="09777123456")
    now_msg(db, "သုခလမ်း အမှတ် ၁၂")
    deliver(db)
    from app.orders import steps
    from app.replies import templates as replies

    with SessionLocal() as s:
        step = steps.step(s, customer_id(db, "91"))
        assert step.kind == "need_address" and steps.resume_text(s, step, replies.load(s)) == ASK_TOWNSHIP


def test_p5_unknown_township_goes_to_a_person(auto_ai, shop, db):
    client, token = shop
    cart_for(client, token, db, phone="09777123456")
    auto_ai.answer = lambda _: answer_with(addr("No 7 Shwe Taung Gyar Rd, Zigon", "Zigon", "Shwe Taung Gyar Rd", "No 7"))
    mid = now_msg(db, "No 7 Shwe Taung Gyar Rd, Zigon")
    assert deliver(db) == [] and open_order(db)[1] is None
    page = client.get("/").text
    assert f'id="address-{mid}"' in page and "Township not in our list." in page
    assert "<b>Zigon</b>" in page and "No 7 Shwe Taung Gyar Rd, Zigon</textarea>" in page
    r = client.post(f"/messages/{mid}/address", data={"csrf": token, "full_text": "Zigon", "back": "/"},
                    follow_redirects=False)
    assert r.status_code == 303 and open_order(db)[1] is None  # still not valid: nothing saved
    client.post(f"/messages/{mid}/address", data={"csrf": token, "full_text": "No 7 Shwe Taung Gyar Rd, Bahan",
                                                   "back": "/"})
    status, saved, _, parts, _ = open_order(db)
    assert saved == "No 7 Shwe Taung Gyar Rd, Bahan" and status == "waiting_payment"
    assert ungreet(deliver(db)[0]).endswith(PAYMENT_FOOTER)
    assert f'id="address-{mid}"' not in client.get("/").text


def test_p5_unsure_ai_and_ask_for_full_address(auto_ai, shop, db):
    client, token = shop
    cart_for(client, token, db, phone="09777123456")
    auto_ai.answer = lambda _: answer_with(addr("ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅", "ဗဟန်း", confidence=0.6))
    mid = now_msg(db, "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅ လားမသိဘူး")
    assert deliver(db) == []
    page = client.get("/").text
    assert f'id="address-{mid}"' in page and "The AI is not sure about this address." in page
    client.post(f"/messages/{mid}/address/ask", data={"csrf": token, "back": "/"})
    assert ungreet(deliver(db)[0]) == "အိမ်နံပါတ်၊ လမ်း၊ မြို့နယ် ပါတဲ့ လိပ်စာ အပြည့်အစုံ ပို့ပေးပါနော်။"
    assert f'id="address-{mid}"' not in client.get("/").text and open_order(db)[1] is None


def test_p6_ai_address_off_rules_still_work_and_nothing_address_like_leaves(ai, shop, db):
    client, token = shop
    from app.ai import settings as ai_settings

    mode("auto", ai_address=False)
    auto_on(db)
    cart_for(client, token, db)
    ai.answer = lambda _: full("other", confidence=0.3)
    now_msg(db, LIVE_P2)
    assert all("ရွှေဂုံတိုင်" not in body for _, body in ai.requests)  # not even asked: the rules are sure
    status, saved, phones, parts, _ = open_order(db)
    assert saved == "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် 5" and phones == ["09777123456"] and status == "waiting_payment"
    now_msg(db, "mystery 10ml ယူမယ် ပြီးတော့ ရန်ကင်း သုခလမ်း အမှတ်၁၂ ကိုပို့ပေးပါ", customer="92")
    instructions, body = ai.requests[-1]
    assert "သုခလမ်း" not in body and "[ADDRESS]" in body and "## address" not in instructions
    with SessionLocal() as s:
        assert ai_settings.load(s)["ai_address"] is False


# ---------- N2 / P1: approve and the confirmation are blocked too ----------

from tests.test_payments import downloaded, photo, waiting_for_payment  # noqa: E402


def test_p1_approve_and_confirmation_blocked_until_fixed(shop, db, tmp_path, monkeypatch, capsys):
    client, token = shop
    waiting_for_payment(client, token, db)
    with db.begin() as c:  # the live case: the 4.8 bug saved the change request as the address
        c.execute(text("UPDATE orders SET address = :a"), {"a": BAD})
    repair(monkeypatch, capsys)
    photo(1)
    check = scalar(db, "SELECT id FROM payment_checks")
    page = client.get(f"/payments/{check}").text
    assert "⚠️ invalid address" in page and "Approving is blocked until the address is valid." in page
    downloaded(db, tmp_path, monkeypatch, check)
    form = {"csrf": token, "transaction_id": "TX1", "amount": "18000"}
    r = client.post(f"/payments/{check}/approve", data=form)
    assert r.status_code == 400 and "The address is not valid: fix it on this card." in r.text
    r = client.post(f"/payments/{check}/approve", data={**form, "confirmed": "1"})  # no "approve anyway" either
    assert r.status_code == 400 and scalar(db, "SELECT order_no FROM orders") is None
    assert scalar(db, "SELECT count(*) FROM outbox WHERE reply_kind = 'payment'") == 0  # no confirmation
    r = client.post(f"/payments/{check}/address", data={"csrf": token, "address": "ပို့ပေးပါ"})
    assert r.status_code == 400 and flags(db)[0] is True
    client.post(f"/payments/{check}/address", data={"csrf": token, "address": "ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅"})
    assert flags(db) == (False, False)
    r = client.post(f"/payments/{check}/approve", data=form, follow_redirects=False)
    assert r.status_code == 303 and scalar(db, "SELECT order_no FROM orders") == 1001
    assert "လိပ်စာ: ဗဟန်း ရွှေဂုံတိုင်လမ်း အမှတ် ၅\n" in deliver(db)[-1]


def test_p1_no_payment_info_again_while_the_address_is_invalid(shop, db):
    """docs/SPEC-v4.10 resends payment info with a new total; not while the address is invalid."""
    client, token = shop
    waiting_for_payment(client, token, db)
    with db.begin() as c:
        c.execute(text("UPDATE orders SET address = :a, address_invalid = true"), {"a": BAD})
    mid = say(db, 5, "sauvage edp 10ml ထပ်ယူမယ်")
    from tests.test_cart import button

    b = button(client, mid)
    assert b is None or "payment info" not in b[0]
    assert scalar(db, "SELECT count(*) FROM outbox WHERE reply_kind = 'payment_info' AND status = 'queued'") == 0


# ---------- N3: the payment-screenshot reader (fake provider) ----------

from app.ai import providers, screens  # noqa: E402
from app.ai.providers import FakeProvider  # noqa: E402
from app.ai import settings as ai_settings  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402


def reading(**over) -> dict:
    base = {"is_payment_receipt": True, "app": "KBZPay", "amount": 18000, "currency": "Ks",
            "transaction_no": "01003456789012345678", "time": "17/10/2026 23:21:05",
            "time_iso": datetime.now(ZoneInfo(get_settings().timezone)).strftime("%Y-%m-%dT%H:%M"),
            "receiver_name": "Test Shop",
            "receiver_account_last4": "0001", "status_text": "Payment Successful", "confidence": 0.97}
    return {**base, **over}


@pytest.fixture
def reader(shop, db, tmp_path, monkeypatch):
    """Payment info sent (18,000 ကျပ်, KPay Test Shop 09000000001), one screenshot opened + downloaded,
    a fake AI provider; returns (client, token, fake, check id)."""
    client, token = shop
    fake = FakeProvider()
    providers.use(fake)
    monkeypatch.setattr(screens, "MEDIA_DIR", tmp_path)
    waiting_for_payment(client, token, db)
    photo(1)
    check = scalar(db, "SELECT id FROM payment_checks")
    client.get(f"/payments/{check}")  # the admin opens the card: only now the photo is downloaded
    downloaded(db, tmp_path, monkeypatch, check, content=b"\x89PNG fake receipt")
    yield client, token, fake, check
    providers.use(None)


def switch_screens(on: bool) -> None:
    with SessionLocal.begin() as s:
        ai_settings.save(s, {"ai_screenshot": on}, None)


def test_p7_paid_more_to_another_receiver_needs_second_confirm(reader, db):
    client, token, fake, check = reader
    switch_screens(True)
    fake.image_answer = reading(amount=70000, receiver_name="Soe Htike Lwin", receiver_account_last4="7788")
    assert screens.run_once() == {"done": 1}
    [(sent_text, image)] = fake.images
    assert image == b"\x89PNG fake receipt" and "EXPECTED TOTAL: 18000 Ks" in sent_text
    assert "Test Shop (…0001)" in sent_text and "09000000001" not in sent_text  # last 4 digits only
    assert screens.run_once() == {} and len(fake.images) == 1  # once per check
    assert scalar(db, "SELECT status FROM orders") == "photo_received"  # never approved by itself
    assert scalar(db, "SELECT count(*) FROM outbox WHERE status = 'queued'") == 0  # nothing to the customer
    page = client.get(f"/payments/{check}").text
    assert "70,000 ≠ order total 18,000 ကျပ်: paid more (52,000 ကျပ် too much)." in page
    assert "Paid to Soe Htike Lwin (…7788): not one of our payment accounts." in page
    assert 'name="transaction_id" value="01003456789012345678"' in page and "from the screenshot" in page
    assert 'name="amount" value="70000"' in page
    assert "⚠️ 2 warnings from the screenshot" in client.get("/").text
    form = {"csrf": token, "transaction_id": "01003456789012345678", "amount": "18000", "method": "KPay"}
    r = client.post(f"/payments/{check}/approve", data=form)
    assert "Approve anyway" in r.text and "paid more" in r.text and scalar(db, "SELECT order_no FROM orders") is None
    r = client.post(f"/payments/{check}/approve", data={**form, "confirmed": "1"}, follow_redirects=False)
    assert r.status_code == 303 and scalar(db, "SELECT order_no FROM orders") == 1001


def test_p7_matching_receipt_has_no_warnings(reader, db):
    client, token, fake, check = reader
    switch_screens(True)
    fake.image_answer = reading()
    screens.run_once()
    page = client.get(f"/payments/{check}").text
    assert "Amount, receiver and time match." in page
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "01003456789012345678",
                                                         "amount": "18000"}, follow_redirects=False)
    assert r.status_code == 303  # no second confirm needed


@pytest.mark.parametrize("over, expected", [
    ({"transaction_no": "TX-DUP"}, "Transaction no. TX-DUP from the screenshot was already used for order #1001."),
    ({"time_iso": "2026-10-09T07:30"}, "is before we sent the payment info"),
    ({"is_payment_receipt": False, "amount": None, "transaction_no": None, "receiver_name": None,
      "receiver_account_last4": None, "status_text": None, "app": None},
     "The screenshot does not look like a payment receipt (or it is unreadable)."),
    ({"status_text": "Transaction Failed"}, "Status on the screenshot: “Transaction Failed” (not successful)."),
    ({"amount": 15000}, "paid less (3,000 ကျပ် missing)."),
])
def test_p8_more_warnings(reader, db, over, expected):
    client, token, fake, check = reader
    switch_screens(True)
    if over.get("transaction_no") == "TX-DUP":  # an earlier approved payment used the same transaction no.
        from tests.test_messaging import add

        add(900, "", customer="77", kind="photo", when=datetime.now(UTC) - timedelta(days=1))
        with db.begin() as c:
            c.execute(text("INSERT INTO orders (customer_id, status, order_no, paid_at) SELECT customer_id, 'paid', "
                           "1001, now() FROM messages WHERE external_message_id = '900'"))
            c.execute(text("INSERT INTO payment_checks (order_id, message_id, decision, transaction_id) SELECT "
                           "o.id, m.id, 'approved', 'TX-DUP' FROM orders o, messages m WHERE o.order_no = 1001 AND "
                           "m.external_message_id = '900'"))
    fake.image_answer = reading(**over)
    screens.run_once()
    page = client.get(f"/payments/{check}").text
    assert expected in page
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX-NEW", "amount": "18000"})
    assert "Approve anyway" in r.text  # every warning needs the second confirm


def test_p8_errors_never_block(reader, db):
    client, token, fake, check = reader
    switch_screens(True)
    fake.image_answer = providers.AIError("timeout")
    assert screens.run_once() == {"error": 1}
    assert "Could not read the screenshot; check it yourself." in client.get(f"/payments/{check}").text
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "18000"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_p9_switch_off_no_image_ever_sent(reader, db):
    client, token, fake, check = reader
    with SessionLocal() as s:
        assert ai_settings.load(s)["ai_screenshot"] is False  # the default
    fake.image_answer = reading(amount=70000)
    assert screens.run_once() == {} and fake.images == []
    page = client.get(f"/payments/{check}").text
    assert "From the screenshot" not in page and "Reading the screenshot" not in page
    assert 'name="transaction_id" value=""' in page  # the card works as before
    r = client.post(f"/payments/{check}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "18000"},
                    follow_redirects=False)
    assert r.status_code == 303 and fake.images == []

