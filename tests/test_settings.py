"""Settings: payment methods and reply templates (defaults, validation, reset, audit)."""
import pytest
from sqlalchemy import text

from app.replies import templates as replies
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def test_default_templates_are_valid():
    for t in replies.TEMPLATES:
        assert replies.validate(t.key, t.default) == t.default
        assert set(replies.placeholders(t.default)) == set(t.example), t.key
        replies.render(t.default, **t.example)
    assert replies.render(replies.BY_KEY["price_one"].default, product="Aventus", size="5ml", price="65,000") \
        == "Aventus 5ml က 65,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"


@pytest.mark.parametrize("bad", ["{product.__class__}", "{price:>10}", "{product!r}", "{0}", "{oops", "{total}", " "])
def test_template_validation_rejects(bad):
    with pytest.raises(ValueError):
        replies.validate("price_one", bad)


def test_payment_methods(client, db):  # noqa: F811
    token = log_in(client)
    r = client.post("/settings/payment-methods", data={
        "csrf": token, "name": "KPay", "account_number": "09 123 456 789", "account_name": "Daw Test"})
    assert r.status_code == 200 and "KPay added" in r.text
    with db.connect() as c:
        mid = c.execute(text("SELECT id FROM payment_methods")).scalar()
    client.post(f"/settings/payment-methods/{mid}", data={
        "csrf": token, "name": "KBZPay", "account_number": "09 1", "account_name": "Daw Test"})  # no active=1
    with db.connect() as c:
        assert c.execute(text("SELECT name, active FROM payment_methods")).one() == ("KBZPay", False)
    r = client.post("/settings/payment-methods", data={"csrf": token, "name": " ", "account_number": "1",
                                                       "account_name": "x"})
    assert r.status_code == 400
    client.post(f"/settings/payment-methods/{mid}/delete", data={"csrf": token})
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM payment_methods")).scalar() == 0
        assert c.execute(text("SELECT action FROM audit_log ORDER BY id")).scalars().all() == [
            "payment_method.add", "payment_method.update", "payment_method.delete"]


def test_reply_templates(client, db):  # noqa: F811
    token = log_in(client)
    page = client.get("/settings").text
    assert "လောလောဆယ် ကုန်နေပါတယ်နော်" in page  # default shown
    assert "Aventus 10ml လောလောဆယ် ကုန်နေပါတယ်နော်။" in page  # rendered example

    r = client.post("/settings/templates/out_of_stock", data={"csrf": token, "text": "{product} {size} ကုန်ပြီ\r\nsorry"})
    assert r.status_code == 200 and "Reply saved" in r.text
    with db.connect() as c:
        assert c.execute(text("SELECT text FROM reply_templates WHERE key = 'out_of_stock'")).scalar() \
            == "{product} {size} ကုန်ပြီ\nsorry"

    r = client.post("/settings/templates/out_of_stock", data={"csrf": token, "text": "{price} ကုန်ပြီ"})
    assert r.status_code == 400 and "Unknown placeholder {price}" in r.text
    with db.connect() as c:  # bad text was not saved
        assert c.execute(text("SELECT text FROM reply_templates WHERE key = 'out_of_stock'")).scalar().endswith("sorry")

    client.post("/settings/templates/out_of_stock/reset", data={"csrf": token})
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM reply_templates")).scalar() == 0
    assert client.post("/settings/templates/nope", data={"csrf": token, "text": "x"}).status_code == 404
