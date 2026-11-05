from datetime import date
from decimal import Decimal

from app.pipeline import checks
from app.pipeline.schemas import QualityCheck, TaxId
from tests.conftest import make_extraction, receipt_png, upload


def test_clean_receipt_waits_for_confirmation(client):
    receipt = upload(client)
    assert receipt["status"] == "ready_to_confirm"
    assert receipt["issues"] == []
    draft = receipt["draft"]
    assert draft["merchant"]["name"] == "ABC Fresh Mart"
    assert draft["customer"]["loyalty_id"] == "LOY-77"
    assert Decimal(draft["total"]) == Decimal(179)
    assert draft["category_id"] is not None
    # Nothing reaches the ledger before the user confirms.
    assert client.get("/api/expenses").json() == []


def test_confirm_saves_expense_and_learns_category(client, fake_ai):
    receipt = upload(client)
    categories = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    draft = receipt["draft"]
    draft["category_id"] = categories["Home"]  # user overrides the suggestion
    resp = client.post(f"/api/receipts/{receipt['id']}/confirm", json=draft)
    assert resp.status_code == 200, resp.text
    expense = resp.json()
    assert expense["category_name"] == "Home"
    assert Decimal(expense["total"]) == Decimal("179.00")
    assert Decimal(expense["total_home"]) == Decimal("179.00")
    assert len(expense["line_items"]) == 2
    assert expense["merchant"]["tax_ids"][0]["value"] == "29AABCR1718E1ZL"

    # Next receipt from the same merchant uses the learned rule, not the model.
    fake_ai.extractions = [
        make_extraction(receipt_number="INV-2000", total=179, purchase_date="2026-10-21")
    ]
    calls = fake_ai.categorize_calls
    second = upload(client, _other_png())
    assert second["draft"]["category_id"] == categories["Home"]
    assert fake_ai.categorize_calls == calls


def _other_png() -> bytes:
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(img)
    for y in range(40, 860, 28):
        draw.text((30, y), "SECOND RECEIPT 55.10 TOTAL", fill="black")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_totals_mismatch_retries_then_needs_review(client, fake_ai):
    fake_ai.extractions = [make_extraction(total=999)]
    receipt = upload(client)
    assert fake_ai.extract_calls == 2
    assert receipt["status"] == "needs_review"
    assert any("printed total" in i for i in receipt["issues"])


def test_retry_fixes_mismatch(client, fake_ai):
    fake_ai.extractions = [make_extraction(total=999), make_extraction()]
    receipt = upload(client)
    assert fake_ai.extract_calls == 2
    assert receipt["status"] == "ready_to_confirm"


def test_unreadable_photo_asks_for_retake(client, fake_ai):
    fake_ai.quality = QualityCheck(
        is_receipt=True,
        readable=False,
        receipt_count=1,
        issues=["blurry"],
        retake_hint="Hold the phone steady; the total is blurry.",
    )
    receipt = upload(client)
    assert receipt["status"] == "retake"
    assert "blurry" in receipt["status_detail"]
    assert receipt["draft"] is None  # the parallel read, if any, is thrown away


def test_not_a_receipt_is_rejected(client, fake_ai):
    fake_ai.quality = QualityCheck(
        is_receipt=False, readable=True, receipt_count=0, issues=[], retake_hint=None
    )
    assert upload(client)["status"] == "rejected"


def test_same_photo_again_is_not_read_twice(client, fake_ai):
    first = upload(client)
    calls = fake_ai.extract_calls
    again = upload(client)
    assert again["already_uploaded"] is True
    assert again["id"] == first["id"] and again["uploaded_at"] == first["uploaded_at"]
    assert fake_ai.extract_calls == calls
    # The same photo twice in one batch counts once too.
    files = [("files", (f"r{i}.png", receipt_png("batch"), "image/png")) for i in range(2)]
    batch = client.post("/api/receipts", files=files).json()
    assert [r["already_uploaded"] for r in batch] == [False, True]
    assert batch[0]["id"] == batch[1]["id"]


def test_new_photo_of_a_saved_receipt_is_flagged_with_its_upload_date(client):
    first = upload(client)
    client.post(f"/api/receipts/{first['id']}/confirm", json=first["draft"])
    second = upload(client, receipt_png("another photo"))
    assert second["already_uploaded"] is False
    assert second["status"] == "needs_review"
    assert second["duplicate_of_expense_id"] is not None
    assert any("which you uploaded on" in i for i in second["issues"])


