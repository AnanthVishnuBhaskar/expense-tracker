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
    cors_origins: list[str] = ["http://localhost:5173"]
    process_in_background: bool = True
    # How many receipts are read at the same time; more speeds up batches but risks rate limits.
    reader_workers: int = 4

    # Accounts. Turn sign-up off once everyone who should have an account has one.
    allow_signup: bool = True
    # Empty: a random one kept in data/session_secret.
    session_secret: str = Field(default="", validate_default=True)
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = False  # set true when served over HTTPS
    hsts: bool = False

    # Abuse limits (per client IP).
    uploads_per_hour: int = 60
    max_files_per_upload: int = 20
    login_attempts_per_15_min: int = 10

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
