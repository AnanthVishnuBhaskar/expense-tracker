from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.mailer import EmailError
from app.models import AuthToken
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, link_token

NEW = {"name": "XYZ User", "email": "xyz@example.com", "password": "xyz password 123"}


@pytest.fixture
def mail_on():
    """Email is on in every test (see conftest); kept for readability."""


def fresh(client) -> TestClient:
    from app.main import app

    return TestClient(app)


def age_tokens(seconds: int) -> None:
    """Pretend the last links went out a while ago, past the resend cooldown."""
    with SessionLocal() as db:
        db.execute(
            update(AuthToken).values(created_at=AuthToken.created_at - timedelta(seconds=seconds))
        )
        db.commit()


def test_signup_waits_for_the_emailed_link(client, mail_on, outbox):
    outbox.clear()  # drop the ABC account's own confirmation email
    c = fresh(client)
    resp = c.post("/api/auth/signup", json=NEW)
    assert resp.status_code == 201
    body = resp.json()
    assert body["authenticated"] is False and body["verification_sent_to"] == "xyz@example.com"
    assert "session" not in c.cookies
    assert outbox[-1]["to"] == "xyz@example.com"
    assert "Confirm" in outbox[-1]["subject"]

    # Signing in before confirming says so (and the right password is required to learn it).
    resp = c.post("/api/auth/login", json={"email": NEW["email"], "password": "wrong password"})
    assert resp.status_code == 401
    resp = c.post("/api/auth/login", json={"email": NEW["email"], "password": NEW["password"]})
    assert resp.status_code == 403 and "confirm your email" in resp.json()["detail"]

    token = link_token(outbox[0], "verify-email")
    resp = c.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200 and resp.json()["authenticated"] is True
    assert c.get("/api/expenses").status_code == 200
    # Single use.
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 400


def test_newer_links_void_older_ones_and_resends_are_throttled(client, mail_on, outbox):
    outbox.clear()  # drop the ABC account's own confirmation email
    c = fresh(client)
    c.post("/api/auth/signup", json=NEW)
    first = link_token(outbox[-1], "verify-email")
    # Asking again at once doesn't send another email.
    assert c.post("/api/auth/resend-verification", json={"email": NEW["email"]}).status_code == 204
    assert len(outbox) == 1
    age_tokens(120)
    assert c.post("/api/auth/resend-verification", json={"email": NEW["email"]}).status_code == 204
    assert len(outbox) == 2
    second = link_token(outbox[-1], "verify-email")
    assert c.post("/api/auth/verify-email", json={"token": first}).status_code == 400
    assert c.post("/api/auth/verify-email", json={"token": second}).status_code == 200


