import logging
import re
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.accounts import (
    RESET,
    VERIFY,
    issue_link,
    mark_verified,
    notify_account_deleted,
    notify_password_changed,
    send_reset,
    send_verification,
    use_link,
)
from app.config import get_settings
from app.deps import DB, CurrentUser, current_user
from app.ledger import create_user
from app.mailer import EmailError
from app.models import Receipt, User
from app.security import (
    COOKIE,
    RateLimiter,
    client_key,
    hash_password,
    session_user,
    sign_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)

login_limiter = RateLimiter(get_settings().login_attempts_per_15_min, 15 * 60)
# Per account too, so guessing one person's password from many addresses gets nowhere.
account_limiter = RateLimiter(get_settings().login_attempts_per_15_min, 15 * 60)
# Every emailed link costs a send and lands in someone's inbox, so they share one budget.
email_limiter = RateLimiter(get_settings().emails_per_hour, 60 * 60)
EMAIL_FAILED = "We couldn't send the email just now. Please try again in a minute."
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Checked when the email is unknown, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    remember: bool = False


class SignupIn(LoginIn):
    name: str = Field(max_length=120)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class TokenIn(BaseModel):
    token: str = Field(max_length=100)


class ResetIn(TokenIn):
    password: str = Field(max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class DeleteAccountIn(BaseModel):
    # The account's email (or DELETE for an account without one), typed out by hand.
    confirm: str = Field(max_length=254)
    # Required when the account has a password.
    password: str = Field(default="", max_length=200)


class AuthStatus(BaseModel):
    authenticated: bool
    name: str | None = None
    email: str | None = None
    signup_open: bool
    # Sign-up waits for the emailed link, and "Forgot password?" is offered.
    email_enabled: bool = False
    # Which of "google", "microsoft", "apple" are offered.
    social_providers: list[str] = []
    # False for accounts that only sign in with Google, Microsoft or Apple.
    has_password: bool = False
    # Set after sign-up when the account is waiting for its email to be confirmed.
    verification_sent_to: str | None = None


def _status(user: User | None, *, verification_sent_to: str | None = None) -> AuthStatus:
    settings = get_settings()
    return AuthStatus(
        authenticated=user is not None,
        name=user.name if user else None,
        email=user.email if user else None,
        signup_open=settings.allow_signup,
        email_enabled=settings.email_enabled,
        social_providers=settings.social_providers,
        has_password=bool(user and user.password_hash),
        verification_sent_to=verification_sent_to,
    )


def _check_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(422, "Use at least 8 characters for your password")


def _email_link(db: DB, user: User, purpose: str) -> None:
    """Email a confirm or reset link, committing only once the email has gone out."""
    settings = get_settings()
    if purpose == VERIFY:
        raw = issue_link(db, user, VERIFY, timedelta(hours=settings.verify_link_hours))
    else:
        raw = issue_link(db, user, RESET, timedelta(minutes=settings.reset_link_minutes))
    if raw is None:  # one went out moments ago
        db.commit()
        return
    try:
        (send_verification if purpose == VERIFY else send_reset)(settings, user, raw)
    except EmailError:
        db.rollback()
        raise HTTPException(503, EMAIL_FAILED) from None
    db.commit()


def _start_session(response: Response, user: User, *, remember: bool = True) -> None:
    """Sign this browser in. Remembered sessions survive closing the browser; others don't."""
    settings = get_settings()
    hours = settings.session_ttl_hours if remember else settings.session_short_hours
    ttl = hours * 3600
    response.set_cookie(
        COOKIE,
        sign_session(settings.session_secret, user.id, user.session_version, ttl, remember),
        max_age=ttl if remember else None,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def _remembered(request: Request) -> bool:
    session = session_user(get_settings().session_secret, request.cookies.get(COOKIE))
    return bool(session and session[2])


@router.get("/me", response_model=AuthStatus)
def me(request: Request, db: DB) -> AuthStatus:
    try:
        return _status(current_user(request, db))
    except HTTPException:
        return _status(None)


@router.post("/signup", response_model=AuthStatus, status_code=201)
def signup(body: SignupIn, request: Request, db: DB) -> AuthStatus:
    settings = get_settings()
    if not settings.allow_signup:
        raise HTTPException(403, "New accounts are turned off")
    if not settings.email_enabled:
        # Every email sign-up is confirmed by email; without a way to send, only social sign-in.
        raise HTTPException(403, "Signing up with email isn't available yet")
    login_limiter.hit(client_key(request))
    email, name = body.email.strip().lower(), body.name.strip()
    if not name:
        raise HTTPException(422, "Please enter your name")
    if not _EMAIL.match(email):
        raise HTTPException(422, "That email doesn't look right")
    _check_password(body.password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(
            409, "There's already an account with that email. Sign in, or reset your password."
        )

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

    # Nothing is saved unless the confirmation email goes out, so a failed send can be retried.
    email_limiter.hit(client_key(request))
    db.flush()
    _email_link(db, user, VERIFY)
    return _status(None, verification_sent_to=email)


@router.post("/login", response_model=AuthStatus)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> AuthStatus:
    login_limiter.hit(client_key(request))
    email = body.email.strip().lower()
    account_limiter.hit(email)
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(
        body.password, user.password_hash if user and user.password_hash else _DUMMY_HASH
    )
    if not (user and ok):
        if user and user.password_hash is None:
            raise HTTPException(
                401,
                "This account signs in with Google, Microsoft or Apple. Use that button, "
                "or reset your password to add one.",
            )
        raise HTTPException(401, "That email and password don't match")
    if user.email_verified_at is None:
        # Only reached with the right password, so this reveals nothing to a stranger.
        if not get_settings().email_enabled:
            raise HTTPException(403, "Please confirm your email first.")
        email_limiter.hit(client_key(request))
        _email_link(db, user, VERIFY)
        raise HTTPException(
            403, f"Please confirm your email first. We've sent a link to {user.email}."
        )
    _start_session(response, user, remember=body.remember)
    return _status(user)


@router.post("/resend-verification", status_code=204)
def resend_verification(body: EmailIn, request: Request, db: DB) -> None:
    if not get_settings().email_enabled:
        raise HTTPException(404, "Email isn't set up")
    email_limiter.hit(client_key(request))
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # Same answer whether or not the account exists, so this can't be used to probe emails.
    if user and user.email_verified_at is None:
        _email_link(db, user, VERIFY)


@router.post("/verify-email", response_model=AuthStatus)
def verify_email(body: TokenIn, request: Request, response: Response, db: DB) -> AuthStatus:
    login_limiter.hit(client_key(request))
    user = use_link(db, body.token, VERIFY)
    if user is None:
        db.rollback()
        raise HTTPException(
            400, "This link has expired or was already used. Sign in to get a new one."
        )
    mark_verified(user)
    db.commit()
    _start_session(response, user, remember=False)
    return _status(user)


@router.post("/forgot-password", status_code=204)
def forgot_password(body: EmailIn, request: Request, db: DB) -> None:
    if not get_settings().email_enabled:
        raise HTTPException(404, "Email isn't set up")
    email_limiter.hit(client_key(request))
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # Same answer whether or not the account exists.
    if user:
        _email_link(db, user, RESET)


@router.post("/reset-password", response_model=AuthStatus)
def reset_password(body: ResetIn, request: Request, response: Response, db: DB) -> AuthStatus:
    login_limiter.hit(client_key(request))
    _check_password(body.password)
    user = use_link(db, body.token, RESET)
    if user is None:
        db.rollback()
        raise HTTPException(400, "This link has expired or was already used. Ask for a new one.")
    if user.password_hash and verify_password(body.password, user.password_hash):
        db.rollback()
        raise HTTPException(422, "Choose a password you haven't used for this account")
    user.password_hash = hash_password(body.password)
    # Following the link proves the inbox is theirs; and every other session is signed out.
    mark_verified(user)
    user.session_version += 1
    db.commit()
    _start_session(response, user, remember=False)
    notify_password_changed(get_settings(), user)
    return _status(user)


@router.post("/change-password", response_model=AuthStatus)
def change_password(
    body: ChangePasswordIn, request: Request, response: Response, db: DB, user: CurrentUser
) -> AuthStatus:
    login_limiter.hit(client_key(request))
    account_limiter.hit(user.email or str(user.id))
    if not user.password_hash:
        raise HTTPException(
            400, "This account has no password yet. Use Forgot password? on the sign-in page."
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Your current password isn't right")
    _check_password(body.new_password)
    if body.new_password == body.current_password:
        raise HTTPException(422, "Choose a password you haven't used for this account")
    user.password_hash = hash_password(body.new_password)
    # Everywhere else is signed out; this browser gets a fresh session.
    user.session_version += 1
    db.commit()
    _start_session(response, user, remember=_remembered(request))
    notify_password_changed(get_settings(), user)
    return _status(user)


@router.post("/delete-account", status_code=204)
def delete_account(
    body: DeleteAccountIn, request: Request, response: Response, db: DB, user: CurrentUser
) -> None:
    """Close the account for good: every row it owns and every receipt photo."""
    login_limiter.hit(client_key(request))
    account_limiter.hit(user.email or str(user.id))
    if user.password_hash and not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "Your password isn't right")
    expected = user.email or "DELETE"
    if body.confirm.strip().lower() != expected.lower():
        raise HTTPException(422, f"Type {expected} to confirm")
    settings = get_settings()
    photos = list(db.scalars(select(Receipt.image_path).where(Receipt.user_id == user.id)))
    email, name, user_id = user.email, user.name, user.id
    # Every table that holds the user's data references users.id with ON DELETE CASCADE.
    db.delete(user)
    db.commit()
    # Photos go once the rows are gone, so a failed commit never leaves receipts without images.
    for rel in photos:
        try:
            (settings.upload_dir / rel).unlink(missing_ok=True)
        except OSError:
            log.warning("couldn't delete a receipt photo of deleted user %s", user_id)
    response.delete_cookie(COOKIE, path="/")
    log.info("user %s deleted their account (%d photos)", user_id, len(photos))
    notify_account_deleted(settings, email, name)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
