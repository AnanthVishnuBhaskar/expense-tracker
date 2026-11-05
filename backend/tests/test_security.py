from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.schemas import PaymentOut
from app.security import mask_card_numbers, sanitize_extraction
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, make_extraction, receipt_png, upload


def test_api_requires_login(client):
    anonymous = TestClient(app)
    assert anonymous.get("/api/expenses").status_code == 401
    assert (
        anonymous.post("/api/receipts", files=[("files", ("r.png", b"x", "image/png"))]).status_code
        == 401
    )
    assert anonymous.get("/api/auth/me").json()["authenticated"] is False


def test_wrong_password_is_rejected_and_rate_limited(client):
    anonymous = TestClient(app)
    codes = [
        anonymous.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": "nope"}
        ).status_code
        for _ in range(12)
    ]
    assert codes[0] == 401
    assert codes[-1] == 429


def test_session_cookie_is_locked_down(client):
    resp = TestClient(app).post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_logout_ends_session(client):
    client.post("/api/auth/logout")
    assert client.get("/api/expenses").status_code == 401


def test_security_headers(client):
    headers = client.get("/api/expenses").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cache-control"] == "no-store"


def test_full_card_numbers_are_masked():
    assert (
        mask_card_numbers("VISA 4111 1111 1111 1111 APPROVED")
        == "VISA **** **** **** 1111 APPROVED"
    )
    # Not a valid card number (fails Luhn), e.g. a GSTIN-like or order number: left alone.
    assert mask_card_numbers("Order 1234567890123") == "Order 1234567890123"
    ex = make_extraction(
        full_text="CARD 4111111111111111",
        payments=[
            PaymentOut(
                method="card",
                card_brand="VISA",
                card_last4="4111111111111111",
                reference=None,
                approval_code=None,
                amount=179,
            )
        ],
    )
    clean = sanitize_extraction(ex)
    assert clean.payments[0].card_last4 == "1111"
    assert "4111111111111111" not in clean.full_text


def test_discard_deletes_the_photo(client):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Receipt

    receipt = upload(client)
    with SessionLocal() as db:
        path = get_settings().upload_dir / db.get(Receipt, receipt["id"]).image_path
    assert path.exists()
    client.post(f"/api/receipts/{receipt['id']}/discard")
    assert not path.exists()
    assert client.get(f"/api/receipts/{receipt['id']}/image").status_code == 404


def test_deleting_an_expense_deletes_the_photo(client):
    receipt = upload(client)
    expense = client.post(f"/api/receipts/{receipt['id']}/confirm", json=receipt["draft"]).json()
    client.delete(f"/api/expenses/{expense['id']}")
    assert client.get(f"/api/receipts/{receipt['id']}/image").status_code == 404


def test_too_many_files_in_one_upload(client):
    files = [("files", (f"r{i}.png", receipt_png(), "image/png")) for i in range(21)]
    assert client.post("/api/receipts", files=files).status_code == 413


def test_non_image_upload_is_rejected(client):
    resp = client.post("/api/receipts", files=[("files", ("x.png", b"<script>", "image/png"))])
    assert resp.status_code == 415


def test_missing_api_key_gives_a_clear_error(monkeypatch):
    import pytest

    from app.config import Settings
    from app.pipeline.ai import AIError, AnthropicReceiptAI

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ai = AnthropicReceiptAI(Settings(anthropic_api_key=None))
    with pytest.raises(AIError, match="No Claude API key"):
        ai.check_quality(b"x", "image/jpeg")
