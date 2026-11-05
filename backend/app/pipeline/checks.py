"""Deterministic checks on an extraction: totals, dates and country-specific formats."""

import re
from datetime import date, timedelta
from decimal import Decimal

from app.money import smallest_unit
from app.pipeline.schemas import ReceiptExtraction


def _d(value: float | None) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def tolerance(currency: str, total: Decimal) -> Decimal:
    # Allow a couple of minor units, or 0.2% on large bills, for per-line rounding.
    return max(smallest_unit(currency) * 2, abs(total) * Decimal("0.002"))


def check_totals(ex: ReceiptExtraction) -> list[str]:
    """Return problems; empty means the receipt adds up."""
    if ex.total is None:
        return ["The total could not be read."]
    total = _d(ex.total)
    tol = tolerance(ex.currency, total)
    tax = sum((_d(t.amount) for t in ex.tax_lines), Decimal(0))
    fees = _d(ex.service_charge) + _d(ex.delivery_fee) + _d(ex.packaging_fee) + _d(ex.tip)
    adjust = fees - _d(ex.discount_total) + _d(ex.rounding)

    if ex.subtotal is not None:
        base = _d(ex.subtotal)
    elif ex.line_items:
        base = sum((_d(i.amount) for i in ex.line_items), Decimal(0))
    else:
        return []  # Only a total is printed; nothing to reconcile against.

    candidates = []
    if ex.tax_inclusive is not False:
        candidates.append(base + adjust)
    if ex.tax_inclusive is not True:
        candidates.append(base + tax + adjust)
    if any(abs(c - total) <= tol for c in candidates):
        problems = []
    else:
        closest = min(candidates, key=lambda c: abs(c - total))
        problems = [
            f"Subtotal, taxes and fees add up to {closest} but the printed total is {total}."
        ]

    if ex.subtotal is not None and ex.line_items:
        items = sum((_d(i.amount) for i in ex.line_items), Decimal(0))
        # Some receipts print item prices before line tax; only flag clear gaps.
        if abs(items - base) > tol and abs(items - (base + tax)) > tol:
            problems.append(f"Line items add up to {items} but the subtotal is {base}.")
    return problems


def check_date(purchase: date | None, today: date) -> list[str]:
    if purchase is None:
        return ["The purchase date could not be read."]
    if purchase > today + timedelta(days=1):
        return [f"The date {purchase.isoformat()} is in the future; day and month may be swapped."]
    if purchase < today - timedelta(days=365 * 5):
        return [f"The date {purchase.isoformat()} is more than five years ago."]
    return []


_TAX_ID_PATTERNS = {
    "GSTIN": re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"),
    "ABN": re.compile(r"^\d{11}$"),
    "TRN": re.compile(r"^\d{15}$"),
    "CNPJ": re.compile(r"^\d{14}$"),
    "VAT": re.compile(r"^[A-Z]{2}[0-9A-Z]{2,13}$"),
}


def check_tax_ids(ex: ReceiptExtraction) -> list[str]:
    problems = []
    for tax_id in ex.merchant.tax_ids:
        pattern = _TAX_ID_PATTERNS.get(tax_id.type.upper())
        value = re.sub(r"[\s.\-/]", "", tax_id.value.upper())
        if pattern and not pattern.match(value):
            problems.append(f"{tax_id.type} '{tax_id.value}' doesn't match the expected format.")
    return problems


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalize_merchant(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    cleaned = re.sub(r"\b(pvt|private|ltd|limited|llc|inc|gmbh|co|corp|plc|the)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip() or name.lower().strip()
