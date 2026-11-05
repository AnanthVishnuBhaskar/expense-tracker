import csv
import io
from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.api.receipts import delete_image
from app.api.summary import first_expense_date
from app.deps import DB, CurrentUser
from app.ledger import PERIODS, expense_out, month_bounds, own_category, period_bounds, save_draft
from app.models import Expense, Receipt, ReceiptStatus
from app.money import from_minor, to_minor
from app.pipeline import fx
from app.schemas import ExpenseDraft, ExpenseOut

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


def _query(
    user_id: int,
    month: str | None,
    category_id: int | None,
    q: str | None,
    bounds: tuple[date, date] | None = None,
):
    query = (
        select(Expense)
        .where(Expense.user_id == user_id)
        .options(
            selectinload(Expense.line_items),
            selectinload(Expense.category),
            selectinload(Expense.merchant),
        )
        .order_by(Expense.purchased_on.desc(), Expense.id.desc())
    )
    if month and not bounds:
        bounds = month_bounds(month)
    if bounds:
        query = query.where(Expense.purchased_on >= bounds[0], Expense.purchased_on < bounds[1])
    if category_id:
        query = query.where(Expense.category_id == category_id)
    if q:
        like = f"%{q}%"
        query = query.outerjoin(Receipt, Expense.receipt_id == Receipt.id).where(
            or_(Expense.merchant_name.ilike(like), Receipt.full_text.ilike(like))
        )
    return query


def _period(db: DB, user_id: int, month: str | None, period: str) -> tuple[date, date] | None:
    """Bounds for a longer period, or None to use the month."""
    if period not in PERIODS or period == "month":
        return None
    start, end, _ = period_bounds(period, month or "", first_expense_date(db, user_id))
    return start, end


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    db: DB,
    user: CurrentUser,
    month: str | None = None,
    category_id: int | None = None,
    q: str | None = None,
    period: str = "month",
) -> list[ExpenseOut]:
    query = _query(user.id, month, category_id, q, _period(db, user.id, month, period))
    return [expense_out(e) for e in db.scalars(query.limit(1000))]


@router.post("", response_model=ExpenseOut, status_code=201)
def create_manual_expense(draft: ExpenseDraft, db: DB, user: CurrentUser) -> ExpenseOut:
    try:
        expense = save_draft(db, user, draft, None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    db.refresh(expense)
    return expense_out(expense)


@router.get("/export.csv")
def export_csv(
    db: DB, user: CurrentUser, month: str | None = None, period: str = "month"
) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "date",
            "merchant",
            "category",
            "currency",
            "total",
            "home_currency",
            "total_home",
            "tax",
            "payment",
            "receipt_number",
            "country",
        ]
    )
    for e in db.scalars(_query(user.id, month, None, None, _period(db, user.id, month, period))):
        writer.writerow(
            [
                e.purchased_on.isoformat(),
                e.merchant_name,
                e.category.name if e.category else "",
                e.currency,
                from_minor(e.total, e.currency),
                e.home_currency,
                from_minor(e.total_home, e.home_currency) or "",
                from_minor(e.tax_total, e.currency) or "",
                e.payments[0].get("method") if e.payments else "",
                e.receipt_number or "",
                e.country or "",
            ]
        )
    name = f"expenses-{month or 'all'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/reconvert")
def reconvert(db: DB, user: CurrentUser) -> dict:
    """Try again to convert expenses that had no exchange rate when they were saved."""
    fx.forget_misses()
    fixed = 0
    for e in db.scalars(
        select(Expense).where(Expense.user_id == user.id, Expense.total_home.is_(None))
    ):
        rate = fx.get_rate(db, e.purchased_on, e.currency, user.home_currency)
        if rate is not None:
            e.home_currency, e.fx_rate = user.home_currency, rate
            e.total_home = to_minor(from_minor(e.total, e.currency) * rate, user.home_currency)
            fixed += 1
    db.commit()
    return {"converted": fixed}


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: DB, user: CurrentUser) -> ExpenseOut:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.user_id != user.id:
        raise HTTPException(404, "Expense not found")
    return expense_out(expense)


@router.patch("/{expense_id}/category", response_model=ExpenseOut)
def set_category(expense_id: int, category_id: int, db: DB, user: CurrentUser) -> ExpenseOut:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.user_id != user.id:
        raise HTTPException(404, "Expense not found")
    try:
        expense.category_id = own_category(db, user.id, category_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    db.refresh(expense)
    return expense_out(expense)


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: DB, user: CurrentUser) -> None:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.user_id != user.id:
        raise HTTPException(404, "Expense not found")
    receipt = expense.receipt
    if receipt:
        receipt.status = ReceiptStatus.DISCARDED
        receipt.draft = receipt.raw_extraction = receipt.full_text = None
    db.delete(expense)
    db.commit()
    if receipt:
        delete_image(receipt)
