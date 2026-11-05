import re

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, current_user
from app.ledger import create_user
from app.models import User
from app.security import (
    COOKIE,
    RateLimiter,
    client_key,
    hash_password,
    sign_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

login_limiter = RateLimiter(get_settings().login_attempts_per_15_min, 15 * 60)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Checked when the email is unknown, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class SignupIn(LoginIn):
    name: str = Field(max_length=120)


class AuthStatus(BaseModel):
    authenticated: bool
    name: str | None = None
    email: str | None = None
    signup_open: bool


def _status(user: User | None) -> AuthStatus:
    return AuthStatus(
        authenticated=user is not None,
        name=user.name if user else None,
        email=user.email if user else None,
        signup_open=get_settings().allow_signup,
    )


def _start_session(response: Response, user: User) -> None:
    settings = get_settings()
    ttl = settings.session_ttl_hours * 3600
    response.set_cookie(
        COOKIE,
        sign_session(settings.session_secret, user.id, ttl),
        max_age=ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.get("/me", response_model=AuthStatus)
def me(request: Request, db: DB) -> AuthStatus:
    try:
        return _status(current_user(request, db))
    except HTTPException:
        return _status(None)


@router.post("/signup", response_model=AuthStatus, status_code=201)
def signup(body: SignupIn, request: Request, response: Response, db: DB) -> AuthStatus:
    if not get_settings().allow_signup:
        raise HTTPException(403, "New accounts are turned off")
    login_limiter.hit(client_key(request))
    email, name = body.email.strip().lower(), body.name.strip()
    if not name:
        raise HTTPException(422, "Please enter your name")
    if not _EMAIL.match(email):
        raise HTTPException(422, "That email doesn't look right")
    if len(body.password) < 8:
        raise HTTPException(422, "Use at least 8 characters for your password")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "There's already an account with that email. Try signing in.")

    hashed = hash_password(body.password)
    # The first account takes over whatever was recorded before accounts existed.
    legacy = None
    if not db.scalar(select(User.id).where(User.email.is_not(None)).limit(1)):
        legacy = db.scalar(select(User).where(User.email.is_(None)).order_by(User.id).limit(1))
    if legacy:
        legacy.name, legacy.email, legacy.password_hash = name, email, hashed
        user = legacy
    else:
        user = create_user(db, name=name, email=email, password_hash=hashed)
    db.commit()
    _start_session(response, user)
    return _status(user)


@router.post("/login", response_model=AuthStatus)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> AuthStatus:
    login_limiter.hit(client_key(request))
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    ok = verify_password(
        body.password, user.password_hash if user and user.password_hash else _DUMMY_HASH
    )
    if not (user and ok):
        raise HTTPException(401, "That email and password don't match")
    _start_session(response, user)
    return _status(user)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
