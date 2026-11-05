from datetime import date
from decimal import Decimal

from app.currency import country_for, currency_for
from app.pipeline import fx


def test_country_from_time_zone_then_locale():
    assert country_for("Asia/Kolkata", "en-US") == "IN"  # time zone wins over an en-US Mac
    assert country_for("Asia/Calcutta", None) == "IN"
    assert country_for(None, "de-CH") == "CH"
    assert country_for("Etc/UTC", "en") is None
    assert currency_for("FR") == "EUR"
    assert currency_for("ZZ") is None


def test_detect_sets_currency_once(client):
    res = client.post("/api/settings/detect", json={"timezone": "Europe/Paris", "locale": "fr-FR"})
    assert res.json()["home_currency"] == "EUR"
    assert res.json()["home_currency_source"] == "detected"

    client.put("/api/settings", json={"home_currency": "GBP"})
    res = client.post("/api/settings/detect", json={"timezone": "Asia/Tokyo", "locale": "ja-JP"})
    assert res.json()["home_currency"] == "GBP"  # a hand-picked currency is never overridden
    assert res.json()["home_currency_source"] == "user"


def test_switching_home_currency_reconverts_expenses_and_budgets(client, monkeypatch):
    def fake_rate(db, on, base, quote):
        return Decimal(1) if base == quote else {("INR", "USD"): Decimal("0.012")}[(base, quote)]

    monkeypatch.setattr(fx, "get_rate", fake_rate)
    assert client.get("/api/settings").json()["home_currency"] == "INR"
    client.post(
        "/api/expenses",
        json={
            "merchant": {"name": "Shop"},
            "purchased_on": date.today().isoformat(),
            "currency": "INR",
            "total": "1000.00",
        },
    )
    client.put("/api/budgets", json={"category_id": None, "amount": "50000"})

    client.put("/api/settings", json={"home_currency": "USD"})

    expense = client.get("/api/expenses").json()[0]
    assert expense["home_currency"] == "USD"
    assert float(expense["total_home"]) == 12.0
    assert float(client.get("/api/budgets").json()[0]["amount"]) == 600.0
