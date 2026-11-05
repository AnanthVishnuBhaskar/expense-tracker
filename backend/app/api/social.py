"""Sign in or sign up with Google, Microsoft or Apple (OpenID Connect, authorization code flow).

Every sign-in carries a random state (tied to this browser by a signed cookie), a nonce (tied
to the ID token) and, where the provider supports it, PKCE. The ID token's signature, issuer,
audience, expiry and nonce are all checked against the provider's published keys.
"""

import base64
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.accounts import mark_verified, notify_sign_in_added
from app.api.auth import _start_session, login_limiter
from app.config import Settings, get_settings
from app.deps import DB
from app.ledger import create_user
from app.models import SocialLogin, User
from app.security import _sign, client_key

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)

STATE_TTL = 10 * 60
# Personal Microsoft accounts (Outlook.com, Hotmail, Live) all sign in through this tenant.
MSA_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"


class SignInError(Exception):
    """Shown to the person on the sign-in page."""


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    jwks_url: str
    scope: str
    pkce: bool
    # Apple posts its answer back (form_post), which needs a cookie that survives a cross-site POST.
    form_post: bool
    issuer_ok: Callable[[dict], bool]
    client_id: Callable[[Settings], str]
    client_secret: Callable[[Settings], str]


def _apple_secret(s: Settings) -> str:
    """Apple wants a short-lived JWT signed with your key instead of a fixed secret."""
    now = int(time.time())
    key = s.apple_private_key.replace("\\n", "\n")
    return jwt.encode(
        {
            "iss": s.apple_team_id,
            "iat": now,
            "exp": now + 300,
            "aud": "https://appleid.apple.com",
            "sub": s.apple_client_id,
        },
        key,
        algorithm="ES256",
        headers={"kid": s.apple_key_id},
    )


PROVIDERS = {
    p.name: p
    for p in (
        Provider(
            name="google",
            label="Google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            jwks_url="https://www.googleapis.com/oauth2/v3/certs",
            scope="openid email profile",
            pkce=True,
            form_post=False,
            issuer_ok=lambda c: (
                c.get("iss") in {"accounts.google.com", "https://accounts.google.com"}
            ),
            client_id=lambda s: s.google_client_id,
            client_secret=lambda s: s.google_client_secret,
        ),
        Provider(
            name="microsoft",
            label="Microsoft",
            authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            jwks_url="https://login.microsoftonline.com/common/discovery/v2.0/keys",
            scope="openid email profile",
            pkce=True,
            form_post=False,
            # Each tenant has its own issuer; it must be the one the token says it's from.
            issuer_ok=lambda c: (
                bool(c.get("tid"))
                and c.get("iss") == f"https://login.microsoftonline.com/{c['tid']}/v2.0"
            ),
            client_id=lambda s: s.microsoft_client_id,
            client_secret=lambda s: s.microsoft_client_secret,
        ),
        Provider(
            name="apple",
            label="Apple",
            authorize_url="https://appleid.apple.com/auth/authorize",
            token_url="https://appleid.apple.com/auth/token",
            jwks_url="https://appleid.apple.com/auth/keys",
            scope="name email",
            pkce=False,
            form_post=True,
            issuer_ok=lambda c: c.get("iss") == "https://appleid.apple.com",
            client_id=lambda s: s.apple_client_id,
            client_secret=_apple_secret,
        ),
    )
}

# Each provider's signing keys, fetched when first needed and cached (they rotate).
_jwks: dict[str, jwt.PyJWKClient] = {}


def _signing_key(provider: Provider, id_token: str):
    client = _jwks.setdefault(
        provider.name, jwt.PyJWKClient(provider.jwks_url, cache_keys=True, lifespan=6 * 3600)
    )
    return client.get_signing_key_from_jwt(id_token).key


def _provider(name: str) -> Provider:
    if name not in PROVIDERS or name not in get_settings().social_providers:
        raise HTTPException(404, "That sign-in option isn't set up")
    return PROVIDERS[name]


def _redirect_uri(p: Provider) -> str:
    return f"{get_settings().public_url}/api/auth/{p.name}/callback"


def _cookie(p: Provider) -> str:
    return f"oauth_{p.name}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _back(p: Provider, error: str | None = None) -> RedirectResponse:
    target = "/" if error is None else "/?" + urlencode({"auth_error": error})
    resp = RedirectResponse(target, status_code=303)
    resp.delete_cookie(_cookie(p), path=f"/api/auth/{p.name}")
    return resp


