from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Category, User
from tests.conftest import (
    TEST_EMAIL,
    TEST_PASSWORD,
    confirmed_signup,
    make_extraction,
    upload,
)


def second_user(name="XYZ User", email="xyz@example.com") -> TestClient:
    from app.main import app

    c = TestClient(app)
    confirmed_signup(c, name, email, "another password")
    return c


def test_signup_signs_you_in_with_default_categories(client):
    me = client.get("/api/auth/me").json()
    assert me == {
        "authenticated": True,
        "name": "ABC User",
        "email": TEST_EMAIL,
        "signup_open": True,
        "email_enabled": True,
        "social_providers": [],
        "has_password": True,
        "verification_sent_to": None,
    }
    assert len(client.get("/api/categories").json()) > 5


def test_email_is_case_insensitive_and_unique(client):
    from app.main import app

    c = TestClient(app)
    resp = c.post(
        "/api/auth/signup",
        json={"name": "Dup", "email": " ABC@Example.com ", "password": "whatever123"},
    )
    assert resp.status_code == 409
    assert (
        c.post(
            "/api/auth/login", json={"email": "ABC@EXAMPLE.COM", "password": TEST_PASSWORD}
        ).status_code
        == 200
    )


def test_signup_checks_its_inputs(client):
    from app.main import app

    c = TestClient(app)
    bad = [
        {"name": "A", "email": "not-an-email", "password": "long enough"},
        {"name": "A", "email": "a@example.com", "password": "short"},
        {"name": " ", "email": "a@example.com", "password": "long enough"},
    ]
    for body in bad:
        assert c.post("/api/auth/signup", json=body).status_code == 422


def test_wrong_email_and_wrong_password_look_the_same(client):
    from app.main import app

    c = TestClient(app)
    a = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    b = c.post("/api/auth/login", json={"email": TEST_EMAIL, "password": "x"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_people_only_see_their_own_data(client, fake_ai):
    fake_ai.extractions = [make_extraction()]
    receipt = upload(client)
    draft = client.get(f"/api/receipts/{receipt['id']}").json()["draft"]
    expense = client.post(f"/api/receipts/{receipt['id']}/confirm", json=draft).json()
    my_category = client.get("/api/categories").json()[0]["id"]

    other = second_user()
    assert other.get("/api/expenses").json() == []
    assert other.get("/api/receipts").json() == []
    assert other.get(f"/api/expenses/{expense['id']}").status_code == 404
    assert other.get(f"/api/receipts/{receipt['id']}").status_code == 404
    assert other.get(f"/api/receipts/{receipt['id']}/image").status_code == 404
    assert other.delete(f"/api/expenses/{expense['id']}").status_code == 404
    assert other.get("/api/summary").json()["count"] == 0

    # Nor can they file their own expense under someone else's category.
    fake_ai.extractions = [make_extraction(receipt_number="XYZ-2")]
    theirs = upload(other)
    their_draft = other.get(f"/api/receipts/{theirs['id']}").json()["draft"]
    resp = other.post(
        f"/api/receipts/{theirs['id']}/confirm", json={**their_draft, "category_id": my_category}
    )
    assert resp.status_code == 422
    saved = other.post(f"/api/receipts/{theirs['id']}/confirm", json=their_draft).json()
    assert (
        other.patch(
            f"/api/expenses/{saved['id']}/category", params={"category_id": my_category}
        ).status_code
        == 422
    )


def test_first_account_keeps_data_from_before_accounts(client):
    # Simulate the single-user setup: one user with no email and some categories.
    with SessionLocal() as db:
        db.query(User).delete()
        db.commit()
        legacy = User(name="Me")
        db.add(legacy)
        db.flush()
        db.add(Category(user_id=legacy.id, name="Old category", icon="tag", color="#9a958e"))
        db.commit()
        legacy_id = legacy.id

    c = second_user(name="ABC Owner", email="owner@example.com")
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == "owner@example.com"))
        assert owner.id == legacy_id
    assert [cat["name"] for cat in c.get("/api/categories").json()] == ["Old category"]

    # Later accounts start fresh.
    assert second_user().get("/api/categories").json()[0]["name"] != "Old category"


def test_signup_can_be_turned_off(client, monkeypatch):
    from app.main import app

    monkeypatch.setattr(get_settings(), "allow_signup", False)
    c = TestClient(app)
    resp = c.post(
        "/api/auth/signup",
        json={"name": "XYZ", "email": "xyz@example.com", "password": "long enough"},
    )
    assert resp.status_code == 403
    assert c.get("/api/auth/me").json()["signup_open"] is False


def test_empty_session_secret_falls_back_to_a_stored_random_one(monkeypatch, tmp_path):
    from app.config import Settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SESSION_SECRET", "")
    first = Settings().session_secret
    assert len(first) > 20
    assert Settings().session_secret == first
