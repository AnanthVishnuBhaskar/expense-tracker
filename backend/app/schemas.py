"""API request and response models. Money crosses the API as decimal strings."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TaxLineDraft(BaseModel):
    name: str
    rate_percent: Decimal | None = None
    taxable_amount: Decimal | None = None
    amount: Decimal


class PaymentDraft(BaseModel):
    method: str
    card_brand: str | None = None
    card_last4: str | None = None
    reference: str | None = None
    approval_code: str | None = None
    amount: Decimal | None = None


class ExtraDraft(BaseModel):
    label: str
    value: str


class MerchantDraft(BaseModel):
    name: str = ""
    legal_name: str | None = None
    branch: str | None = None
    address: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    tax_ids: list[dict] = Field(default_factory=list)
    registrations: list[str] = Field(default_factory=list)


class CustomerDraft(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    billing_address: str | None = None
    delivery_address: str | None = None
    loyalty_id: str | None = None
    tax_id: str | None = None


class LineItemDraft(BaseModel):
    description: str
    description_en: str | None = None
    sku: str | None = None
    hsn_sac_code: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    discount: Decimal | None = None
    tax_rate_percent: Decimal | None = None
    amount: Decimal
    category_id: int | None = None


class ExpenseDraft(BaseModel):
    """What the user reviews on the confirm card, and sends back (possibly edited)."""

    merchant: MerchantDraft
    customer: CustomerDraft = Field(default_factory=CustomerDraft)
    country: str | None = None
    language: str | None = None
    document_type: str | None = None
    receipt_number: str | None = None
    order_number: str | None = None
    purchased_on: date | None = None
    purchased_at_time: str | None = None
    order_type: str | None = None
    table_number: str | None = None
    guests: int | None = None
    cashier: str | None = None
    terminal_id: str | None = None

    currency: str
    subtotal: Decimal | None = None
    tax_lines: list[TaxLineDraft] = Field(default_factory=list)
    tax_inclusive: bool | None = None
    service_charge: Decimal | None = None
    delivery_fee: Decimal | None = None
    packaging_fee: Decimal | None = None
    tip: Decimal | None = None
    discount_total: Decimal | None = None
    rounding: Decimal | None = None
    total: Decimal | None = None
    amount_tendered: Decimal | None = None
    change_given: Decimal | None = None
    payments: list[PaymentDraft] = Field(default_factory=list)
    line_items: list[LineItemDraft] = Field(default_factory=list)
    extras: list[ExtraDraft] = Field(default_factory=list)
    warranty_until: date | None = None
    return_by: date | None = None
    notes: str | None = None

    category_id: int | None = None
    suggested_category_id: int | None = None
    home_currency: str | None = None
    fx_rate: Decimal | None = None
    total_home: Decimal | None = None
    low_confidence_fields: list[str] = Field(default_factory=list)


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    status_detail: str | None
    issues: list[str]
    quality: dict | None
    draft: ExpenseDraft | None
    confidence: float | None
    duplicate_of_expense_id: int | None
    expense_id: int | None = None
    # True when this exact photo was uploaded before; the earlier receipt is returned instead.
    already_uploaded: bool = False
    uploaded_at: datetime
    processed_at: datetime | None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    icon: str | None = None
    color: str | None = None


class CategoryOut(CategoryIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LineItemOut(BaseModel):
    description: str
    description_en: str | None
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    amount: Decimal
    category_id: int | None


class ExpenseOut(BaseModel):
    id: int
    receipt_id: int | None
    merchant_name: str
    merchant: MerchantDraft | None
    category_id: int | None
    category_name: str | None
    purchased_on: date
    purchased_at_time: str | None
    country: str | None
    currency: str
    total: Decimal
    tax_total: Decimal | None
    home_currency: str
    total_home: Decimal | None
    fx_rate: Decimal | None
    payment_method: str | None
    receipt_number: str | None
    customer: CustomerDraft
    line_items: list[LineItemOut]
    extras: list[ExtraDraft]
    notes: str | None
    warranty_until: date | None
    return_by: date | None
    created_at: datetime


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    home_currency: str
    home_currency_source: str
    timezone: str
    locale: str


class DetectIn(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=35)


class SettingsIn(BaseModel):
    name: str | None = None
    home_currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = None
    locale: str | None = None


class BudgetIn(BaseModel):
    category_id: int | None = None
    amount: Decimal = Field(gt=0)


class BudgetOut(BaseModel):
    id: int
    category_id: int | None
    amount: Decimal


class CategorySpend(BaseModel):
    category_id: int | None
    name: str
    color: str | None
    icon: str | None
    spent: Decimal
    budget: Decimal | None
    count: int


class DaySpend(BaseModel):
    day: date
    spent: Decimal


class Insight(BaseModel):
    kind: str  # budget, unusual, info
    severity: str  # info, warning, critical
    message: str


class UnconvertedSpend(BaseModel):
    """Expenses left out of the totals because no exchange rate could be found."""

    currency: str
    total: Decimal
    count: int


class MonthSummary(BaseModel):
    month: str
    period: str = "month"
    start: date
    end: date  # inclusive
    bucket: str = "day"  # by_day holds days, or the first day of each month
    home_currency: str
    total: Decimal
    previous_total: Decimal
    budget: Decimal | None
    count: int
    by_category: list[CategorySpend]
    by_day: list[DaySpend]
    top_merchants: list[dict]
    insights: list[Insight]
    pending_receipts: int
    unconverted: list[UnconvertedSpend] = []


class MonthTotal(BaseModel):
    month: str
    total: Decimal
    count: int


class YearOverview(BaseModel):
    year: int
    home_currency: str
    first_month: str | None  # earliest month with an expense, to bound navigation
    months: list[MonthTotal]
