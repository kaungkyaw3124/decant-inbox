"""rules-2 against the test database: stored items, 24 h context, phone on the customer,
reparse stability, human edits as one item, multi-item quick reply."""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.parser.worker import run_batch
from scripts.reparse_all import reparse_all
from tests.test_messaging import add, scalar
from tests.test_prices import STW, run_import, xlsx
from tests.test_web import client, log_in  # noqa: F401  (fixture)

T0 = datetime.now(UTC) - timedelta(hours=3)


def items(db, external: str) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT p.name, i.size_ml, i.is_full_bottle, i.quantity, i.unknown_text, i.from_context "
            "FROM parse_items i JOIN parse_results r ON r.id = i.parse_result_id AND r.is_current "
            "JOIN messages m ON m.id = r.message_id LEFT JOIN products p ON p.id = i.product_id "
            "WHERE m.external_message_id = :e ORDER BY i.position"), {"e": external}))


def test_items_context_and_phone(client, db):  # noqa: F811  (client seeds the small catalog)
    with db.begin() as c:
        c.execute(text("UPDATE products SET full_size_ml = 100 WHERE name = 'Sauvage Eau de Parfum'"))
    add(201, "stw intensely 5ml, dior sauvage 100ml ယူမယ်", customer="61", when=T0)
    add(202, "10ml ရော ရှိလား", customer="61", when=T0 + timedelta(hours=1))  # context: last product
    add(203, "10ml ရှိလား", customer="62", when=T0)  # no earlier message: no context
    add(204, "ဗဟန်း ကိုပို့ပေးပါ 09 111 222 333", customer="61", when=T0 + timedelta(hours=2))
    add(205, "phone ၀၉ ၄၄၄ ၅၅၅ ၆၆၆", customer="61", when=T0 - timedelta(days=2))  # older number
    run_batch()
    assert items(db, "201") == [("Stronger With You Intensely", 5, False, 1, None, False),
                                ("Sauvage Eau de Parfum", None, True, 1, None, False)]
    # "last mentioned product" = first item of the latest message with a product
    assert items(db, "202") == [("Stronger With You Intensely", 10, False, 1, None, True)]
    assert items(db, "203") == [(None, 10, False, 1, None, False)]
    with db.connect() as c:
        assert c.execute(text("SELECT intent, phone FROM parse_results r JOIN messages m ON m.id = r.message_id "
                              "WHERE m.external_message_id = '204' AND r.is_current")).one() == ("address", "09111222333")
        # Step 4b: the parser only finds numbers; an admin tap saves them on the customer
        assert c.execute(text("SELECT phone FROM customers WHERE external_user_id = '61'")).scalar() is None

    # reparse: nothing changes
    stats = reparse_all()
    assert stats["changed"] == 0 and stats["new"] == 0

    log_in(client)
    page = client.get("/?intent=all&status=all").text
    assert "Sauvage Eau de Parfum · full" in page and "(from previous message)" in page and "📞 09111222333" in page


def test_human_edit_is_one_item(client, db):  # noqa: F811
    token = log_in(client)
    add(301, "dior sauvage နဲ့ stw intensely ဝယ်ချင်", customer="71", when=T0)
    run_batch()
    mid = scalar(db, "SELECT id FROM messages WHERE external_message_id = '301'")
    pid = scalar(db, "SELECT id FROM products WHERE name = 'Sauvage Eau de Parfum'")
    assert "has 2 items" in client.get(f"/messages/{mid}").text
    client.post(f"/messages/{mid}/parse", data={"csrf": token, "intent": "buy", "product_id": str(pid),
                                                "size_ml": "", "full_bottle": "1", "quantity": "1"})
    assert items(db, "301") == [("Sauvage Eau de Parfum", None, True, 1, None, False)]


def test_multi_item_quick_reply(client, db):  # noqa: F811
    log_in(client)
    run_import(xlsx(STW, ["Dior", "Sauvage Eau de Parfum", 100, 420000, None, 20000, 38000, "yes"]))
    add(401, "stw intensely 5ml, sauvage edp 10ml ဘယ်လောက်လဲ", customer="81")
    add(402, "stw intensely 5ml, hawas ice 10ml ယူပါမယ်", customer="82")  # unknown product: no button
    add(403, "stw intensely 5ml", customer="83", when=datetime.now(UTC) - timedelta(minutes=5))
    add(404, "full ရော ဘယ်လောက်လဲ", customer="83")  # product from context: no button
    run_batch()
    page = client.get("/?intent=all").text

    def title(external: str) -> str | None:
        mid = scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=external)
        m = re.search(rf'id="msg-{mid}".*?(?:title="([^"]+)">💬 Reply price|</li>)', page, re.S)
        return m.group(1) if m else None

    assert title("401") == ("မင်္ဂလာပါ။\nStronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။\n"
                            "Sauvage Eau de Parfum 10ml က 38,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။")
    assert title("402") is None and title("404") is None
    mid = scalar(db, "SELECT id FROM messages WHERE external_message_id = '401'")
    detail = client.get(f"/messages/{mid}").text
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    assert f"p1={stw}&amp;s1=5&amp;p2=" in detail
