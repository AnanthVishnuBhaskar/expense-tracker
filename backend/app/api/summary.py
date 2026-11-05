from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.receipts import OPEN_STATUSES
from app.deps import DB, CurrentUser
from app.ledger import PERIODS, month_bounds, period_bounds
from app.models import Budget, Category, Expense, Receipt
from app.money import from_minor
from app.schemas import (
    CategorySpend,
    DaySpend,
    Insight,
    MonthSummary,
    MonthTotal,
    UnconvertedSpend,
    YearOverview,
)

router = APIRouter(prefix="/api/summary", tags=["summary"])


def _shift_month(month: str, delta: int) -> str:
    year, mon = (int(p) for p in month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _spend_by_category(db: DB, user_id: int, month: str) -> dict[int | None, int]:
    start, end = month_bounds(month)
    rows = db.execute(
        select(Expense.category_id, func.coalesce(func.sum(Expense.total_home), 0))
        .where(
            Expense.user_id == user_id, Expense.purchased_on >= start, Expense.purchased_on < end
        )
        .group_by(Expense.category_id)
    )
    return {cat: int(total) for cat, total in rows}


def _pct(part: Decimal, whole: Decimal) -> int:
    return int(part / whole * 100) if whole else 0


@router.get("/months", response_model=YearOverview)
def year_overview(db: DB, user: CurrentUser, year: int | None = None) -> YearOverview:
    """Spend per month for one year, for the month picker."""
    year = year or date.today().year
    month_col = func.date_trunc("month", Expense.purchased_on)
    rows = db.execute(
        select(month_col, func.coalesce(func.sum(Expense.total_home), 0), func.count())
        .where(
            Expense.user_id == user.id,
            Expense.purchased_on >= date(year, 1, 1),
            Expense.purchased_on < date(year + 1, 1, 1),
        )
        .group_by(month_col)
    )
    totals = {m.month: (int(total), count) for m, total, count in rows}
    first = db.scalar(select(func.min(Expense.purchased_on)).where(Expense.user_id == user.id))
    return YearOverview(
        year=year,
        home_currency=user.home_currency,
        first_month=first.strftime("%Y-%m") if first else None,
        months=[
            MonthTotal(
                month=f"{year:04d}-{m:02d}",
                total=from_minor(totals.get(m, (0, 0))[0], user.home_currency),
                count=totals.get(m, (0, 0))[1],
            )
            for m in range(1, 13)
        ],
    )


def first_expense_date(db: DB, user_id: int) -> date | None:
    return db.scalar(select(func.min(Expense.purchased_on)).where(Expense.user_id == user_id))


def _total_between(db: DB, user_id: int, start: date, end: date) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Expense.total_home), 0)).where(
                Expense.user_id == user_id,
                Expense.purchased_on >= start,
                Expense.purchased_on < end,
            )
        )
    )