def test_discarded_photo_can_be_uploaded_again(client):
    first = upload(client)
    client.post(f"/api/receipts/{first['id']}/discard")
    again = upload(client)
    assert again["already_uploaded"] is False and again["id"] != first["id"]


def test_foreign_currency_is_converted(client, fake_ai, monkeypatch):
    from app.pipeline import fx

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"rates": {"INR": 90.5}}

    monkeypatch.setattr(fx.httpx, "get", lambda *a, **k: Resp())
    fake_ai.extractions = [
        make_extraction(
            currency="EUR",
            country_code="DE",
            subtotal=None,
            tax_inclusive=True,
            rounding=None,
            tax_lines=[],
            total=10.0,
            line_items=[],
            merchant=make_extraction().merchant.model_copy(
                update={"tax_ids": [], "name": "ABC Bäckerei"}
            ),
        )
    ]
    receipt = upload(client)
    assert receipt["status"] == "ready_to_confirm", receipt["issues"]
    assert Decimal(receipt["draft"]["total_home"]) == Decimal("905.00")


def test_jpy_has_no_decimals():
    from app.money import from_minor, to_minor

    assert to_minor(Decimal(1200), "JPY") == 1200
    assert to_minor(Decimal("1.234"), "KWD") == 1234
    assert from_minor(17900, "INR") == Decimal("179.00")


def test_date_and_tax_id_checks():
    assert checks.check_date(date(2026, 12, 3), date(2026, 3, 12))
    assert checks.check_date(date(2026, 3, 12), date(2026, 3, 12)) == []
    bad = make_extraction(
        merchant=make_extraction().merchant.model_copy(
            update={"tax_ids": [TaxId(type="GSTIN", value="29AABCR1718")]}
        )
    )
    assert checks.check_tax_ids(bad)


def test_summary_and_budget_alert(client):
    receipt = upload(client)
    client.post(f"/api/receipts/{receipt['id']}/confirm", json=receipt["draft"])
    groceries = next(c for c in client.get("/api/categories").json() if c["name"] == "Groceries")
    client.put("/api/budgets", json={"category_id": groceries["id"], "amount": "150"})
    summary = client.get("/api/summary", params={"month": "2026-10"}).json()
    assert Decimal(summary["total"]) == Decimal("179.00")
    assert summary["by_category"][0]["name"] == "Groceries"
    assert any(i["kind"] == "budget" for i in summary["insights"])


def test_export_csv(client):
    receipt = upload(client)
    client.post(f"/api/receipts/{receipt['id']}/confirm", json=receipt["draft"])
    resp = client.get("/api/expenses/export.csv")
    assert resp.status_code == 200
    assert "ABC Fresh Mart" in resp.text


def test_year_overview_totals_each_month(client):
    home = client.get("/api/settings").json()["home_currency"]
    for day, amount in [("2026-03-04", "100.00"), ("2026-03-20", "50.50"), ("2026-07-01", "10.00")]:
        res = client.post(
            "/api/expenses",
            json={
                "merchant": {"name": "Shop"},
                "purchased_on": day,
                "currency": home,
                "total": amount,
            },
        )
        assert res.status_code == 201, res.text
    data = client.get("/api/summary/months?year=2026").json()
    by_month = {m["month"]: m for m in data["months"]}
    assert len(data["months"]) == 12
    assert by_month["2026-03"]["count"] == 2
    assert float(by_month["2026-03"]["total"]) == 150.50
    assert by_month["2026-02"]["count"] == 0
    assert data["first_month"] == "2026-03"


def test_category_picked_during_extraction_skips_extra_call(client, fake_ai):
    fake_ai.extractions = [make_extraction(category="Groceries")]
    receipt = upload(client)
    groceries = next(c for c in client.get("/api/categories").json() if c["name"] == "Groceries")
    assert receipt["draft"]["category_id"] == groceries["id"]
    assert fake_ai.categorize_calls == 0


def test_unexpected_error_fails_instead_of_hanging(client, fake_ai, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network fell over")

    monkeypatch.setattr(fake_ai, "check_quality", boom)
    receipt = upload(client)
    assert receipt["status"] == "failed"
    assert "Something went wrong" in receipt["status_detail"]
