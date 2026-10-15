"""docs/SPEC-v4.md 4.1 acceptance tests A1-A4: a known nickname inside a longer unknown name
("hawas for him" with alias "hawas") never produces a wrong product: one partial item, the
nickname's product only as a suggestion, nothing sent, the message waits in Needs you."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.db import SessionLocal
from app.orders import auto
from app.web import auto as auto_pages
from tests.test_auto import switch_on
from tests.test_cart import button, deliver, items, say, shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_prices import run_import, xlsx
from tests.test_web import client, log_in  # noqa: F401  (fixture)

HAWAS_ICE = ["Rasasi", "Hawas Ice", 100, 250000, 6000, 14000, 26000, "yes"]
GOOD_GIRL = ["Carolina Herrera", "Good Girl", 80, 320000, 8000, 21000, 39000, "yes"]


def hawas_shop(db) -> None:
    run_import(xlsx(HAWAS_ICE, GOOD_GIRL), {2: "new", 3: "new"})
    with db.begin() as c:
        c.execute(text("INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
                       "SELECT id, 'hawas', 'hawas', 'learned' FROM products WHERE name = 'Hawas Ice'"))


def auto_on(db) -> None:
    switch_on(db, since=datetime.now(UTC) - timedelta(hours=3))  # say() dates messages up to ~1 h back


def parse_items(db, mid: int) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT p.name, i.size_ml, i.unknown_text, i.match, cp.name FROM parse_items i "
            "JOIN parse_results r ON r.id = i.parse_result_id AND r.is_current "
            "LEFT JOIN products p ON p.id = i.product_id LEFT JOIN products cp ON cp.id = i.candidate_product_id "
            "WHERE r.message_id = :m ORDER BY i.position"), {"m": mid}))


def outbox_count(db) -> int:
    return scalar(db, "SELECT count(*) FROM outbox WHERE status != 'cancelled'")


def unknown_ids() -> list[int]:
    """Messages waiting in Needs you for their unknown items (with a teaching card since 4.2)."""
    with SessionLocal() as s:
        needs = auto_pages.needs_you(s)
        return [m.id for m, _, _ in needs["unknown"]] + [m.id for m, _, _ in needs["teach"]]


def test_a1_partial_name_is_not_a_match(shop, db):
    client, _ = shop
    hawas_shop(db)
    auto_on(db)
    mid = say(db, 1, "hawas for him 10ml ယူမယ်")
    assert parse_items(db, mid) == [(None, 10, "hawas for him", "partial", "Hawas Ice")]
    assert auto.run_once() == {} and outbox_count(db) == 0  # not certain: no auto reply
    assert button(client, mid) is None  # and no one-tap reply either
    assert mid in unknown_ids()  # it waits in Needs you
    page = client.get(f"/messages/{mid}").text  # 4.2 teaching card: the candidate is the first answer
    assert "“hawas for him” ဆိုတာ ဘယ်ပစ္စည်းလဲ?" in page and "“Hawas Ice” ရဲ့ nickname ပါပေမယ့်" in page
    first = page.index('name="p0"')
    assert page.index("Hawas Ice", first) < page.index("Good Girl", first) and 'value="' in page[first:first + 80]
    hawas = scalar(db, "SELECT id FROM products WHERE name = 'Hawas Ice'")
    assert f'name="p0" value="{hawas}" checked' in page


def test_a2_exact_names_unchanged(shop, db):
    client, _ = shop
    hawas_shop(db)  # aliases "hawas ice" (the name, from the price list) and "hawas"
    for n, body in ((1, "hawas ice 10ml ယူမယ်"), (2, "hawas 10ml ယူမယ်"), (3, "pls hawas 10ml ယူမယ်")):
        mid = say(db, n, body, customer=str(90 + n))
        assert parse_items(db, mid) == [("Hawas Ice", 10, None, "exact", None)], body
        assert button(client, mid)[0] == "🛒 Add to cart + send list"


def test_a3_known_plus_partial_waits_whole_message(shop, db):
    client, token = shop
    hawas_shop(db)
    auto_on(db)
    mid = say(db, 1, "good girl 5ml, hawas for him 10ml ယူမယ်")
    assert parse_items(db, mid) == [("Good Girl", 5, None, "exact", None),
                                    (None, 10, "hawas for him", "partial", "Hawas Ice")]
    assert auto.run_once() == {} and outbox_count(db) == 0  # the whole message waits
    assert button(client, mid) is None and mid in unknown_ids()
    assert scalar(db, "SELECT count(*) FROM orders") == 0
    # the admin says it is Hawas Ice after all -> one reply with both, never "hawas him" too
    hawas = scalar(db, "SELECT id FROM products WHERE name = 'Hawas Ice'")
    client.post(f"/messages/{mid}/unknown/1/map", data={"csrf": token, "product_id": hawas})
    auto.run_once()
    sent = deliver(db)
    assert len(sent) == 1 and "Good Girl 5ml" in sent[0] and "Hawas Ice 10ml" in sent[0]
    assert "hawas for him" not in sent[0] and "hawas him" not in sent[0]
    assert [i[0] for i in items(db)] == ["Good Girl", "Hawas Ice"]


def test_a3b_not_stocked_partial(shop, db):
    client, token = shop
    hawas_shop(db)
    mid = say(db, 1, "good girl 5ml, hawas for him 10ml ယူမယ်")
    client.post(f"/messages/{mid}/unknown/1/not-stocked", data={"csrf": token})
    label, tooltip, _ = button(client, mid)
    assert "Good Girl 5ml" in tooltip and "Hawas Ice" not in tooltip and "hawas for him" in tooltip
