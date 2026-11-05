"""Emailed links for confirming an address and resetting a password."""

import hashlib
import html
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.mailer import EmailError, send_email
from app.models import AuthToken, User

log = logging.getLogger(__name__)

VERIFY, RESET = "verify", "reset"
# A new link for the same thing isn't sent more often than this, however often it's asked for.
RESEND_COOLDOWN = timedelta(seconds=60)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _fingerprint(user: User) -> str:
    return _hash(user.password_hash or "")[:16]


def _now() -> datetime:
    return datetime.now(UTC)


def issue_link(db: Session, user: User, purpose: str, ttl: timedelta) -> str | None:
    """A fresh single-use token, voiding earlier ones; None if one was sent moments ago."""
    recent = db.scalar(
        select(AuthToken.id).where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.created_at > _now() - RESEND_COOLDOWN,
        )
    )
    if recent:
        return None
    db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash(raw),
            password_fingerprint=_fingerprint(user),
            expires_at=_now() + ttl,
            created_at=_now(),
        )
    )
    db.flush()
    return raw


def use_link(db: Session, raw: str, purpose: str) -> User | None:
    """The account a still-valid token belongs to, marking the token used; None otherwise."""
    if not raw or len(raw) > 100:
        return None
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == _hash(raw), AuthToken.purpose == purpose)
        .with_for_update()
    )
    if token is None or token.used_at is not None or token.expires_at <= _now():
        return None
    user = db.get(User, token.user_id)
    if user is None or token.password_fingerprint != _fingerprint(user):
        return None
    token.used_at = _now()
    return user


def mark_verified(user: User) -> None:
    if user.email_verified_at is None:
        user.email_verified_at = _now()


# --- The emails -----------------------------------------------------------------------------


def _layout(title: str, intro: str, button: str, url: str, outro: str) -> str:
    e = html.escape
    return f"""<!doctype html><html><body style="margin:0;background:#f6f5f2;font-family:Inter,
Helvetica,Arial,sans-serif;color:#1f2a27"><table role="presentation" width="100%"
cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="100%" style="max-width:480px;background:#ffffff;
border-radius:14px;padding:32px" cellpadding="0" cellspacing="0"><tr><td>
<p style="margin:0 0 20px;font-weight:600;font-size:16px;color:#3f685d">Receipts</p>
<h1 style="margin:0 0 12px;font-size:20px;font-weight:600">{e(title)}</h1>
<p style="margin:0 0 24px;font-size:14px;line-height:1.6;color:#4b5552">{e(intro)}</p>
<a href="{e(url)}" style="display:inline-block;background:#3f685d;color:#ffffff;
text-decoration:none;font-weight:600;font-size:14px;padding:12px 20px;border-radius:10px">
{e(button)}</a>
<p style="margin:24px 0 0;font-size:12px;line-height:1.6;color:#7a8380">{e(outro)}<br><br>
If the button doesn't work, paste this into your browser:<br>
<span style="word-break:break-all">{e(url)}</span></p>
</td></tr></table></td></tr></table></body></html>"""


def send_verification(settings: Settings, user: User, raw: str) -> None:
    url = f"{settings.public_url}/verify-email?token={raw}"
    hours = settings.verify_link_hours
    intro = f"Hi {user.name}, confirm this is your email address to finish creating your account."
    outro = f"The link works once and expires in {hours} hours. If you didn't sign up, ignore this."
    send_email(
        settings,
        user.email or "",
        "Confirm your email for Receipts",
        f"{intro}\n\nConfirm your email: {url}\n\n{outro}\n",
        _layout("Confirm your email", intro, "Confirm email", url, outro),
    )


def send_reset(settings: Settings, user: User, raw: str) -> None:
    url = f"{settings.public_url}/reset-password?token={raw}"
    minutes = settings.reset_link_minutes
    intro = f"Hi {user.name}, someone asked to reset the password for your Receipts account."
    outro = (
        f"The link works once and expires in {minutes} minutes. If it wasn't you, ignore this; "
        "your password stays the same."
    )
    send_email(
        settings,
        user.email or "",
        "Reset your Receipts password",
        f"{intro}\n\nChoose a new password: {url}\n\n{outro}\n",
        _layout("Reset your password", intro, "Choose a new password", url, outro),
    )


def send_notice(settings: Settings, user: User, subject: str, title: str, intro: str) -> None:
    """A heads-up about a change to the account. Best effort: a failed send is only logged."""
    if not settings.email_enabled or not user.email:
        return
    url = f"{settings.public_url}/"
    outro = (
        "If this was you, there's nothing to do. If it wasn't, open the app and use "
        "Forgot password? right away to choose a new one; that signs everyone else out."
    )
    try:
        send_email(
            settings,
            user.email,
            subject,
            f"{intro}\n\n{outro}\n\n{url}\n",
            _layout(title, intro, "Open Receipts", url, outro),
        )
    except EmailError:
        log.warning("couldn't send the '%s' notice to user %s", subject, user.id)


def notify_password_changed(settings: Settings, user: User) -> None:
    send_notice(
        settings,
        user,
        "Your Receipts password was changed",
        "Your password was changed",
        f"Hi {user.name}, the password for your Receipts account was just changed, and every "
        "other device was signed out.",
    )


def notify_sign_in_added(settings: Settings, user: User, provider: str) -> None:
    send_notice(
        settings,
        user,
        f"{provider} sign-in was added to your Receipts account",
        f"{provider} sign-in added",
        f"Hi {user.name}, your Receipts account can now be opened with {provider}.",
    )


def notify_account_deleted(settings: Settings, email: str | None, name: str) -> None:
    """The last email we send: a receipt for the deletion. Best effort, like the other notices."""
    if not settings.email_enabled or not email:
        return
    intro = (
        f"Hi {name}, your Receipts account was closed and everything in it was deleted: "
        "your receipts and their photos, expenses, categories, budgets and sign-in methods."
    )
    outro = (
        "This can't be undone, and we won't email you again. If you didn't do this, someone "
        "had your password; change it anywhere else you used it."
    )
    url = f"{settings.public_url}/"
    try:
        send_email(
            settings,
            email,
            "Your Receipts account was deleted",
            f"{intro}\n\n{outro}\n",
            _layout("Your account was deleted", intro, "Open Receipts", url, outro),
        )
    except EmailError:
        log.warning("couldn't send the account-deleted notice")
