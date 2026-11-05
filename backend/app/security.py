"""Security helpers: card-number masking, rate limiting, response headers and login sessions."""

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.pipeline.schemas import ReceiptExtraction

# --- Card numbers -------------------------------------------------------------------------

# 13-19 digits, optionally separated by single spaces or dashes.
_PAN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def mask_card_numbers(text: str | None) -> str | None:
    """Replace anything that looks like a full payment card number with its last 4 digits."""
    if not text:
        return text

    def repl(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        return f"**** **** **** {digits[-4:]}" if _luhn_ok(digits) else m.group()

    return _PAN.sub(repl, text)


def sanitize_extraction(ex: ReceiptExtraction) -> ReceiptExtraction:
    """Enforce in code what the prompt asks: never keep a full card number anywhere."""
    payments = []
    for p in ex.payments:
        last4 = re.sub(r"\D", "", p.card_last4 or "")[-4:] or None
        payments.append(
            p.model_copy(update={"card_last4": last4, "reference": mask_card_numbers(p.reference)})
        )
    return ex.model_copy(
        update={
            "payments": payments,
            "full_text": mask_card_numbers(ex.full_text) or "",
            "extras": [
                e.model_copy(update={"value": mask_card_numbers(e.value)}) for e in ex.extras
            ],
            "qr_and_barcodes": [mask_card_numbers(c) or "" for c in ex.qr_and_barcodes],
            "notes": mask_card_numbers(ex.notes),
        }
    )


# --- Rate limiting ------------------------------------------------------------------------


class RateLimiter:
    """Sliding-window limiter kept in memory; enough for a single-process, single-user app."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, cost: int = 1) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) + cost > self.limit:
                retry = int(hits[0] + self.window - now) + 1 if hits else int(self.window)
                raise HTTPException(
                    429,
                    "Too many requests, slow down a little",
                    headers={"Retry-After": str(retry)},
                )
            hits.extend([now] * cost)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --- Response headers ---------------------------------------------------------------------


# For the web app itself when the API serves it: its own scripts, Inter from Google Fonts,
# inline styles (animations set them), and photo previews from blob: URLs.
APP_CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool):
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        path = request.url.path
        if path.startswith("/api/"):
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        elif not path.startswith(("/docs", "/redoc", "/openapi.json")):
            h.setdefault("Content-Security-Policy", APP_CSP)
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if self.hsts:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


# --- Password and sessions ----------------------------------------------------------------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    # ":" rather than "$" so the value survives shell and docker-compose interpolation.
    return "scrypt:" + base64.b64encode(salt).decode() + ":" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split(":")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=len(expected), **_SCRYPT)
    return hmac.compare_digest(digest, expected)


COOKIE = "session"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign_session(secret: str, user_id: int, version: int, ttl_seconds: int, remember: bool) -> str:
    payload = f"{user_id}.{version}.{int(time.time()) + ttl_seconds}.{int(remember)}"
    return f"{payload}.{_sign(secret, payload)}"


def session_user(secret: str, token: str | None) -> tuple[int, int, bool] | None:
    """(user id, session version, remembered) from the cookie; None if missing, forged or expired."""
    parts = (token or "").split(".")
    if len(parts) != 5 or not all(p.isdigit() for p in parts[:4]):
        return None
    user_id, version, expires, remember, sig = parts
    if not hmac.compare_digest(sig, _sign(secret, f"{user_id}.{version}.{expires}.{remember}")):
        return None
    if int(expires) <= time.time():
        return None
    return int(user_id), int(version), remember == "1"
