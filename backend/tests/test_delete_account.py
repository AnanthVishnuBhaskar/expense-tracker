from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    AuthToken,
    Budget,
    Category,
    Expense,
    LineItem,
    Merchant,
    MerchantRule,
    Receipt,
    SocialLogin,
    User,
)
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, confirmed_signup, receipt_png, upload
from tests.test_social import error_of, idp, new_client, sign_in  # noqa: F401

XYZ = ("XYZ User", "xyz@example.com", "xyz password 123")


def counts(user_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        n = {
            m.__name__: db.scalar(select(func.count()).select_from(m).where(m.user_id == user_id))
            for m in (
                AuthToken,
                Budget,
                Category,
                Expense,
                Merchant,
                MerchantRule,
                Receipt,
                SocialLogin,
            )
        }
        n["LineItem"] = db.scalar(
            select(func.count())
            .select_from(LineItem)
            .join(Expense)
            .where(Expense.user_id == user_id)
        )
        n["User"] = db.scalar(select(func.count()).select_from(User).where(User.id == user_id))
        return n


def user_id(email: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == email))


def test_delete_account_removes_everything_and_only_that(client, outbox):
    from fastapi.testclient import TestClient

    from app.main import app

    # ABC (the fixture's account) keeps a receipt of its own throughout.
    abc_receipt = upload(client, receipt_png("abc"))
    client.post(f"/api/receipts/{abc_receipt['id']}/confirm", json=abc_receipt["draft"])
    abc_before = counts(user_id(TEST_EMAIL))

    c = TestClient(app)
    confirmed_signup(c, *XYZ)
    r = upload(c, receipt_png("xyz"))
    assert c.post(f"/api/receipts/{r['id']}/confirm", json=r["draft"]).status_code == 200
    upload(c, receipt_png("xyz-2"))  # one still waiting in the inbox
    xyz = user_id(XYZ[1])
    before = counts(xyz)
    assert before["Receipt"] == 2 and before["Expense"] == 1 and before["Category"] > 0
    with SessionLocal() as db:
        photos = list(db.scalars(select(Receipt.image_path).where(Receipt.user_id == xyz)))
    assert all((get_settings().upload_dir / p).exists() for p in photos)

    # Both the password and the typed email are required.
    wrong = c.post("/api/auth/delete-account", json={"confirm": XYZ[1], "password": "nope nope"})
    assert wrong.status_code == 403
    typo = c.post(
        "/api/auth/delete-account", json={"confirm": "xyz@example.co", "password": XYZ[2]}
    )
    assert typo.status_code == 422
    assert counts(xyz) == before

    outbox.clear()
    resp = c.post(
        "/api/auth/delete-account", json={"confirm": " XYZ@example.com ", "password": XYZ[2]}
    )
    assert resp.status_code == 204
    assert all(v == 0 for v in counts(xyz).values()), counts(xyz)
    assert not any((get_settings().upload_dir / p).exists() for p in photos)
    assert c.get("/api/auth/me").json()["authenticated"] is False
    assert outbox[-1]["to"] == XYZ[1] and "deleted" in outbox[-1]["subject"]

    # The old password no longer opens anything, and the email can sign up again from scratch.
    login = c.post("/api/auth/login", json={"email": XYZ[1], "password": XYZ[2]})
    assert login.status_code == 401
    # ABC is untouched.
    assert counts(user_id(TEST_EMAIL)) == abc_before
    assert client.get("/api/expenses").status_code == 200
    assert (
        client.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        ).status_code
        == 200
    )


def test_a_stolen_session_from_before_still_cant_be_reused(client):
    cookie = client.cookies.get("session")
    assert (
        client.post(
            "/api/auth/delete-account", json={"confirm": TEST_EMAIL, "password": TEST_PASSWORD}
        ).status_code
        == 204
    )
    client.cookies.set("session", cookie)
    assert client.get("/api/expenses").status_code == 401


def test_social_only_account_confirms_with_its_email(client, idp):  # noqa: F811
    c = new_client()
    assert error_of(sign_in(c, idp, "google")) is None
    xyz = user_id("xyz@example.com")
    assert c.post("/api/auth/delete-account", json={"confirm": "DELETE"}).status_code == 422
    assert (
        c.post("/api/auth/delete-account", json={"confirm": "xyz@example.com"}).status_code == 204
    )
    assert all(v == 0 for v in counts(xyz).values())
    # Signing in with Google again makes a brand-new, empty account.
    c2 = new_client()
    assert error_of(sign_in(c2, idp, "google")) is None
    assert user_id("xyz@example.com") != xyz


def test_needs_a_session(client):
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).post(
        "/api/auth/delete-account", json={"confirm": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 401
