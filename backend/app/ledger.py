"""Writing confirmed drafts to the ledger, and reading expenses back."""

from datetime import date, time, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Category, Expense, LineItem, Merchant, MerchantRule, Receipt, User
from app.money import from_minor, to_minor
from app.pipeline import checks, fx
from app.schemas import (
    CustomerDraft,
    ExpenseDraft,
    ExpenseOut,
    ExtraDraft,
    LineItemOut,
    MerchantDraft,
)

DEFAULT_CATEGORIES = [
    ("Groceries", "shopping-basket", "#5f9a78"),
    ("Dining", "utensils", "#cf8a5c"),
    ("Transport & fuel", "car", "#5c84b0"),
    ("Shopping", "shopping-bag", "#c27996"),
    ("Bills & utilities", "receipt", "#c4a04f"),
    ("Health", "heart-pulse", "#c26a68"),
    ("Entertainment", "clapperboard", "#8b7bb5"),
    ("Travel", "plane", "#4f969e"),
    ("Education", "graduation-cap", "#6d76b3"),
    ("Home", "home", "#8a9a5b"),
    ("Personal care", "sparkles", "#c48aa8"),
    ("Gifts & donations", "gift", "#4f9a8a"),
    ("Other", "circle-dashed", "#9a958e"),
]


def create_user(db: Session, *, name: str, email: str, password_hash: str | None) -> User:
    """A new account with the default categories."""
    user = User(name=name, email=email, password_hash=password_hash)
    db.add(user)
    db.flush()
    for cat_name, icon, color in DEFAULT_CATEGORIES:
        db.add(Category(user_id=user.id, name=cat_name, icon=icon, color=color))
    return user


def own_category(db: Session, user_id: int, category_id: int | None) -> int | None:
    """category_id if it belongs to this user; anything else is rejected."""
    if category_id is None:
        return None
    category = db.get(Category, category_id)
    if category is None or category.user_id != user_id:
        raise ValueError("Unknown category")
    return category_id


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value[:5])
    except ValueError:
        return None


def upsert_merchant(db: Session, user_id: int, m: MerchantDraft) -> Merchant:
    normalized = checks.normalize_merchant(m.name)
    query = select(Merchant).where(
        Merchant.user_id == user_id, Merchant.normalized_name == normalized
    )
    if m.address:
        # Same chain at another address is another branch.
        query = query.where(or_(Merchant.address == m.address, Merchant.address.is_(None)))
    merchant = db.scalar(query.order_by(Merchant.id).limit(1))
    if merchant is None:
        merchant = Merchant(user_id=user_id, name=m.name, normalized_name=normalized)
        db.add(merchant)
    for field in ("branch", "address", "city", "postcode", "phone", "email", "website"):
        if getattr(m, field):
            setattr(merchant, field, getattr(m, field))
    if m.country:
        merchant.country = m.country
    if m.tax_ids:
        merchant.tax_ids = m.tax_ids
    if m.registrations:
        merchant.registrations = m.registrations
    db.flush()
    return merchant


