from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ReceiptStatus(StrEnum):
    PROCESSING = "processing"
    READY_TO_CONFIRM = "ready_to_confirm"
    NEEDS_REVIEW = "needs_review"
    RETAKE = "retake"
    REJECTED = "rejected"
    FAILED = "failed"
    SAVED = "saved"
    DISCARDED = "discarded"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Me")
    # Stored lowercased. Null only for the user created before accounts existed.
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    home_currency: Mapped[str] = mapped_column(String(3), default="INR")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    locale: Mapped[str] = mapped_column(String(16), default="en-IN")
    # default -> detected (from time zone/locale) -> user (picked by hand); only "default" is replaced.
    home_currency_source: Mapped[str] = mapped_column(
        String(16), default="default", server_default="default"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    icon: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(16))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    branch: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    postcode: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(200))
    tax_ids: Mapped[list] = mapped_column(JSONB, default=list)
    registrations: Mapped[list] = mapped_column(JSONB, default=list)


class MerchantRule(Base):
    """A category the user picked for a merchant; applied to later receipts."""

    __tablename__ = "merchant_rules"
    __table_args__ = (UniqueConstraint("user_id", "merchant_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    merchant_normalized: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    image_path: Mapped[str] = mapped_column(String(500))
    image_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default=ReceiptStatus.PROCESSING, index=True)
    status_detail: Mapped[str | None] = mapped_column(Text)
    quality: Mapped[dict | None] = mapped_column(JSONB)
    raw_extraction: Mapped[dict | None] = mapped_column(JSONB)
    draft: Mapped[dict | None] = mapped_column(JSONB)
    issues: Mapped[list] = mapped_column(JSONB, default=list)
    full_text: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[float | None] = mapped_column(Float)
    duplicate_of_expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="SET NULL", use_alter=True)
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a reader picks the receipt up; a processing receipt without it is waiting in line.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    expense: Mapped["Expense | None"] = relationship(
        back_populates="receipt", foreign_keys="Expense.receipt_id"
    )


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL"), unique=True
    )
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )

    merchant_name: Mapped[str] = mapped_column(String(200))
    merchant_normalized: Mapped[str] = mapped_column(String(200), index=True)
    country: Mapped[str | None] = mapped_column(String(2))
    language: Mapped[str | None] = mapped_column(String(16))

    document_type: Mapped[str | None] = mapped_column(String(40))
    receipt_number: Mapped[str | None] = mapped_column(String(120))
    order_number: Mapped[str | None] = mapped_column(String(120))
    purchased_on: Mapped[date] = mapped_column(Date, index=True)
    purchased_at_time: Mapped[time | None] = mapped_column(Time)
    order_type: Mapped[str | None] = mapped_column(String(40))
    table_number: Mapped[str | None] = mapped_column(String(40))
    guests: Mapped[int | None] = mapped_column(Integer)
    cashier: Mapped[str | None] = mapped_column(String(120))
    terminal_id: Mapped[str | None] = mapped_column(String(120))

    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_phone: Mapped[str | None] = mapped_column(String(60))
    customer_email: Mapped[str | None] = mapped_column(String(200))
    customer_billing_address: Mapped[str | None] = mapped_column(Text)
    customer_delivery_address: Mapped[str | None] = mapped_column(Text)
    customer_loyalty_id: Mapped[str | None] = mapped_column(String(120))
    customer_tax_id: Mapped[str | None] = mapped_column(String(120))

    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[int | None] = mapped_column(BigInteger)
    tax_total: Mapped[int | None] = mapped_column(BigInteger)
    tax_inclusive: Mapped[bool | None] = mapped_column()
    tax_lines: Mapped[list] = mapped_column(JSONB, default=list)
    service_charge: Mapped[int | None] = mapped_column(BigInteger)
    delivery_fee: Mapped[int | None] = mapped_column(BigInteger)
    packaging_fee: Mapped[int | None] = mapped_column(BigInteger)
    tip: Mapped[int | None] = mapped_column(BigInteger)
    discount_total: Mapped[int | None] = mapped_column(BigInteger)
    rounding: Mapped[int | None] = mapped_column(BigInteger)
    total: Mapped[int] = mapped_column(BigInteger)
    amount_tendered: Mapped[int | None] = mapped_column(BigInteger)
    change_given: Mapped[int | None] = mapped_column(BigInteger)

    home_currency: Mapped[str] = mapped_column(String(3))
    total_home: Mapped[int | None] = mapped_column(BigInteger)
    fx_rate: Mapped[float | None] = mapped_column(Numeric(18, 8))

    payments: Mapped[list] = mapped_column(JSONB, default=list)
    extras: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    return_by: Mapped[date | None] = mapped_column(Date)
    is_manual: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    receipt: Mapped[Receipt | None] = relationship(
        back_populates="expense", foreign_keys=[receipt_id]
    )
    category: Mapped[Category | None] = relationship()
    merchant: Mapped[Merchant | None] = relationship()
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan", order_by="LineItem.position"
    )


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(80))
    hsn_sac_code: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[float | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[int | None] = mapped_column(BigInteger)
    discount: Mapped[int | None] = mapped_column(BigInteger)
    tax_rate_percent: Mapped[float | None] = mapped_column(Numeric(7, 3))
    amount: Mapped[int] = mapped_column(BigInteger)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )

    expense: Mapped[Expense] = relationship(back_populates="line_items")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(10), default="month")
    amount: Mapped[int] = mapped_column(BigInteger)  # minor units of the home currency


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("on_date", "base", "quote"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    on_date: Mapped[date] = mapped_column(Date)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[float] = mapped_column(Numeric(18, 8))
