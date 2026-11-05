import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.social import MSA_TENANT
from app.config import get_settings
from app.db import SessionLocal
from app.models import SocialLogin, User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
APPLE_KEY = ec.generate_private_key(ec.SECP256R1())
APPLE_PEM = APPLE_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
IDS = {"google": "abc-google-client", "microsoft": "abc-ms-client", "apple": "com.abc.receipts"}
ISS = {
    "google": "https://accounts.google.com",
    "microsoft": f"https://login.microsoftonline.com/{MSA_TENANT}/v2.0",
    "apple": "https://appleid.apple.com",
}


class Provider:
    """Plays the provider's token endpoint: hands back an ID token for any code."""

    def __init__(self, monkeypatch):
        self.claims: dict = {}
        self.key = KEY
        self.requests: list[dict] = []
        monkeypatch.setattr("app.api.social.httpx.post", self.token_endpoint)
        monkeypatch.setattr("app.api.social._signing_key", lambda p, t: KEY.public_key())

    def token_endpoint(self, url, data, timeout):
        self.requests.append({"url": url, **data})
        token = jwt.encode(self.claims, self.key, algorithm="RS256")
        return httpx.Response(200, json={"id_token": token}, request=httpx.Request("POST", url))


@pytest.fixture
def idp(monkeypatch):
    s = get_settings()
    for k, v in {
        "google_client_id": IDS["google"],
        "google_client_secret": "g-secret",
        "microsoft_client_id": IDS["microsoft"],
        "microsoft_client_secret": "m-secret",
        "apple_client_id": IDS["apple"],
        "apple_team_id": "ABCTEAM123",
        "apple_key_id": "ABCKEY1234",
        "apple_private_key": APPLE_PEM.replace("\n", "\\n"),  # as pasted into one env var
        "cookie_secure": True,
    }.items():
        monkeypatch.setattr(s, k, v)
    return Provider(monkeypatch)


def new_client():
    from app.main import app

    return TestClient(app, base_url="https://abc.example")


def sign_in(c, idp, provider="google", form_user=None, **claims):
    start = c.get(f"/api/auth/{provider}/start", follow_redirects=False)
    assert start.status_code == 303
    q = parse_qs(urlparse(start.headers["location"]).query)
    assert q["redirect_uri"] == [f"https://abc.example/api/auth/{provider}/callback"]
    now = int(time.time())
    idp.claims = {
        "iss": ISS[provider],
        "aud": IDS[provider],
        "sub": f"{provider}-123",
        "email": "xyz@example.com",
        "email_verified": True,
        "name": "XYZ User",
        "nonce": q["nonce"][0],
        "iat": now,
        "exp": now + 3600,
        **({"tid": MSA_TENANT} if provider == "microsoft" else {}),
        **claims,
    }
    idp.claims = {k: v for k, v in idp.claims.items() if v is not None}
    answer = {"code": "abc-code", "state": q["state"][0]}
    if provider == "apple":
        assert q["response_mode"] == ["form_post"]
        if form_user:
            answer["user"] = form_user
        return c.post(f"/api/auth/{provider}/callback", data=answer, follow_redirects=False)
    return c.get(f"/api/auth/{provider}/callback", params=answer, follow_redirects=False)


def error_of(resp) -> str | None:
    assert resp.status_code == 303, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query).get("auth_error", [None])[0]


@pytest.mark.parametrize("provider", ["google", "microsoft", "apple"])
def test_new_account_from_each_provider(client, idp, provider):
    c = new_client()
    assert error_of(sign_in(c, idp, provider)) is None
    me = c.get("/api/auth/me").json()
    assert me["authenticated"] and me["email"] == "xyz@example.com"
    assert c.get("/api/expenses").status_code == 200
    # Next time, the same account (matched by the provider's id, not the email).
    c2 = new_client()
    assert error_of(sign_in(c2, idp, provider, email="changed@example.com")) is None
    assert c2.get("/api/auth/me").json()["email"] == "xyz@example.com"


def test_pkce_for_google_and_microsoft(client, idp):
    sign_in(new_client(), idp, "google")
    sign_in(new_client(), idp, "microsoft")
    assert all(len(r["code_verifier"]) > 40 for r in idp.requests)


def test_apple_client_secret_is_a_signed_jwt_and_name_comes_from_the_form(client, idp):
    c = new_client()
    form_user = '{"name": {"firstName": "XYZ", "lastName": "Person"}}'
    resp = sign_in(c, idp, "apple", form_user=form_user, name=None, email_verified="true")
    assert error_of(resp) is None
    assert c.get("/api/auth/me").json()["name"] == "XYZ Person"
    secret = idp.requests[0]["client_secret"]
    claims = jwt.decode(
        secret, APPLE_KEY.public_key(), algorithms=["ES256"], audience="https://appleid.apple.com"
    )
    assert claims["iss"] == "ABCTEAM123" and claims["sub"] == IDS["apple"]
    assert jwt.get_unverified_header(secret)["kid"] == "ABCKEY1234"


