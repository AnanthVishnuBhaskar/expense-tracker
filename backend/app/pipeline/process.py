"""The receipt agent: takes an uploaded photo to a draft the user confirms."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Expense, MerchantRule, Receipt, ReceiptStatus, User
from app.money import from_minor, to_minor
from app.pipeline import checks, fx
from app.pipeline.ai import AIError, ReceiptAI
from app.pipeline.image import decode_codes
from app.pipeline.schemas import ReceiptExtraction
from app.schemas import (
    CustomerDraft,
    ExpenseDraft,
    ExtraDraft,
    LineItemDraft,
    MerchantDraft,
    PaymentDraft,
    TaxLineDraft,
)
from app.security import sanitize_extraction

log = logging.getLogger(__name__)

# Below this sharpness score a photo is almost certainly too blurry to read.
MIN_SHARPNESS = 15.0
LOW_CONFIDENCE = 0.6
KEY_FIELDS = {"total", "purchase_date", "merchant", "merchant.name", "currency"}


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def build_draft(ex: ReceiptExtraction) -> ExpenseDraft:
    m, c = ex.merchant, ex.customer
    return ExpenseDraft(
        merchant=MerchantDraft(
            name=m.name,
            legal_name=m.legal_name,
            branch=m.branch,
            address=m.address,
            city=m.city,
            postcode=m.postcode,
            country=m.country_code,
            phone=m.phone,
            email=m.email,
            website=m.website,
            tax_ids=[t.model_dump() for t in m.tax_ids],
            registrations=m.registrations,
        ),
        customer=CustomerDraft(**c.model_dump()),
        country=(ex.country_code or m.country_code),
        language=ex.language,
        document_type=ex.document_type,
        receipt_number=ex.receipt_number,
        order_number=ex.order_number,
        purchased_on=checks.parse_iso_date(ex.purchase_date),
        purchased_at_time=ex.purchase_time,
        order_type=ex.order_type,
        table_number=ex.table_number,
        guests=ex.guests,
        cashier=ex.cashier,
        terminal_id=ex.terminal_id,
        currency=ex.currency.upper(),
        subtotal=_dec(ex.subtotal),
        tax_lines=[
            TaxLineDraft(
                name=t.name,
                rate_percent=_dec(t.rate_percent),
                taxable_amount=_dec(t.taxable_amount),
                amount=_dec(t.amount),
            )
            for t in ex.tax_lines
        ],
        tax_inclusive=ex.tax_inclusive,
        service_charge=_dec(ex.service_charge),
        delivery_fee=_dec(ex.delivery_fee),
        packaging_fee=_dec(ex.packaging_fee),
        tip=_dec(ex.tip),
        discount_total=_dec(ex.discount_total),
        rounding=_dec(ex.rounding),
        total=_dec(ex.total),
        amount_tendered=_dec(ex.amount_tendered),
        change_given=_dec(ex.change_given),
        payments=[
            PaymentDraft(**{**p.model_dump(), "amount": _dec(p.amount)}) for p in ex.payments
        ],
        line_items=[
            LineItemDraft(
                description=i.description,
                description_en=i.description_en,
                sku=i.sku,
                hsn_sac_code=i.hsn_sac_code,
                quantity=_dec(i.quantity),
                unit=i.unit,
                unit_price=_dec(i.unit_price),
                discount=_dec(i.discount),
                tax_rate_percent=_dec(i.tax_rate_percent),
                amount=_dec(i.amount),
            )
            for i in ex.line_items
        ],
        extras=[ExtraDraft(label="Code", value=v) for v in ex.qr_and_barcodes]
        + [ExtraDraft(**e.model_dump()) for e in ex.extras],
        warranty_until=checks.parse_iso_date(ex.warranty_until),
        return_by=checks.parse_iso_date(ex.return_by),
        notes=ex.notes,
        low_confidence_fields=ex.low_confidence_fields,
    )


def find_duplicate(db: Session, receipt: Receipt, draft: ExpenseDraft) -> Expense | None:
    same_image = db.scalar(
        select(Expense)
        .join(Receipt, Expense.receipt_id == Receipt.id)
        .where(
            Receipt.user_id == receipt.user_id,
            Receipt.image_hash == receipt.image_hash,
            Receipt.id != receipt.id,
        )
    )
    if same_image:
        return same_image
    if draft.total is None or draft.purchased_on is None:
        return None
    return db.scalar(
        select(Expense).where(
            Expense.user_id == receipt.user_id,
            Expense.merchant_normalized == checks.normalize_merchant(draft.merchant.name),
            Expense.purchased_on == draft.purchased_on,
            Expense.currency == draft.currency,
            Expense.total == to_minor(draft.total, draft.currency),
        )
    )


def suggest_category(
    db: Session, ai: ReceiptAI, user_id: int, draft: ExpenseDraft, picked: str | None = None
) -> None:
    categories = db.scalars(select(Category).where(Category.user_id == user_id)).all()
    if not categories:
        return
    by_name = {c.name.lower(): c.id for c in categories}
    rule = db.scalar(
        select(MerchantRule).where(
            MerchantRule.user_id == user_id,
            MerchantRule.merchant_normalized == checks.normalize_merchant(draft.merchant.name),
        )
    )
    if rule:
        draft.category_id = draft.suggested_category_id = rule.category_id
        return
    if picked and (cat_id := by_name.get(picked.lower())):
        draft.category_id = draft.suggested_category_id = cat_id  # chosen during extraction
        return
    try:
        choice = ai.categorize(
            draft.merchant.name,
            [i.description_en or i.description for i in draft.line_items],
            [c.name for c in categories],
        )
    except AIError as e:
        log.warning("categorize failed: %s", e)
        return
    cat_id = by_name.get(choice.category.lower()) or by_name.get("other")
    draft.category_id = draft.suggested_category_id = cat_id
    for ic in choice.item_categories:
        if 0 <= ic.index < len(draft.line_items):
            draft.line_items[ic.index].category_id = by_name.get(ic.category.lower())


def convert_currency(db: Session, user: User, draft: ExpenseDraft) -> list[str]:
    draft.home_currency = user.home_currency
    if draft.total is None:
        return []
    on = draft.purchased_on or date.today()
    rate = fx.get_rate(db, on, draft.currency, user.home_currency)
    if rate is None:
        return [f"No exchange rate found for {draft.currency} to {user.home_currency}."]
    draft.fx_rate = rate
    draft.total_home = from_minor(
        to_minor(draft.total * rate, user.home_currency), user.home_currency
    )
    return []


def process_receipt(db: Session, ai: ReceiptAI, receipt_id: int, upload_dir: Path) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if receipt is None:
        raise ValueError(f"receipt {receipt_id} not found")
    user = db.get(User, receipt.user_id)
    image = (upload_dir / receipt.image_path).read_bytes()

    def finish(status: ReceiptStatus, detail: str | None = None) -> Receipt:
        receipt.status = status
        receipt.status_detail = detail
        receipt.processed_at = datetime.now(UTC)
        db.commit()
        return receipt

    def step(text: str) -> None:
        receipt.status_detail = text  # shown in the app while the receipt is being read
        db.commit()

    try:
        category_names = [
            c.name for c in db.scalars(select(Category).where(Category.user_id == receipt.user_id))
        ]
        codes = decode_codes(image)
        country_hint = user.locale.split("-")[-1] if user and "-" in user.locale else None

        def extract(problems: list[str] | None):
            return ai.extract(
                image,
                receipt.content_type,
                home_country_hint=country_hint,
                decoded_codes=codes,
                previous_problems=problems,
                categories=category_names,
            )

        # 1. Quality gate and 2. extraction run side by side; a bad photo just discards the read.
        step("Reading the receipt…")
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            quality_job = pool.submit(ai.check_quality, image, receipt.content_type)
            extract_job = pool.submit(extract, None)
            quality = quality_job.result()
            sharp = (receipt.quality or {}).get("sharpness")
            receipt.quality = {**quality.model_dump(), "sharpness": sharp}
            if not quality.is_receipt:
                return finish(ReceiptStatus.REJECTED, "This doesn't look like a receipt.")
            if not quality.readable or (sharp is not None and sharp < MIN_SHARPNESS):
                hint = (
                    quality.retake_hint
                    or "Retake the photo in good light, holding the phone steady."
                )
                return finish(ReceiptStatus.RETAKE, hint)
            extraction, model = extract_job.result()
        finally:
            # Don't make a bad photo wait for the read running beside it.
            pool.shutdown(wait=False, cancel_futures=True)

        # 3. Check; retry once with the problems spelled out.
        for attempt in range(2):
            extraction = sanitize_extraction(extraction)
            draft = build_draft(extraction)
            problems = (
                checks.check_totals(extraction)
                + checks.check_date(draft.purchased_on, date.today())
                + checks.check_tax_ids(extraction)
            )
            if not problems or attempt == 1:
                break
            log.info("receipt %s attempt %s problems: %s", receipt.id, attempt + 1, problems)
            step("Double-checking the numbers…")
            extraction, model = extract(problems)

        receipt.raw_extraction = extraction.model_dump(mode="json")
        receipt.full_text = extraction.full_text
        receipt.model_version = model
        receipt.confidence = extraction.confidence
        if not draft.merchant.name:
            problems.append("The merchant name could not be read.")

        # 4. Duplicates, 5. category, 6. currency.
        duplicate = find_duplicate(db, receipt, draft)
        if duplicate:
            receipt.duplicate_of_expense_id = duplicate.id
            first = duplicate.receipt.uploaded_at if duplicate.receipt else duplicate.created_at
            problems.append(
                f"Looks like a duplicate of {duplicate.merchant_name} on "
                f"{duplicate.purchased_on:%d %b %Y}, which you uploaded on {first:%d %b %Y}."
            )
        suggest_category(db, ai, receipt.user_id, draft, extraction.category)
        problems += convert_currency(db, user, draft)

        low = extraction.confidence < LOW_CONFIDENCE or bool(
            KEY_FIELDS & set(extraction.low_confidence_fields)
        )
        receipt.issues = problems
        receipt.draft = draft.model_dump(mode="json")
        needs_review = bool(problems) or low or draft.total is None or draft.purchased_on is None
        if quality.receipt_count > 1:
            receipt.issues = problems + ["The photo seems to contain more than one receipt."]
            needs_review = True
        return finish(
            ReceiptStatus.NEEDS_REVIEW if needs_review else ReceiptStatus.READY_TO_CONFIRM
        )
    except AIError as e:
        db.rollback()
        return finish(ReceiptStatus.FAILED, str(e))
    except Exception:
        # Anything unexpected must still end the "reading" state, or the app waits forever.
        log.exception("receipt %s failed", receipt_id)
        db.rollback()
        return finish(ReceiptStatus.FAILED, "Something went wrong while reading this receipt.")