@router.get("/{name}/start")
def start(name: str, remember: bool = False) -> RedirectResponse:
    p, settings = _provider(name), get_settings()
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    # State, nonce, PKCE verifier and "keep me signed in" ride in a signed, short-lived cookie.
    payload = f"{state}.{nonce}.{verifier}.{int(remember)}.{int(time.time()) + STATE_TTL}"
    query = {
        "client_id": p.client_id(settings),
        "redirect_uri": _redirect_uri(p),
        "response_type": "code",
        "scope": p.scope,
        "state": state,
        "nonce": nonce,
    }
    if p.pkce:
        query |= {
            "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    if p.form_post:
        query["response_mode"] = "form_post"
    resp = RedirectResponse(f"{p.authorize_url}?{urlencode(query)}", status_code=303)
    resp.set_cookie(
        _cookie(p),
        f"{payload}.{_sign(settings.session_secret, payload)}",
        max_age=STATE_TTL,
        httponly=True,
        # It has to come back with the provider's redirect (a cross-site GET, or Apple's POST).
        secure=settings.cookie_secure or p.form_post,
        samesite="none" if p.form_post else "lax",
        path=f"/api/auth/{p.name}",
    )
    return resp


def _read_state(cookie: str | None) -> tuple[str, str, str, bool]:
    retry = "Your sign-in took too long or was started elsewhere. Please try again."
    parts = (cookie or "").split(".")
    if len(parts) != 6:
        raise SignInError(retry)
    state, nonce, verifier, remember, expires, sig = parts
    payload = f"{state}.{nonce}.{verifier}.{remember}.{expires}"
    if not secrets.compare_digest(sig, _sign(get_settings().session_secret, payload)):
        raise SignInError(retry)
    if not expires.isdigit() or int(expires) < time.time():
        raise SignInError(retry)
    return state, nonce, verifier, remember == "1"


def _claims(p: Provider, code: str, verifier: str, nonce: str) -> dict:
    settings = get_settings()
    failed = f"{p.label} sign-in didn't go through. Please try again."
    data = {
        "code": code,
        "client_id": p.client_id(settings),
        "client_secret": p.client_secret(settings),
        "redirect_uri": _redirect_uri(p),
        "grant_type": "authorization_code",
    }
    if p.pkce:
        data["code_verifier"] = verifier
    try:
        resp = httpx.post(p.token_url, data=data, timeout=15)
        resp.raise_for_status()
        id_token = resp.json()["id_token"]
        claims = jwt.decode(
            id_token,
            _signing_key(p, id_token),
            algorithms=["RS256"],
            audience=p.client_id(settings),
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError) as e:
        detail = e.response.text[:300] if isinstance(e, httpx.HTTPStatusError) else repr(e)
        log.error("%s sign-in failed: %s", p.label, detail)
        raise SignInError(failed) from e
    if not p.issuer_ok(claims) or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SignInError(failed)
    return claims


def _verified_email(p: Provider, claims: dict) -> str:
    """The email the provider vouches for; anything less isn't used to find an account."""
    email = str(claims.get("email") or "").strip().lower()
    if p.name == "microsoft":
        # Work and school accounts let admins set any email, so only trust it when Microsoft
        # says the domain is verified, or for personal accounts (Outlook.com, Hotmail, Live).
        ok = claims.get("tid") == MSA_TENANT or claims.get("xms_edov") in (True, "true", "1")
    else:
        ok = claims.get("email_verified") in (True, "true")
    if not (email and ok):
        raise SignInError(
            f"Your {p.label} account needs a confirmed email address. "
            "Try another option, or sign up with your email."
        )
    return email


def _name(p: Provider, claims: dict, form_user: str | None, email: str) -> str:
    name = claims.get("name") or claims.get("given_name")
    if not name and form_user:
        # Apple sends the name only once, alongside the very first sign-in.
        try:
            n = json.loads(form_user).get("name") or {}
            name = " ".join(x for x in (n.get("firstName"), n.get("lastName")) if x)
        except (ValueError, AttributeError):
            name = None
    return str(name or email.split("@")[0])[:120]


def _callback(name: str, request: Request, db: DB, params: dict[str, str]) -> RedirectResponse:
    p, settings = _provider(name), get_settings()
    try:
        login_limiter.hit(client_key(request))
    except HTTPException:
        return _back(p, "Too many sign-in attempts. Please wait a few minutes.")
    if params.get("error"):
        cancelled = params["error"] in ("access_denied", "user_cancelled_authorize")
        return _back(p, f"{p.label} sign-in was cancelled." if cancelled else None)
    try:
        state, nonce, verifier, remember = _read_state(request.cookies.get(_cookie(p)))
        if not secrets.compare_digest(params.get("state", ""), state):
            raise SignInError("Your sign-in was started elsewhere. Please try again.")
        claims = _claims(p, params.get("code", ""), verifier, nonce)
        email = _verified_email(p, claims)
    except SignInError as e:
        return _back(p, str(e))

    subject = str(claims["sub"])
    link = db.scalar(
        select(SocialLogin).where(SocialLogin.provider == p.name, SocialLogin.subject == subject)
    )
    added_to_existing = False
    if link is not None:
        user = db.get(User, link.user_id)
    else:
        user = db.scalar(select(User).where(User.email == email))
        added_to_existing = user is not None
        if user is not None:
            if user.email_verified_at is None:
                # Someone may have signed up with this address and a password without owning
                # it. The provider has just proved who does, so that password goes.
                user.password_hash = None
                user.session_version += 1
        elif not settings.allow_signup:
            return _back(p, "New accounts are turned off.")
        else:
            user = create_user(
                db,
                name=_name(p, claims, params.get("user"), email),
                email=email,
                password_hash=None,
            )
        db.add(SocialLogin(user_id=user.id, provider=p.name, subject=subject, email=email))
    assert user is not None
    mark_verified(user)
    db.commit()
    if link is None and added_to_existing:
        notify_sign_in_added(settings, user, p.label)
    resp = _back(p)
    _start_session(resp, user, remember=remember)
    return resp


@router.get("/{name}/callback")
def callback_get(name: str, request: Request, db: DB) -> RedirectResponse:
    return _callback(name, request, db, dict(request.query_params))


@router.post("/{name}/callback")
def callback_post(
    name: str,
    request: Request,
    db: DB,
    code: str = Form(""),
    state: str = Form(""),
    error: str = Form(""),
    user: str = Form(""),
) -> RedirectResponse:
    """Apple posts its answer back instead of redirecting with it in the URL."""
    form = {"code": code, "state": state, "error": error, "user": user}
    return _callback(name, request, db, {k: v for k, v in form.items() if v})
