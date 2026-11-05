from datetime import date
from decimal import Decimal

import httpx

from app.pipeline import fx
from tests.conftest import make_extraction, upload


class Resp:
    def __init__(self, status: int, body: dict):
        self.status_code, self.body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self.body


def fake_get(urls: list[str], community: dict | None):
    """ECB doesn't know AED; the community source does (if given)."""

    def get(url, params=None, timeout=None):
        urls.append(url)
        if "frankfurter" in url:
            return Resp(404, {"message": "not found"})
        return Resp(200, community) if community else Resp(404, {})

    return get


def test_currencies_the_ecb_lacks_use_the_fallback_source(client, monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr(fx.httpx, "get", fake_get(urls, {"aed": {"inr": 22.75}}))
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert fx.get_rate(db, date(2026, 10, 1), "AED", "INR") == Decimal("22.75")
        db.commit()
        # Cached: no second lookup.
        n = len(urls)
        assert fx.get_rate(db, date(2026, 10, 1), "AED", "INR") == Decimal("22.75")
        assert len(urls) == n
    assert "2026-10-01" in urls[1] and "/aed.min.json" in urls[1]


def test_expenses_without_a_rate_are_reported_not_hidden(client, fake_ai, monkeypatch):
    monkeypatch.setattr(fx.httpx, "get", fake_get([], None))
    fake_ai.extractions = [
        make_extraction(
            currency="AED",
            country_code="AE",
            subtotal=None,
            tax_inclusive=True,
            rounding=None,
            tax_lines=[],
            total=141.44,
            line_items=[],
            merchant=make_extraction().merchant.model_copy(
                update={"tax_ids": [], "name": "XYZ Supermarket"}
            ),
        )
    ]
    receipt = upload(client)
    draft = client.get(f"/api/receipts/{receipt['id']}").json()["draft"]
    expense = client.post(f"/api/receipts/{receipt['id']}/confirm", json=draft).json()
    month = expense["purchased_on"][:7]
    summary = client.get("/api/summary", params={"month": month}).json()
    assert summary["unconverted"] == [{"currency": "AED", "total": "141.44", "count": 1}]
    assert Decimal(summary["total"]) == 0


def test_reconvert_fills_in_rates_that_were_missing(client, fake_ai, monkeypatch):
    monkeypatch.setattr(fx.httpx, "get", fake_get([], None))
    test_expenses_without_a_rate_are_reported_not_hidden(client, fake_ai, monkeypatch)
    assert client.post("/api/expenses/reconvert").json() == {"converted": 0}

    monkeypatch.setattr(fx.httpx, "get", fake_get([], {"aed": {"inr": 22.75}}))
    assert client.post("/api/expenses/reconvert").json() == {"converted": 1}
    expense = client.get("/api/expenses").json()[0]
    assert Decimal(expense["total_home"]) == Decimal("3217.76")  # 141.44 x 22.75


def test_currency_switch_without_a_rate_changes_nothing(client, monkeypatch):
    monkeypatch.setattr(fx.httpx, "get", fake_get([], None))
    client.put("/api/budgets", json={"category_id": None, "amount": "50000"})
    before = client.get("/api/settings").json()["home_currency"]
    resp = client.put("/api/settings", json={"home_currency": "AED"})
    assert resp.status_code == 503
    assert client.get("/api/settings").json()["home_currency"] == before
    assert len(client.get("/api/budgets").json()) == 1