@router.get("", response_model=MonthSummary)
def month_summary(
    db: DB, user: CurrentUser, month: str | None = None, period: str = "month"
) -> MonthSummary:
    month = month or date.today().strftime("%Y-%m")
    cur = user.home_currency
    period = period if period in PERIODS else "month"
    start, end, months = period_bounds(period, month, first_expense_date(db, user.id))
    single = period == "month"

    def money(minor: int | None) -> Decimal:
        return from_minor(minor or 0, cur)

    expenses = db.scalars(
        select(Expense).where(
            Expense.user_id == user.id, Expense.purchased_on >= start, Expense.purchased_on < end
        )
    ).all()
    categories = {c.id: c for c in db.scalars(select(Category).where(Category.user_id == user.id))}
    budgets = {
        b.category_id: b.amount for b in db.scalars(select(Budget).where(Budget.user_id == user.id))
    }

    by_cat: dict[int | None, list[int]] = defaultdict(lambda: [0, 0])
    by_day: dict[date, int] = defaultdict(int)
    by_merchant: dict[str, list] = defaultdict(lambda: [0, 0])
    unconverted: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    # Long periods chart one point per month; a month or a quarter charts each day.
    bucket = "day" if months <= 3 else "month"
    if bucket == "month":
        cursor = start
        while cursor < end:
            by_day[cursor] = 0
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    for e in expenses:
        if e.total_home is None:
            unconverted[e.currency][0] += e.total or 0
            unconverted[e.currency][1] += 1
        amount = e.total_home or 0
        by_cat[e.category_id][0] += amount
        by_cat[e.category_id][1] += 1
        by_day[e.purchased_on if bucket == "day" else e.purchased_on.replace(day=1)] += amount
        by_merchant[e.merchant_name][0] += amount
        by_merchant[e.merchant_name][1] += 1
    total = sum(v[0] for v in by_cat.values())

    if single:
        prev_total = sum(_spend_by_category(db, user.id, _shift_month(month, -1)).values())
        history = [_spend_by_category(db, user.id, _shift_month(month, -i)) for i in (1, 2, 3)]
    else:
        # The same number of months just before this period ("all" has nothing before it).
        prev_start = date.fromisoformat(_shift_month(start.strftime("%Y-%m"), -months) + "-01")
        prev_total = 0 if period == "all" else _total_between(db, user.id, prev_start, start)
        history = []
    # Budgets are monthly, so a longer period gets one budget per month in it.
    budgets = {k: v * months for k, v in budgets.items()}

    spends = []
    for cat_id, (spent, count) in sorted(by_cat.items(), key=lambda kv: -kv[1][0]):
        cat = categories.get(cat_id)
        spends.append(
            CategorySpend(
                category_id=cat_id,
                name=cat.name if cat else "Uncategorized",
                color=cat.color if cat else None,
                icon=cat.icon if cat else None,
                spent=money(spent),
                budget=money(budgets[cat_id]) if cat_id in budgets else None,
                count=count,
            )
        )
    # Show budgeted categories with no spend yet too.
    for cat_id, amount in budgets.items():
        if cat_id is not None and cat_id not in by_cat and cat_id in categories:
            cat = categories[cat_id]
            spends.append(
                CategorySpend(
                    category_id=cat_id,
                    name=cat.name,
                    color=cat.color,
                    icon=cat.icon,
                    spent=Decimal(0),
                    budget=money(amount),
                    count=0,
                )
            )

    span = "this month" if single else f"these {months} months"
    previous_span = "last month" if single else f"the {months} months before"
    insights: list[Insight] = []
    overall = budgets.get(None)
    if overall:
        pct = _pct(Decimal(total), Decimal(overall))
        if pct >= 80:
            insights.append(
                Insight(
                    kind="budget",
                    severity="critical" if pct >= 100 else "warning",
                    message=f"You've used {pct}% of the overall budget for {span}.",
                )
            )
    for s in spends:
        if s.budget:
            pct = _pct(s.spent, s.budget)
            if pct >= 80:
                insights.append(
                    Insight(
                        kind="budget",
                        severity="critical" if pct >= 100 else "warning",
                        message=f"{s.name} is at {pct}% of its budget.",
                    )
                )
        avg = sum(h.get(s.category_id, 0) for h in history) / 3 if history else 0
        if avg and s.spent > money(int(avg)) * Decimal("1.5") and s.count >= 2:
            ratio = s.spent / money(int(avg))
            insights.append(
                Insight(
                    kind="unusual",
                    severity="info",
                    message=f"{s.name} spending is {ratio:.1f}x your 3-month average.",
                )
            )
    if prev_total and total:
        change = _pct(Decimal(total - prev_total), Decimal(prev_total))
        if abs(change) >= 10:
            direction = "more" if change > 0 else "less"
            insights.append(
                Insight(
                    kind="info",
                    severity="info",
                    message=f"You've spent {abs(change)}% {direction} than {previous_span}"
                    + (" so far." if single or end > date.today() else "."),
                )
            )
    soon = date.today() + timedelta(days=14)
    for e in db.scalars(
        select(Expense).where(
            Expense.user_id == user.id, Expense.return_by >= date.today(), Expense.return_by <= soon
        )
    ):
        insights.append(
            Insight(
                kind="info",
                severity="warning",
                message=f"Return window for {e.merchant_name} closes on {e.return_by:%d %b}.",
            )
        )

    pending = db.scalar(
        select(func.count(Receipt.id)).where(
            Receipt.user_id == user.id, Receipt.status.in_(OPEN_STATUSES)
        )
    )
    top = sorted(by_merchant.items(), key=lambda kv: -kv[1][0])[:5]
    return MonthSummary(
        month=month,
        period=period,
        start=start,
        end=end - timedelta(days=1),
        bucket=bucket,
        home_currency=cur,
        total=money(total),
        previous_total=money(prev_total),
        budget=money(overall) if overall else None,
        count=len(expenses),
        by_category=spends,
        by_day=[DaySpend(day=d, spent=money(v)) for d, v in sorted(by_day.items())],
        top_merchants=[{"name": n, "spent": str(money(v[0])), "count": v[1]} for n, v in top],
        insights=insights,
        pending_receipts=pending or 0,
        unconverted=[
            UnconvertedSpend(currency=c, total=from_minor(t, c), count=n)
            for c, (t, n) in sorted(unconverted.items())
        ],
    )
