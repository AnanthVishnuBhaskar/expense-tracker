from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.currency import country_for, currency_for
from app.deps import DB, CurrentUser
from app.models import Budget, Category, Expense, User
from app.money import from_minor, to_minor
from app.pipeline import fx
from app.schemas import (
    BudgetIn,
    BudgetOut,
    CategoryIn,
    CategoryOut,
    DetectIn,
    SettingsIn,
    SettingsOut,
)

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
def get_settings_(user: CurrentUser) -> SettingsOut:
    return SettingsOut.model_validate(user)


def _switch_home_currency(db: DB, user: User, new: str) -> None:
    """Re-express every expense and budget in the new home currency, so totals stay comparable."""
    old = user.home_currency
    if new == old:
        return
    # Fetch the budget rate first, so a failed lookup changes nothing.
    budgets = db.scalars(select(Budget).where(Budget.user_id == user.id)).all()
    budget_rate = fx.get_rate(db, date.today(), old, new) if budgets else None
    if budgets and budget_rate is None:
        raise HTTPException(
            503, f"Couldn't get a {old} to {new} exchange rate right now. Try again in a bit."
        )
    for e in db.scalars(select(Expense).where(Expense.user_id == user.id)):
        rate = fx.get_rate(db, e.purchased_on, e.currency, new)
        e.home_currency = new
        e.fx_rate = rate
        e.total_home = to_minor(from_minor(e.total, e.currency) * rate, new) if rate else None
    for b in budgets:
        b.amount = to_minor(from_minor(b.amount, old) * budget_rate, new)
    user.home_currency = new


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsIn, db: DB, user: CurrentUser) -> SettingsOut:
    changes = body.model_dump(exclude_none=True)
    if new := changes.pop("home_currency", None):
        _switch_home_currency(db, user, new.upper())
        user.home_currency_source = "user"
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    return SettingsOut.model_validate(user)


@router.post("/settings/detect", response_model=SettingsOut)
def detect_settings(body: DetectIn, db: DB, user: CurrentUser) -> SettingsOut:
    """Called by the app on load: fills in time zone, locale and home currency until the user
    picks a currency themselves."""
    if body.timezone:
        user.timezone = body.timezone
    if body.locale:
        user.locale = body.locale
    if user.home_currency_source == "default":
        detected = currency_for(country_for(body.timezone, body.locale))
        if detected:
            _switch_home_currency(db, user, detected)
            user.home_currency_source = "detected"
    db.commit()
    return SettingsOut.model_validate(user)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: DB, user: CurrentUser) -> list[CategoryOut]:
    rows = db.scalars(select(Category).where(Category.user_id == user.id).order_by(Category.id))
    return [CategoryOut.model_validate(c) for c in rows]


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, db: DB, user: CurrentUser) -> CategoryOut:
    category = Category(user_id=user.id, **body.model_dump())
    db.add(category)
    db.commit()
    return CategoryOut.model_validate(category)


@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(db: DB, user: CurrentUser) -> list[BudgetOut]:
    rows = db.scalars(select(Budget).where(Budget.user_id == user.id))
    return [
        BudgetOut(
            id=b.id, category_id=b.category_id, amount=from_minor(b.amount, user.home_currency)
        )
        for b in rows
    ]


@router.put("/budgets", response_model=BudgetOut)
def set_budget(body: BudgetIn, db: DB, user: CurrentUser) -> BudgetOut:
    """Create or update the monthly budget for a category (or overall when category_id is null)."""
    if body.category_id is not None:
        cat = db.get(Category, body.category_id)
        if cat is None or cat.user_id != user.id:
            raise HTTPException(404, "Category not found")
    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category_id.is_(None)
            if body.category_id is None
            else Budget.category_id == body.category_id,
            Budget.period == "month",
        )
    )
    if budget is None:
        budget = Budget(user_id=user.id, category_id=body.category_id, period="month", amount=0)
        db.add(budget)
    budget.amount = to_minor(body.amount, user.home_currency)
    db.commit()
    return BudgetOut(id=budget.id, category_id=budget.category_id, amount=body.amount)


@router.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: int, db: DB, user: CurrentUser) -> None:
    budget = db.get(Budget, budget_id)
    if budget is None or budget.user_id != user.id:
        raise HTTPException(404, "Budget not found")
    db.delete(budget)
    db.commit()
