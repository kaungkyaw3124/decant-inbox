"""docs/SPEC-v4.md 4.3 acceptance tests C1-C6: "ဟိုနေ့ကဟာ ထပ်ယူမယ်" works without guessing.
One earlier item -> added + "(အရင်ယူထားတဲ့ဟာ)" line; several -> numbered list, the answer
"2" / "၁" / "1 နဲ့ 2" adds them (24 h); none -> Needs you."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.orders import auto
from app.parser.worker import run_batch
from tests.test_after_payment import paid_order
from tests.test_auto import switch_on
from tests.test_cart import button, deliver, items, shop, tap  # noqa: F401  (fixture)
from tests.test_messaging import add, scalar
from tests.test_v4_teaching import card_page, teach
from tests.test_web import client, log_in  # noqa: F401  (fixture)

LINE = "Stronger With You Intensely 5ml (အရင်ယူထားတဲ့ဟာ) ဟုတ်တယ်နော်။ မဟုတ်ရင် ပြောပေးပါ။"
RETURNING = "ဖုန်း 09777123456, 09444555666၊ လိပ်စာ No. 12, Bahan ကိုပဲ ပို့ပေးရမလား။"
_n = iter(range(7000, 8000))


def msg(db, body: str, customer: str = "91", ago: timedelta = timedelta(0)) -> int:
    n = next(_n)
    add(n, body, customer=customer, when=datetime.now(UTC) - ago)
    run_batch()
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(n))


def intent(db, mid: int) -> str:
    return scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid)


def run_auto() -> dict:
    return auto.run_once(datetime.now(UTC) + timedelta(seconds=5))  # the customer has been quiet


def history(db, customer: str) -> None:
    """Asked for two products earlier today (no reply)."""
    msg(db, "stw intensely 5ml ဘယ်လောက်လဲ", customer, ago=timedelta(minutes=30))
    msg(db, "sauvage edp 10ml ဘယ်လောက်လဲ", customer, ago=timedelta(minutes=20))


def test_c1_one_paid_item_added_automatically(shop, db, tmp_path, monkeypatch):
    client, token = shop
    paid_order(client, token, db, tmp_path, monkeypatch, "91", 1)  # Stronger With You Intensely 5ml, paid
    switch_on(db, since=datetime.now(UTC) - timedelta(minutes=1))
    mid = msg(db, "ဟိုနေ့ကဟာ ထပ်ယူမယ်")
    assert intent(db, mid) == "previous_item"
    assert run_auto()["replied"] == 1  # (the payment photo is "skipped")
    # docs/SPEC-v4.10-interruptions.md: Order #1001 is paid and locked: this is a NEW order
    assert deliver(db) == ["Order #1001 ကတော့ အတည်ပြုပြီးသားပါ။ ဒါကို order အသစ်အနေနဲ့ ယူပေးပါမယ်နော်။\n• Stronger With You Intensely 5ml – 18,000 ကျပ်\nစုစုပေါင်း 18,000 ကျပ်ပါ။\n"
                           f"{LINE}\n{RETURNING}"]
    assert items(db)[-1] == ("Stronger With You Intensely", 5, False, 1, 18000)


def test_c2_two_items_numbered_choice(shop, db):
    client, token = shop
    for customer, answer, picked in (("91", "2", "Stronger With You Intensely"),
                                     ("92", "၁", "Sauvage Eau de Parfum")):
        history(db, customer)
        mid = msg(db, "အရင်ကဟာ ယူမယ်", customer, ago=timedelta(minutes=5))
        label, _, _ = button(client, mid)
        assert label == "🔢 Ask which earlier item"
        tap(client, token, mid)
        assert deliver(db) == ["မင်္ဂလာပါ။\nအရင်က ယူထားတာတွေပါ –\n1. Sauvage Eau de Parfum 10ml\n"
                               "2. Stronger With You Intensely 5ml\nဘယ်ဟာလဲ နံပါတ်လေး ပြောပေးပါနော်။"]
        choice = msg(db, answer, customer)
        assert intent(db, choice) == "buy"
        tap(client, token, choice)
        sent = deliver(db)
        assert len(sent) == 1 and sent[0].startswith(f"• {picked}")
    assert [i[0] for i in items(db)] == ["Stronger With You Intensely", "Sauvage Eau de Parfum"]


def test_c3_pick_both(shop, db):
    client, token = shop
    switch_on(db, since=datetime.now(UTC) - timedelta(hours=1))
    history(db, "91")
    with db.begin() as c:  # the asks were answered by hand: auto mode leaves them alone
        c.execute(text("INSERT INTO auto_runs (message_id, status, reason) SELECT id, 'skipped', 'test' FROM messages"))
    msg(db, "same as before", ago=timedelta(seconds=30))
    assert run_auto() == {"replied": 1}
    assert "1. Sauvage Eau de Parfum 10ml" in deliver(db)[0]
    msg(db, "1 နဲ့ 2")
    assert run_auto() == {"replied": 1}  # picked by number from our own list: certain
    sent = deliver(db)
    assert "• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်" in sent[0] and "• Stronger With You Intensely 5ml" in sent[0]
    assert sorted(i[0] for i in items(db)) == ["Sauvage Eau de Parfum", "Stronger With You Intensely"]


def test_c4_expired_prompt(shop, db):
    client, token = shop
    history(db, "91")
    tap(client, token, msg(db, "အရင်ကဟာ ယူမယ်", ago=timedelta(minutes=5)))
    deliver(db)
    with db.begin() as c:  # the list was sent 25 h ago
        c.execute(text("UPDATE choice_prompts SET created_at = now() - interval '25 hours', "
                       "expires_at = now() - interval '1 hour'"))
    late = msg(db, "1")
    assert intent(db, late) == "other" and button(client, late) is None
    assert items(db) == []


def test_c5_no_history_needs_you(shop, db):
    client, token = shop
    switch_on(db, since=datetime.now(UTC) - timedelta(minutes=1))
    mid = msg(db, "ဟိုနေ့ကဟာ ထပ်ယူမယ်")
    assert "replied" not in run_auto() and deliver(db) == [] and button(client, mid) is None
    assert "📘 သင်ပေးမယ်" in client.get("/").text
    page = card_page(client, mid)
    assert "ဆိုတာ ဘယ်ပစ္စည်းလဲ?" in page and "ဘယ် size လဲ?" in page
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    teach(client, token, mid, p0=str(stw), size0="5", learn=None)
    assert deliver(db)[0].startswith("မင်္ဂလာပါ။\n• Stronger With You Intensely 5ml – 18,000 ကျပ်")


def test_c6_quantity(shop, db, tmp_path, monkeypatch):
    client, token = shop
    paid_order(client, token, db, tmp_path, monkeypatch, "91", 1)
    mid = msg(db, "ဟိုနေ့ကဟာ ၂ ခု ထပ်ယူမယ်")
    tap(client, token, mid)
    assert deliver(db)[0].startswith("Order #1001 ကတော့ အတည်ပြုပြီးသားပါ။ ဒါကို order အသစ်အနေနဲ့ ယူပေးပါမယ်နော်။\n• Stronger With You Intensely 5ml × 2 – 36,000 ကျပ်\nစုစုပေါင်း 36,000 ကျပ်ပါ။")  # 4.10
    assert items(db)[-1] == ("Stronger With You Intensely", 5, False, 2, 18000)


def test_undo_removes_the_prompt(shop, db):
    client, token = shop
    history(db, "91")
    mid = msg(db, "အရင်ကဟာ ယူမယ်", ago=timedelta(minutes=5))
    tap(client, token, mid)
    aid = scalar(db, "SELECT id FROM quick_actions WHERE message_id = :m", m=mid)
    client.post(f"/quick/{aid}/undo", data={"csrf": token})
    assert scalar(db, "SELECT count(*) FROM choice_prompts") == 0 and deliver(db) == []
    assert intent(db, msg(db, "1")) == "other"  # no list was sent: "1" is just "1"


def test_parse_choice():
    from app.parser.normalize import normalize
    from app.parser.rules import parse_choice

    cases = {"1": [1], "၁": [1], "1 နဲ့ 2": [1, 2], "1,2": [1, 2], "2 ခုလုံး": [1, 2], "အကုန်": [1, 2],
             "1 ယူမယ်": [1], "2 ကိုယူပါမယ်": [2], "3": None, "2 ခုလုံး ": [1, 2], "hi 1": None, "": None,
             "stw 5ml": None}
    for raw, expected in cases.items():
        assert parse_choice(normalize(raw), 2) == expected, raw
    assert parse_choice("2ခုလုံး", 3) is None  # "both" but there are three
