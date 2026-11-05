import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _stored_secret(path: Path) -> str:
    """A random secret kept on disk, so restarts don't sign everyone out."""
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(32)
        path.write_text(secret)
        path.chmod(0o600)
        return secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://expense:expense@localhost:5432/expense"
    upload_dir: Path = Path("data/uploads")
    # The built frontend (frontend/dist). When set, the API serves the web app too, so one
    # service runs everything; the Docker image sets it.
    static_dir: Path | None = None
    # Falls back to the SDK's own lookup (ANTHROPIC_API_KEY env var or `ant auth login`).
    anthropic_api_key: str | None = None

    # Models: a fast one for the quality gate and categories, a strong one for extraction.
    fast_model: str = "claude-haiku-5-5"
    extraction_model: str = "claude-opus-5-5"
    extraction_effort: str = "low"  # fast first read; a failed check retries at retry_effort
    retry_effort: str = "high"

    fx_api_url: str = "https://api.frankfurter.app"
    # Used for currencies the ECB doesn't publish; {tag} is a YYYY-MM-DD date or "latest".
    fx_fallback_urls: list[str] = [
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{tag}/v1/currencies/{base}.min.json",
        "https://{tag}.currency-api.pages.dev/v1/currencies/{base}.min.json",
    ]
    cors_origins: list[str] = ["http://localhost:5174"]
    process_in_background: bool = True
    # How many receipts are read at the same time; more speeds up batches but risks rate limits.
    reader_workers: int = 4

    # Accounts. Turn sign-up off once everyone who should have an account has one.
    allow_signup: bool = True
    # Empty: a random one kept in data/session_secret.
    session_secret: str = Field(default="", validate_default=True)
    # "Keep me signed in" lasts this long; otherwise the session ends with the browser, and at
    # the latest after session_short_hours.
    session_ttl_hours: int = 24 * 30
    session_short_hours: int = 12
    cookie_secure: bool = False  # set true when served over HTTPS
    hsts: bool = False

    # Email, for confirming new accounts and resetting passwords. Set EMAIL_FROM plus one way to
    # send: RESEND_API_KEY, BREVO_API_KEY, or SMTP_HOST (with SMTP_USERNAME/SMTP_PASSWORD, e.g. a
    # Gmail app password). Railway blocks SMTP below its Pro plan, so use an API there. Every
    # email sign-up must be confirmed, so without one of these only social sign-in is offered.
    email_from: str = ""  # e.g. "Receipts <receipts@yourdomain.com>"
    resend_api_key: str = ""
    brevo_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587  # 465 for implicit TLS
    smtp_username: str = ""
    smtp_password: str = ""
    # Local testing only: print emails (with their links) to the server log instead of sending.
    email_console: bool = False
    # The site's public address, used in email links. On Railway it's filled in from
    # RAILWAY_PUBLIC_DOMAIN; links never trust the request's Host header.
    app_url: str = ""
    railway_public_domain: str = ""
    # Social sign-in. Each provider is offered once its keys are set; the redirect URI to
    # register with each is <site address>/api/auth/<provider>/callback. See the README.
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    apple_client_id: str = ""  # the Services ID, e.g. com.example.receipts.web
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""  # contents of the .p8 file
    verify_link_hours: int = 48
    reset_link_minutes: int = 60

    # Abuse limits (per client IP).
    uploads_per_hour: int = 60
    max_files_per_upload: int = 20
    login_attempts_per_15_min: int = 10
    emails_per_hour: int = 10

    @property
    def email_enabled(self) -> bool:
        if self.email_console:
            return True
        return bool(
            self.email_from and (self.resend_api_key or self.brevo_api_key or self.smtp_host)
        )

    @property
    def social_providers(self) -> list[str]:
        on = {
            "google": self.google_client_id and self.google_client_secret,
            "microsoft": self.microsoft_client_id and self.microsoft_client_secret,
            "apple": self.apple_client_id
            and self.apple_team_id
            and self.apple_key_id
            and self.apple_private_key,
        }
        return [name for name, ok in on.items() if ok]

    @property
    def public_url(self) -> str:
        if self.app_url:
            return self.app_url.rstrip("/")
        if self.railway_public_domain:
            return f"https://{self.railway_public_domain}"
        return "http://localhost:5174"

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Hosts such as Railway hand out postgres://… or postgresql://…; SQLAlchemy needs the
        # driver named to use psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if isinstance(v, str) and v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @field_validator("session_secret", mode="before")
    @classmethod
    def _secret_or_stored(cls, v: str | None) -> str:
        # An empty SESSION_SECRET= line in .env would otherwise sign cookies with "".
        return v or _stored_secret(Path("data/session_secret"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
