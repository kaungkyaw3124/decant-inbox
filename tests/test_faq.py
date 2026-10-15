"""docs/SPEC-v3.md Step 7 acceptance tests B1-B6: FAQ auto-answers (auto ON) / one-tap
"💬 Send FAQ" (auto OFF), inactive entries, the normal price flow wins, Settings edits,
unknown questions go to Needs you."""
from datetime import timedelta

from sqlalchemy import text

from tests.test_after_payment import auto_off, auto_on, needs, run_auto, say
from tests.test_cart import button, deliver, shop, tap  # noqa: F401  (fixture)
from tests.test_messaging import customer_id, scalar
from tests.test_web import client, log_in  # noqa: F401  (fixture)

AUTHENTIC = "အားလုံး authentic (original) ပစ္စည်းတွေ ကနေ ခွဲထည့်ပေးတာပါနော်။"
DELI_TIME = "ရန်ကုန်မြို့တွင်း ၁-၂ ရက်၊ နယ်ကို ၃-၅ ရက်လောက် ကြာပါတယ်နော်။"
GREETING = "မင်္ဂလာပါ။\n"


def faq_id(db, title: str) -> int:
    return scalar(db, "SELECT id FROM faq_entries WHERE title = :t", t=title)


def test_b1_authentic_auto_on(shop, db):
    client, _ = shop
    auto_on(db)
    say(1, "authentic လား", "91")
    run_auto()
    assert deliver(db) == [GREETING + AUTHENTIC]
    with db.connect() as c:
        assert c.execute(text("SELECT kind, auto FROM quick_actions")).one() == ("faq", True)
    page = client.get(f"/chats/{customer_id(db, '91')}").text
    assert 'title="Sent by auto-reply">🤖' in page
    assert "FAQ answer" in client.get("/").text  # in the 🤖 handled feed


def test_b1_authentic_auto_off_one_tap(shop, db):
    client, token = shop
    auto_off()
    mid = say(1, "authentic လား", "91")
    run_auto()
    assert deliver(db) == []
    label, tooltip, _ = button(client, mid)
    assert label == "💬 Send FAQ: Authentic" and AUTHENTIC in tooltip
    # also offered in Needs you once it waited 2 minutes (the inbox hides "other" by default)
    with db.begin() as c:
        c.execute(text("UPDATE messages SET received_at = received_at - interval '3 minutes' WHERE id = :m"), {"m": mid})
    (row,) = needs(db)["unanswered"]
    assert row.faq[0] == mid and row.faq[1].entry.title == "Authentic"
    assert "💬 Send FAQ: Authentic" in client.get("/").text
    tap(client, token, mid)
    assert deliver(db) == [GREETING + AUTHENTIC]
    assert 'title="Sent by auto-reply">🤖' in client.get(f"/chats/{customer_id(db, '91')}").text  # every FAQ send


def test_b2_delivery_time_and_kpay(shop, db):
    auto_on(db)
    say(1, "ဘယ်နှစ်ရက်ကြာလဲ", "91")
    run_auto()
    assert deliver(db) == [GREETING + DELI_TIME]
    say(2, "kpay ရလား", "92")  # "kpay" is a keyword here, not an unknown product
    run_auto()
    assert deliver(db) == [GREETING + "KPay / AYA Pay နဲ့ ကြိုလွှဲပေးရပါတယ်။ ပို့ခကိုတော့ ပစ္စည်းရောက်မှ ပေးရပါတယ်နော်။"]
    assert needs(db)["unknown"] == []


def test_most_keywords_wins(shop, db):
    auto_on(db)
    with db.begin() as c:
        c.execute(text("UPDATE faq_entries SET keywords = 'original, tester, အစစ်' WHERE title = 'Location'"))
    say(1, "tester original လား", "91")  # Authentic: 2 hits, Location (edited): 2 hits -> first in the list
    say(2, "tester အစစ် original လား", "92")  # Location: 3 hits, Authentic: 2
    run_auto()
    assert sorted(deliver(db)) == sorted([GREETING + AUTHENTIC, GREETING + "Online ကနေ ပို့ပေးတာပါနော်။"])


