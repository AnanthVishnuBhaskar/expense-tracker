from datetime import date
from decimal import Decimal

from app.ledger import period_bounds


def add(client, on: date, total: str):
    resp = client.post(
        "/api/expenses",
        json={
            "merchant": {"name": "ABC Store"},
            "currency": "INR",
            "purchased_on": on.isoformat(),
            "total": total,
            "line_items": [],
            "payments": [],
        },
    )
    assert resp.status_code == 201, resp.text


def months_ago(n: int) -> date:
    today = date.today()
    i = today.year * 12 + today.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def test_period_bounds():
    today = date.today()
    start, _, months = period_bounds("ytd", "", None)
    assert start == date(today.year, 1, 1) and months == today.month
    start, _, months = period_bounds("1y", "", None)
    assert months == 12 and start == months_ago(11)
    start, _, months = period_bounds("all", "", months_ago(20))
    assert months == 21 and start == months_ago(20)
    assert period_bounds("month", "2026-02", None) == (date(2026, 2, 1), date(2026, 3, 1), 1)


def test_longer_periods_sum_months_and_chart_by_month(client):
    add(client, date.today(), "100")
    add(client, months_ago(5), "200")
    add(client, months_ago(14), "400")
    client.put("/api/budgets", json={"category_id": None, "amount": "1000"})

    month = client.get("/api/summary").json()
    assert Decimal(month["total"]) == 100 and month["bucket"] == "day"

    year = client.get("/api/summary", params={"period": "1y"}).json()
    assert Decimal(year["total"]) == 300
    assert year["bucket"] == "month" and len(year["by_day"]) == 12
    assert Decimal(year["budget"]) == 12000  # one monthly budget per month
    # Compared with the 12 months before.
    assert Decimal(year["previous_total"]) == 400

    everything = client.get("/api/summary", params={"period": "all"}).json()
    assert Decimal(everything["total"]) == 700 and len(everything["by_day"]) == 15

    listed = client.get("/api/expenses", params={"period": "1y"}).json()
    assert len(listed) == 2
