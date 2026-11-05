"""Structured-output schemas the models fill in. Field descriptions double as instructions."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema

# The API allows only 16 nullable fields per schema, so most optional fields are sent as plain
# strings/numbers ("" or 0 when not printed) and turned back into None when the reply is parsed.
Text = Annotated[
    str | None,
    WithJsonSchema({"type": "string"}),
    BeforeValidator(lambda v: v.strip() or None if isinstance(v, str) else v),
]
Fee = Annotated[
    float | None, WithJsonSchema({"type": "number"}), BeforeValidator(lambda v: v or None)
]
Count = Annotated[
    int | None, WithJsonSchema({"type": "integer"}), BeforeValidator(lambda v: v or None)
]


class QualityCheck(BaseModel):
    is_receipt: bool = Field(description="True if the image shows a receipt, bill or invoice.")
    readable: bool = Field(description="True if the merchant and the total can be read.")
    receipt_count: int = Field(description="How many separate receipts are in the image.")
    issues: list[str] = Field(
        description="Problems such as blurry, glare, dark, total cut off, folded, partial."
    )
    retake_hint: str | None = Field(
        description="One short, specific tip for a better photo, or null if none is needed."
    )


class TaxId(BaseModel):
    type: str = Field(description="e.g. GSTIN, VAT, ABN, TRN, CNPJ, EIN, PAN.")
    value: str


class MerchantInfo(BaseModel):
    name: str = Field(description="Merchant name exactly as printed.")
    legal_name: Text = Field(description="Registered or parent company name if printed.")
    branch: Text = Field(description="Branch, outlet or store number.")
    address: Text
    city: Text
    postcode: Text
    country_code: Text = Field(description="ISO 3166-1 alpha-2 code of the merchant.")
    phone: Text
    email: Text
    website: Text
    tax_ids: list[TaxId]
    registrations: list[str] = Field(
        description="Other licence or registration numbers, e.g. 'FSSAI 1001...'."
    )


class CustomerInfo(BaseModel):
    name: Text
    phone: Text
    email: Text
    billing_address: Text
    delivery_address: Text
    loyalty_id: Text
    tax_id: Text


class LineItemOut(BaseModel):
    description: str = Field(description="Item text as printed.")
    description_en: Text = Field(
        description="English translation if the receipt is not in English, else null."
    )
    sku: Text = Field(description="SKU, barcode or item code.")
    hsn_sac_code: Text
    quantity: float | None
    unit: Text = Field(description="kg, g, L, ml, pcs, etc.")
    unit_price: float | None
    discount: Fee = Field(description="Discount on this line as a positive number.")
    tax_rate_percent: float | None
    amount: float = Field(description="Line total as printed (after line discount).")


class TaxLine(BaseModel):
    name: str = Field(description="e.g. CGST, SGST, IGST, VAT, Sales tax, GST, Consumption tax.")
    rate_percent: float | None
    taxable_amount: float | None
    amount: float


class PaymentOut(BaseModel):
    method: str = Field(description="cash, card, upi, wallet, bank_transfer, voucher or other.")
    card_brand: Text
    card_last4: Text = Field(description="Only the last 4 digits, never the full number.")
    reference: Text = Field(description="UPI ref, transaction ID or RRN.")
    approval_code: Text
    amount: float | None


class ExtraField(BaseModel):
    label: str
    value: str


class ReceiptExtraction(BaseModel):
    country_code: Text = Field(
        description="ISO 3166-1 alpha-2 country of purchase, inferred from address, currency, "
        "tax IDs, phone codes and language."
    )
    language: Text = Field(description="Main language as an ISO 639-1 code.")
    currency: str = Field(description="ISO 4217 currency of the amounts.")
    document_type: Text = Field(
        description="receipt, tax_invoice, bill, credit_note, refund or other."
    )
    receipt_number: Text
    order_number: Text
    purchase_date: Text = Field(
        description="Purchase date as YYYY-MM-DD, interpreting day/month order using the country."
    )
    purchase_date_as_printed: Text
    purchase_time: Text = Field(description="24h HH:MM, or null.")
    order_type: Text = Field(description="dine_in, takeaway, delivery, online, in_store.")
    table_number: Text
    guests: Count
    cashier: Text
    terminal_id: Text

    merchant: MerchantInfo
    customer: CustomerInfo
    line_items: list[LineItemOut]

    subtotal: float | None
    tax_lines: list[TaxLine]
    tax_inclusive: bool | None = Field(
        description="True if item prices already include tax (common for VAT), false if tax is "
        "added on top, null if unclear."
    )
    service_charge: Fee
    delivery_fee: Fee
    packaging_fee: Fee
    tip: Fee
    discount_total: Fee = Field(description="Bill-level discounts as a positive number.")
    rounding: Fee = Field(description="Round-off adjustment, signed.")
    total: float | None = Field(description="Final amount payable.")
    amount_tendered: float | None
    change_given: float | None
    payments: list[PaymentOut]

    warranty_until: Text = Field(description="YYYY-MM-DD if a warranty end can be derived.")
    return_by: Text = Field(description="YYYY-MM-DD if a return window can be derived.")
    qr_and_barcodes: list[str] = Field(description="Meaningful content of any decoded codes.")
    extras: list[ExtraField] = Field(
        description="Every other useful printed detail not captured above: loyalty points, "
        "savings, offers, return policy, warranty text, serial numbers, IRN, etc."
    )
    full_text: str = Field(description="The whole receipt transcribed line by line.")

    confidence: float = Field(description="0 to 1: how sure you are the key fields are right.")
    low_confidence_fields: list[str] = Field(
        description="Names of fields that were hard to read or guessed, e.g. 'total', 'purchase_date'."
    )
    notes: Text = Field(description="Anything the user should know about this receipt.")
    category: Text = Field(
        default=None,
        description="Best spending category for the whole receipt, chosen from the list given "
        "in the instructions; empty if no list was given.",
    )


class ItemCategory(BaseModel):
    index: int
    category: str


class CategoryChoice(BaseModel):
    category: str = Field(description="One name from the allowed categories.")
    item_categories: list[ItemCategory] = Field(
        description="Only when items clearly belong to different categories; else empty."
    )