def test_b3_inactive_entry_not_used(shop, db):
    client, token = shop
    auto_on(db)
    entry = faq_id(db, "Authentic")
    with db.connect() as c:
        row = c.execute(text("SELECT title, keywords, answer FROM faq_entries WHERE id = :i"), {"i": entry}).one()
    client.post(f"/settings/faq/{entry}", data={"csrf": token, "title": row[0], "keywords": row[1],
                                                "answer": row[2], "active": ""})
    assert scalar(db, "SELECT active FROM faq_entries WHERE id = :i", i=entry) is False
    say(1, "authentic လား", "91", ago=timedelta(minutes=3))
    run_auto()
    assert deliver(db) == []
    assert [r.customer.external_user_id for r in needs(db)["unanswered"]] == ["91"]


def test_b4_product_named_price_wins(shop, db):
    client, token = shop
    auto_on(db)
    say(1, "stw intensely 5ml ဘယ်လောက်လဲ", "91")
    run_auto()
    assert deliver(db) == [GREETING + "Stronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"]
    # a product AND an FAQ question: the price reply goes out, the FAQ part is a hint in Needs you
    mid = say(2, "sauvage edp 10ml ဘယ်လောက်လဲ original လား", "92")
    run_auto()
    assert deliver(db) == [GREETING + "Sauvage Eau de Parfum 10ml က 38,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"]
    hints = needs(db)["faq_hints"]
    assert [(m.id, match.entry.title) for m, _, match in hints] == [(mid, "Authentic")]
    page = client.get("/").text
    assert "also asks: FAQ “Authentic”" in page
    entry = faq_id(db, "Authentic")
    client.post(f"/messages/{mid}/faq/{entry}", data={"csrf": token})
    assert deliver(db) == [AUTHENTIC] and needs(db)["faq_hints"] == []


def test_b5_settings_edit_changes_matching_now(shop, db):
    client, token = shop
    auto_on(db)
    page = client.get("/settings").text
    assert "💬 FAQ answers" in page and "edit me" in page
    entry = faq_id(db, "Location")
    client.post(f"/settings/faq/{entry}", data={"csrf": token, "title": "Location", "keywords": "ဆိုင်ဖွင့်, pick up",
                                                "answer": "Online shop ပါ။ လာယူလို့မရပါဘူးနော်။", "active": "1"})
    assert scalar(db, "SELECT edited FROM faq_entries WHERE id = :i", i=entry) is True
    say(1, "pick up လုပ်လို့ရလား", "91")
    say(2, "location ဘယ်မှာလဲ", "92", ago=timedelta(minutes=3))  # old keywords no longer match
    run_auto()
    assert deliver(db) == [GREETING + "Online shop ပါ။ လာယူလို့မရပါဘူးနော်။"]
    # a new entry from Settings works at once too
    r = client.post("/settings/faq", data={"csrf": token, "title": "", "keywords": "x", "answer": "y"})
    assert r.status_code == 400 and "Title" in r.text
    client.post("/settings/faq", data={"csrf": token, "title": "Gift", "keywords": "gift box, လက်ဆောင်",
                                       "answer": "Gift box ထည့်ပေးလို့ရပါတယ်နော်။"})
    say(3, "လက်ဆောင်ပေးမလို့", "93")
    run_auto()
    assert deliver(db) == [GREETING + "Gift box ထည့်ပေးလို့ရပါတယ်နော်။"]


def test_b6_unknown_question_needs_you(shop, db):
    client, _ = shop
    auto_on(db)
    mid = say(1, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", "91", ago=timedelta(minutes=3))
    run_auto()
    assert deliver(db) == []
    assert scalar(db, "SELECT reason FROM auto_runs WHERE message_id = :m", m=mid) == "intent other"
    assert [r.message_ids for r in needs(db)["unanswered"]] == [[mid]]
    assert "ဒီအနံ့က ဘယ်လိုမျိုးလဲ" in client.get("/").text


def test_faq_keywords_match_latin_words_only():
    from app.replies.faq import _found, split_keywords

    assert split_keywords("cod, Delivery  Time ၊ ဆိုင်, cod") == ["cod", "delivery time", "ဆိုင်"]
    assert _found("cod", "cod ရလား") and not _found("cod", "code ပါလား")
    assert _found("ဆိုင်", "ဆိုင်ဘယ်မှာလဲ")
