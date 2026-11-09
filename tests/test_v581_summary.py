"""docs/SPEC-v5.8.1-hotfix-final-summary.md: payment info is ONE message with the items, total, the order's phone(s)
and address, the payment accounts and "if everything is correct, send the screenshot" — also after every change of
phone / address, before and after payment info was sent. No "updated" line. Locked orders are unchanged."""
from sqlalchemy import text

from tests.test_cart import FOOTER, PAYMENT_FOOTER, button, deliver, order_row, shop, summary, tap  # noqa: F401
from tests.test_messaging import scalar
from tests.test_payments import waiting_for_payment
from tests.test_v48_change_info import OLD, STW_10, intent, reply, returning  # noqa: F401  (fixture)
from tests.test_web import client, log_in  # noqa: F401  (fixture)

LIVE = STW_10 + summary("09222222222", OLD) + PAYMENT_FOOTER  # the 2026-11-10 00:32 case after the fix


def test_1_returning_customer_says_yes(returning, db):  # noqa: F811
    client, token, _ = returning
    tap(client, token, reply(db, "ဟုတ်ကဲ့"))
    [sent] = deliver(db)
    assert sent == STW_10 + summary("09111222333", OLD) + PAYMENT_FOOTER
    assert sent.endswith(FOOTER) and "ပြင်ပြီးပါပြီ" not in sent


def test_2_live_case_phone_change_in_one_message(returning, db):  # noqa: F811
    client, token, _ = returning
    mid = reply(db, "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222")
    tap(client, token, mid)
    assert deliver(db) == [LIVE]  # new phone, old address, accounts, the confirm sentence — one message
    assert order_row(db, "92")[:4] == ("waiting_payment", 33000, OLD, ["09222222222"])


def test_3_address_change_and_both_in_one_message(returning, db):  # noqa: F811
    client, token, _ = returning
    tap(client, token, reply(db, "လိပ်စာ ပြောင်းချင်ပါတယ် 12 Bahan"))
    [sent] = deliver(db)
    assert sent == STW_10 + summary("09111222333", "12 Bahan") + PAYMENT_FOOTER
    # both at once, while waiting for the payment: the whole message again with both new values
    tap(client, token, reply(db, "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222 လိပ်စာ ပြောင်းချင်ပါတယ် 34 Sanchaung"))
    [again] = deliver(db)
    assert again.startswith(STW_10 + "ဖုန်း: 09222222222") and "လိပ်စာ: 34 Sanchaung" in again
    assert again.endswith(PAYMENT_FOOTER) and "ပြင်ပြီးပါပြီ" not in again


def test_4_change_after_payment_info_resends_once(shop, db):  # noqa: F811
    client, token = shop
    waiting_for_payment(client, token, db)  # phones 09777123456, 09444555666 · "No. 12, Bahan"
    sent_at = scalar(db, "SELECT payment_info_sent_at FROM orders")
    tap(client, token, reply(db, "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222", customer="91"))
    [sent] = deliver(db)
    assert sent.startswith("• Stronger With You Intensely 5ml – 18,000 ကျပ်\nစုစုပေါင်း 18,000 ကျပ်ပါ။\nဖုန်း: 09222222222")
    assert "လိပ်စာ: No. 12, Bahan" in sent and sent.endswith(PAYMENT_FOOTER)
    assert scalar(db, "SELECT payment_info_sent_at FROM orders") == sent_at  # the timers keep counting
    # the same message again changes nothing: nothing is sent twice
    again = reply(db, "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222", customer="91")
    label = button(client, again)
    assert label is None or "payment info" not in label[0]  # no second payment info for the same change
    assert all("KPay" not in s for s in deliver(db))


def test_5_rules_and_ai_parse_give_the_same_text(shop, db):  # noqa: F811
    """The reply is built from the order, not by whoever read the message (rules or AI): same builder, same text."""
    client, token = shop
    texts = []
    for customer, method in (("93", "rules"), ("94", "ai")):
        waiting_for_payment(client, token, db, customer=customer)
        mid = reply(db, "ဖုန်းနံပါတ်ချိန်းချင်ပါတယ် 09222222222", customer=customer)
        assert intent(db, mid) == "change_info"
        if method == "ai":
            with db.begin() as c:
                c.execute(text("UPDATE parse_results SET method = 'ai', parser_version = 'ai-test' WHERE message_id = :m"),
                          {"m": mid})
        tap(client, token, mid)
        texts.append(deliver(db)[-1])
    assert texts[0] == texts[1] and "ဖုန်း: 09222222222" in texts[0]


def test_6_missing_address_still_asks_first(shop, db):  # noqa: F811
    client, token = shop
    from tests.test_cart import say
    tap(client, token, say(db, 1, "stw intensely 5ml ယူမယ်", customer="95"))
    deliver(db)
    tap(client, token, say(db, 2, "ok", customer="95"))
    deliver(db)
    tap(client, token, say(db, 3, "09 777 123 456", customer="95"))
    [asked] = deliver(db)
    assert "လိပ်စာ" in asked and "KPay" not in asked  # no payment info without an address


def test_7_templates_listed_editable_and_custom_footer_kept(client, db):  # noqa: F811
    token = log_in(client)
    page = client.get("/settings?section=auto-reply").text
    for key in ("payment_summary_phone", "payment_summary_address", "payment_info_footer"):
        assert f'action="/settings/templates/{key}"' in page
    assert "အချက်အလက်အားလုံး မှန်ရင် ငွေလွှဲပြီး transaction id ပါတဲ့ screenshot လေး ပို့ပေးပါနော်။" in page
    from app.core.db import SessionLocal
    from app.replies import templates as replies
    with db.begin() as c:  # an owner's own footer text (edited before this release) is kept
        c.execute(text("INSERT INTO reply_templates (key, text) VALUES ('payment_info_footer', 'my own footer')"))
    with SessionLocal() as s:
        texts = replies.load(s)
    assert texts["payment_info_footer"] == "my own footer" and texts["payment_summary_phone"] == "ဖုန်း: {phones}"
    assert token