def test_existing_account_with_that_email_is_used(client, idp):
    c = new_client()
    assert error_of(sign_in(c, idp, email=TEST_EMAIL.upper())) is None
    assert c.get("/api/auth/me").json()["name"] == "ABC User"
    login = {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    assert new_client().post("/api/auth/login", json=login).status_code == 200


@pytest.mark.parametrize(
    "provider, change, message",
    [
        ("google", {"aud": "someone-elses-client"}, "didn't go through"),
        ("google", {"iss": "https://evil.example"}, "didn't go through"),
        ("google", {"exp": int(time.time()) - 3600}, "didn't go through"),
        ("google", {"nonce": "replayed"}, "didn't go through"),
        ("google", {"email_verified": False}, "confirmed email"),
        ("apple", {"email_verified": "false"}, "confirmed email"),
        # A token from one tenant claiming to be from another.
        ("microsoft", {"tid": "abc-other-tenant"}, "didn't go through"),
        # Work accounts' emails are set by their admin: not trusted unless verified.
        (
            "microsoft",
            {"tid": "abc-work", "iss": "https://login.microsoftonline.com/abc-work/v2.0"},
            "confirmed email",
        ),
    ],
)
def test_bad_tokens_are_refused(client, idp, provider, change, message):
    c = new_client()
    assert message in error_of(sign_in(c, idp, provider, **change))
    assert not c.get("/api/auth/me").json()["authenticated"]


def test_verified_work_account_is_accepted(client, idp):
    c = new_client()
    work = {"tid": "abc-work", "iss": "https://login.microsoftonline.com/abc-work/v2.0"}
    assert error_of(sign_in(c, idp, "microsoft", xms_edov=True, **work)) is None


def test_forged_signature_is_refused(client, idp):
    idp.key = OTHER_KEY
    c = new_client()
    assert "didn't go through" in error_of(sign_in(c, idp))
    assert not c.get("/api/auth/me").json()["authenticated"]


def test_state_must_match_this_browser(client, idp):
    c = new_client()
    start = c.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    resp = new_client().get(
        "/api/auth/google/callback", params={"code": "x", "state": state}, follow_redirects=False
    )
    assert "try again" in error_of(resp)
    resp = c.get(
        "/api/auth/google/callback", params={"code": "x", "state": "nope"}, follow_redirects=False
    )
    assert "try again" in error_of(resp)
    assert idp.requests == []


def test_provider_takes_back_an_address_someone_squatted(client, idp):
    squatter = new_client()
    body = {"name": "Not Me", "email": "xyz@example.com", "password": "squatter password"}
    assert squatter.post("/api/auth/signup", json=body).status_code == 201
    owner = new_client()
    assert error_of(sign_in(owner, idp)) is None
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "xyz@example.com"))
        assert user.password_hash is None and user.email_verified_at is not None
        assert db.scalar(select(SocialLogin.provider).where(SocialLogin.user_id == user.id))
    login = {"email": "xyz@example.com", "password": "squatter password"}
    resp = new_client().post("/api/auth/login", json=login)
    assert resp.status_code == 401 and "Google, Microsoft or Apple" in resp.json()["detail"]


def test_signup_off_still_lets_existing_people_in(client, idp, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_signup", False)
    assert "turned off" in error_of(sign_in(new_client(), idp))
    assert error_of(sign_in(new_client(), idp, email=TEST_EMAIL)) is None


def test_cancelling_returns_quietly(client, idp):
    resp = new_client().get(
        "/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert "cancelled" in error_of(resp)


def test_only_configured_providers_are_offered(client, monkeypatch):
    assert client.get("/api/auth/me").json()["social_providers"] == []
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/nope/start", follow_redirects=False).status_code == 404
    monkeypatch.setattr(get_settings(), "microsoft_client_id", "x")
    monkeypatch.setattr(get_settings(), "microsoft_client_secret", "y")
    assert client.get("/api/auth/me").json()["social_providers"] == ["microsoft"]


def test_password_guessing_is_limited_per_account(client):
    for _ in range(10):
        new_client().post("/api/auth/login", json={"email": TEST_EMAIL, "password": "guess"})
    good = {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    assert new_client().post("/api/auth/login", json=good).status_code == 429


def test_connecting_a_provider_to_an_existing_account_sends_an_alert(client, idp, outbox):
    outbox.clear()
    assert error_of(sign_in(new_client(), idp, email=TEST_EMAIL)) is None
    assert outbox[-1]["to"] == TEST_EMAIL and "Google sign-in was added" in outbox[-1]["subject"]
    # Not again on later sign-ins, and not for brand-new accounts.
    outbox.clear()
    sign_in(new_client(), idp, email=TEST_EMAIL)
    sign_in(new_client(), idp, "microsoft", email="new@example.com")
    assert outbox == []


def test_keep_me_signed_in_carries_through_the_provider(client, idp):
    c = new_client()
    start = c.get("/api/auth/google/start?remember=true", follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    now = int(time.time())
    idp.claims = {
        "iss": ISS["google"],
        "aud": IDS["google"],
        "sub": "g-9",
        "nonce": q["nonce"][0],
        "email": "keep@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 60,
    }
    resp = c.get(
        "/api/auth/google/callback",
        params={"code": "x", "state": q["state"][0]},
        follow_redirects=False,
    )
    session_cookie = [h for h in resp.headers.get_list("set-cookie") if h.startswith("session=")]
    assert "Max-Age=2592000" in session_cookie[0]
    assert "Max-Age" not in next(
        h
        for h in sign_in(new_client(), idp).headers.get_list("set-cookie")
        if h.startswith("session=")
    )
