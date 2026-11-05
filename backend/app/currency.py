"""Work out a sensible home currency from where the user is."""

from datetime import date
from functools import cache
from importlib import resources

from babel.numbers import get_territory_currencies


@cache
def _zone_countries() -> dict[str, str]:
    text = resources.files("tzdata").joinpath("zoneinfo/zone.tab").read_text()
    rows = (line.split("\t") for line in text.splitlines() if line and not line.startswith("#"))
    zones = {row[2]: row[0] for row in rows}
    zones.setdefault("Asia/Calcutta", "IN")  # older alias some browsers still report
    return zones


def country_for(timezone: str | None, locale: str | None) -> str | None:
    """Time zone first (it tracks where you are), then the locale's region (en-IN -> IN)."""
    if timezone and (country := _zone_countries().get(timezone)):
        return country
    if locale:
        parts = locale.replace("_", "-").split("-")
        region = next((p for p in parts[1:] if len(p) == 2 and p.isalpha()), None)
        if region:
            return region.upper()
    return None


def currency_for(country: str | None) -> str | None:
    if not country:
        return None
    try:
        current = get_territory_currencies(country, date.today(), tender=True)
    except Exception:  # noqa: BLE001 - unknown territory code
        return None
    return current[0] if current else None