def save_draft(db: Session, user: User, draft: ExpenseDraft, receipt: Receipt | None) -> Expense:
    if draft.total is None:
        raise ValueError("A total is required")
    if draft.purchased_on is None:
        raise ValueError("A purchase date is required")
    if not draft.merchant.name.strip():
        raise ValueError("A merchant name is required")
    cur = draft.currency.upper()

    def m(v: Decimal | None) -> int | None:
        return to_minor(v, cur)

    own_category(db, user.id, draft.category_id)
    for li in draft.line_items:
        own_category(db, user.id, li.category_id)
    merchant = upsert_merchant(db, user.id, draft.merchant)
    rate = draft.fx_rate
    if rate is None or draft.home_currency != user.home_currency:
        rate = fx.get_rate(db, draft.purchased_on, cur, user.home_currency)
    total_home = to_minor(draft.total * rate, user.home_currency) if rate is not None else None
    c = draft.customer
    expense = Expense(
        user_id=user.id,
        receipt_id=receipt.id if receipt else None,
        merchant_id=merchant.id,
        category_id=draft.category_id,
        merchant_name=draft.merchant.name.strip(),
        merchant_normalized=merchant.normalized_name,
        country=draft.country,
        language=draft.language,
        document_type=draft.document_type,
        receipt_number=draft.receipt_number,
        order_number=draft.order_number,
        purchased_on=draft.purchased_on,
        purchased_at_time=_parse_time(draft.purchased_at_time),
        order_type=draft.order_type,
        table_number=draft.table_number,
        guests=draft.guests,
        cashier=draft.cashier,
        terminal_id=draft.terminal_id,
        customer_name=c.name,
        customer_phone=c.phone,
        customer_email=c.email,
        customer_billing_address=c.billing_address,
        customer_delivery_address=c.delivery_address,
        customer_loyalty_id=c.loyalty_id,
        customer_tax_id=c.tax_id,
        currency=cur,
        subtotal=m(draft.subtotal),
        tax_total=m(sum((t.amount for t in draft.tax_lines), Decimal(0)))
        if draft.tax_lines
        else None,
        tax_inclusive=draft.tax_inclusive,
        tax_lines=[t.model_dump(mode="json") for t in draft.tax_lines],
        service_charge=m(draft.service_charge),
        delivery_fee=m(draft.delivery_fee),
        packaging_fee=m(draft.packaging_fee),
        tip=m(draft.tip),
        discount_total=m(draft.discount_total),
        rounding=m(draft.rounding),
        total=m(draft.total),
        amount_tendered=m(draft.amount_tendered),
        change_given=m(draft.change_given),
        home_currency=user.home_currency,
        total_home=total_home,
        fx_rate=rate,
        payments=[p.model_dump(mode="json") for p in draft.payments],
        extras=[e.model_dump() for e in draft.extras],
        notes=draft.notes,
        warranty_until=draft.warranty_until,
        return_by=draft.return_by,
        is_manual=receipt is None,
        line_items=[
            LineItem(
                position=i,
                description=li.description,
                description_en=li.description_en,
                sku=li.sku,
                hsn_sac_code=li.hsn_sac_code,
                quantity=li.quantity,
                unit=li.unit,
                unit_price=m(li.unit_price),
                discount=m(li.discount),
                tax_rate_percent=li.tax_rate_percent,
                amount=m(li.amount),
                category_id=li.category_id,
            )
            for i, li in enumerate(draft.line_items)
        ],
    )
    db.add(expense)

    # Learn: a category the user chose for this merchant applies to future receipts.
    if draft.category_id and draft.category_id != draft.suggested_category_id:
        rule = db.scalar(
            select(MerchantRule).where(
                MerchantRule.user_id == user.id,
                MerchantRule.merchant_normalized == merchant.normalized_name,
            )
        )
        if rule:
            rule.category_id = draft.category_id
        else:
            db.add(
                MerchantRule(
                    user_id=user.id,
                    merchant_normalized=merchant.normalized_name,
                    category_id=draft.category_id,
                )
            )
    db.flush()
    return expense


def expense_out(e: Expense) -> ExpenseOut:
    cur = e.currency
    mer = e.merchant
    return ExpenseOut(
        id=e.id,
        receipt_id=e.receipt_id,
        merchant_name=e.merchant_name,
        merchant=MerchantDraft(
            name=mer.name,
            branch=mer.branch,
            address=mer.address,
            city=mer.city,
            postcode=mer.postcode,
            country=mer.country,
            phone=mer.phone,
            email=mer.email,
            website=mer.website,
            tax_ids=mer.tax_ids or [],
            registrations=mer.registrations or [],
        )
        if mer
        else None,
        category_id=e.category_id,
        category_name=e.category.name if e.category else None,
        purchased_on=e.purchased_on,
        purchased_at_time=e.purchased_at_time.strftime("%H:%M") if e.purchased_at_time else None,
        country=e.country,
        currency=cur,
        total=from_minor(e.total, cur),
        tax_total=from_minor(e.tax_total, cur),
        home_currency=e.home_currency,
        total_home=from_minor(e.total_home, e.home_currency),
        fx_rate=e.fx_rate,
        payment_method=(e.payments[0].get("method") if e.payments else None),
        receipt_number=e.receipt_number,
        customer=CustomerDraft(
            name=e.customer_name,
            phone=e.customer_phone,
            email=e.customer_email,
            billing_address=e.customer_billing_address,
            delivery_address=e.customer_delivery_address,
            loyalty_id=e.customer_loyalty_id,
            tax_id=e.customer_tax_id,
        ),
        line_items=[
            LineItemOut(
                description=li.description,
                description_en=li.description_en,
                quantity=li.quantity,
                unit=li.unit,
                unit_price=from_minor(li.unit_price, cur),
                amount=from_minor(li.amount, cur),
                category_id=li.category_id,
            )
            for li in e.line_items
        ],
        extras=[ExtraDraft(**x) for x in e.extras or []],
        notes=e.notes,
        warranty_until=e.warranty_until,
        return_by=e.return_by,
        created_at=e.created_at,
    )


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(p) for p in month.split("-"))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return start, end


PERIODS = ("month", "3m", "ytd", "1y", "all")


def period_bounds(period: str, month: str, first: date | None) -> tuple[date, date, int]:
    """[start, end) and the number of calendar months for a period ending this month.

    "month" is the picked month; the others run up to today: the last 3 or 12 calendar months,
    the year to date, or everything since the first expense.
    """
    if period not in PERIODS or period == "month":
        start, end = month_bounds(month)
        return start, end, 1
    today = date.today()
    end = today + timedelta(days=1)
    index = today.year * 12 + today.month - 1
    if period == "ytd":
        months = today.month
    elif period == "3m":
        months = 3
    elif period == "1y":
        months = 12
    else:  # all
        first = first or today
        months = index - (first.year * 12 + first.month - 1) + 1
    start_index = index - months + 1
    return date(start_index // 12, start_index % 12 + 1, 1), end, months
