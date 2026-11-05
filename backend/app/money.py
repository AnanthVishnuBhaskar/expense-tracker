"""Money helpers. Amounts are stored as integer minor units plus an ISO 4217 code."""

from decimal import ROUND_HALF_UP, Decimal

# Currencies whose minor unit is not 2 decimal places (ISO 4217).
_MINOR_UNIT_EXCEPTIONS = {
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
}


def minor_units(currency: str) -> int:
    return _MINOR_UNIT_EXCEPTIONS.get(currency.upper(), 2)


def to_minor(amount: Decimal | float | str | None, currency: str) -> int | None:
    if amount is None:
        return None
    exp = Decimal(1).scaleb(-minor_units(currency))
    value = Decimal(str(amount)).quantize(exp, rounding=ROUND_HALF_UP)
    return int(value.scaleb(minor_units(currency)))


def from_minor(amount: int | None, currency: str) -> Decimal | None:
    if amount is None:
        return None
    return Decimal(amount).scaleb(-minor_units(currency))


def smallest_unit(currency: str) -> Decimal:
    return Decimal(1).scaleb(-minor_units(currency))