def test_expired_and_made_up_links_are_refused(client, mail_on, outbox):
    outbox.clear()  # drop the ABC account's own confirmation email
    c = fresh(client)
    c.post("/api/auth/signup", json=NEW)
    token = link_token(outbox[-1], "verify-email")
    with SessionLocal() as db:
        db.execute(update(AuthToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 400
    assert c.post("/api/auth/verify-email", json={"token": "x" * 43}).status_code == 400


def test_a_failed_send_saves_nothing_so_signing_up_again_works(
    client, mail_on, outbox, monkeypatch
):
    def broken(*args):
        raise EmailError("provider down")

    monkeypatch.setattr("app.accounts.send_email", broken)
    c = fresh(client)
    resp = c.post("/api/auth/signup", json=NEW)
    assert resp.status_code == 503 and "try again" in resp.json()["detail"]
    monkeypatch.setattr(
        "app.accounts.send_email", lambda s, to, subj, text, html: outbox.append({"text": text})
    )
    assert c.post("/api/auth/signup", json=NEW).status_code == 201


def test_unknown_emails_get_the_same_answer(client, mail_on, outbox):
    outbox.clear()  # drop the ABC account's own confirmation email
    c = fresh(client)
    for path in ("/api/auth/forgot-password", "/api/auth/resend-verification"):
        assert c.post(path, json={"email": "nobody@example.com"}).status_code == 204
    assert outbox == []


def test_reset_password_signs_out_everywhere_else(client, mail_on, outbox):
    # `client` is signed in as the ABC account.
    other = fresh(client)
    assert other.post("/api/auth/forgot-password", json={"email": TEST_EMAIL}).status_code == 204
    token = link_token(outbox[-1], "reset-password")

    assert (
        other.post(
            "/api/auth/reset-password", json={"token": token, "password": "short"}
        ).status_code
        == 422
    )
    resp = other.post(
        "/api/auth/reset-password", json={"token": token, "password": "a brand new password"}
    )
    assert resp.status_code == 200 and resp.json()["authenticated"] is True
    assert other.get("/api/expenses").status_code == 200
    # The older session is gone, and so is the old password.
    assert client.get("/api/expenses").status_code == 401
    old = {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    assert fresh(client).post("/api/auth/login", json=old).status_code == 401
    # The link can't be used twice.
    again = {"token": token, "password": "another new password"}
    assert fresh(client).post("/api/auth/reset-password", json=again).status_code == 400


def test_changing_the_password_voids_outstanding_links(client, mail_on, outbox):
    c = fresh(client)
    c.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
    first = link_token(outbox[-1], "reset-password")
    age_tokens(120)
    c.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
    second = link_token(outbox[-1], "reset-password")
    assert (
        c.post(
            "/api/auth/reset-password", json={"token": second, "password": "new password one"}
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/api/auth/reset-password", json={"token": first, "password": "new password two"}
        ).status_code
        == 400
    )


def test_signup_squatting_is_not_possible(client, mail_on, outbox):
    outbox.clear()  # drop the ABC account's own confirmation email
    """Someone who signs up with your email can't sign in, and you can take it back."""
    stranger = fresh(client)
    stranger.post("/api/auth/signup", json=NEW)
    assert (
        stranger.post(
            "/api/auth/login", json={"email": NEW["email"], "password": NEW["password"]}
        ).status_code
        == 403
    )
    owner = fresh(client)
    resp = owner.post("/api/auth/signup", json={**NEW, "password": "the real owner pw"})
    assert resp.status_code == 409 and "reset your password" in resp.json()["detail"]
    owner.post("/api/auth/forgot-password", json={"email": NEW["email"]})
    token = link_token(outbox[-1], "reset-password")
    resp = owner.post(
        "/api/auth/reset-password", json={"token": token, "password": "the real owner pw"}
    )
    assert resp.status_code == 200
    # The stranger's pending confirmation link no longer works either.
    old_verify = link_token(outbox[0], "verify-email")
    assert stranger.post("/api/auth/verify-email", json={"token": old_verify}).status_code == 400


def test_links_use_the_configured_address_not_the_request_host(client, mail_on, outbox):
    c = TestClient(client.app, base_url="https://evil.example")
    c.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
    assert "https://abc.example/reset-password?token=" in outbox[-1]["text"]
    assert "evil" not in outbox[-1]["html"]


def test_railway_domain_is_used_for_links():
    s = Settings(railway_public_domain="abc-production.up.railway.app")
    assert s.public_url == "https://abc-production.up.railway.app"
    assert Settings(app_url="https://xyz.example/").public_url == "https://xyz.example"


def test_without_email_there_is_no_email_sign_up(client, outbox, monkeypatch):
    outbox.clear()  # drop the ABC account's own confirmation email
    s = get_settings()
    monkeypatch.setattr(s, "resend_api_key", "")
    c = fresh(client)
    assert c.get("/api/auth/me").json()["email_enabled"] is False
    resp = c.post("/api/auth/signup", json=NEW)
    assert resp.status_code == 403 and "isn't available" in resp.json()["detail"]
    assert c.post("/api/auth/forgot-password", json={"email": NEW["email"]}).status_code == 404
    assert outbox == []


def test_console_email_for_local_testing(client, monkeypatch, caplog):
    from app import mailer

    s = Settings(email_console=True)
    assert s.email_enabled
    with caplog.at_level("WARNING"):
        mailer.send_email(s, "xyz@example.com", "Hi", "link: https://abc.example/x", "<p></p>")
    assert "https://abc.example/x" in caplog.text


def test_change_password_needs_the_current_one_and_alerts_by_email(client, outbox):
    outbox.clear()
    other = fresh(client)
    other.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    wrong = {"current_password": "not it", "new_password": "a new password 1"}
    assert client.post("/api/auth/change-password", json=wrong).status_code == 403
    same = {"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD}
    assert client.post("/api/auth/change-password", json=same).status_code == 422
    ok = {"current_password": TEST_PASSWORD, "new_password": "a new password 1"}
    resp = client.post("/api/auth/change-password", json=ok)
    assert resp.status_code == 200
    # This browser stays signed in; the other one is signed out.
    assert client.get("/api/expenses").status_code == 200
    assert other.get("/api/expenses").status_code == 401
    assert outbox[-1]["to"] == TEST_EMAIL and "password was changed" in outbox[-1]["subject"]
    # Signed-out visitors can't use it.
    assert fresh(client).post("/api/auth/change-password", json=ok).status_code == 401


def test_reset_alerts_by_email_and_refuses_the_same_password(client, outbox):
    c = fresh(client)
    c.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
    token = link_token(outbox[-1], "reset-password")
    same = {"token": token, "password": TEST_PASSWORD}
    assert c.post("/api/auth/reset-password", json=same).status_code == 422
    new = {"token": token, "password": "brand new password"}
    assert c.post("/api/auth/reset-password", json=new).status_code == 200
    assert "password was changed" in outbox[-1]["subject"]


def test_a_failed_alert_does_not_undo_the_change(client, outbox, monkeypatch):
    def broken(*args):
        raise EmailError("provider down")

    monkeypatch.setattr("app.accounts.send_email", broken)
    ok = {"current_password": TEST_PASSWORD, "new_password": "a new password 1"}
    assert client.post("/api/auth/change-password", json=ok).status_code == 200
