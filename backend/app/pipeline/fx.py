"""Daily FX rates, cached in Postgres.

ECB reference rates (via Frankfurter) first; they cover about 30 currencies, so anything else
(AED, SAR, VND, ...) comes from the community currency-api, which covers about 200.
"""

import logging
import time
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import FxRate

log = logging.getLogger(__name__)

# Lookups that just failed, so converting many expenses doesn't ask again for each one.
_MISS_TTL = 60.0
_misses: dict[tuple[date, str, str], float] = {}


def forget_misses() -> None:
    """Called before an explicit retry, so it really asks again."""
    _misses.clear()


def get_rate(db: Session, on: date, base: str, quote: str) -> Decimal | None:
    """Rate to convert 1 unit of `base` into `quote` on a date; None if unavailable."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return Decimal(1)
    cached = db.scalar(
        select(FxRate).where(FxRate.on_date == on, FxRate.base == base, FxRate.quote == quote)
    )
    if cached:
        return Decimal(str(cached.rate))
    key = (on, base, quote)
    if _misses.get(key, 0) > time.monotonic():
        return None
    rate = _ecb_rate(on, base, quote) or _community_rate(on, base, quote)
    if rate is None:
        log.warning("No FX rate for %s->%s on %s", base, quote, on)
        _misses[key] = time.monotonic() + _MISS_TTL
        return None
    db.add(FxRate(on_date=on, base=base, quote=quote, rate=rate))
    db.flush()
    return rate


def _ecb_rate(on: date, base: str, quote: str) -> Decimal | None:
    try:
        resp = httpx.get(
            f"{get_settings().fx_api_url}/{on.isoformat()}",
            params={"from": base, "to": quote},
            timeout=10,
        )
        resp.raise_for_status()
        return Decimal(str(resp.json()["rates"][quote]))
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        log.info("ECB rate unavailable for %s->%s on %s: %s", base, quote, on, e)
        return None


def _community_rate(on: date, base: str, quote: str) -> Decimal | None:
    # Published once a day under a dated tag; today's may not be out yet, so fall back to latest.
    tags = [on.isoformat(), "latest"] if on >= date.today() else [on.isoformat()]
    for tag in tags:
        for url in get_settings().fx_fallback_urls:
            try:
                resp = httpx.get(url.format(tag=tag, base=base.lower()), timeout=10)
                resp.raise_for_status()
                return Decimal(str(resp.json()[base.lower()][quote.lower()]))
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                log.info("Fallback rate unavailable from %s: %s", url, e)
    return None
