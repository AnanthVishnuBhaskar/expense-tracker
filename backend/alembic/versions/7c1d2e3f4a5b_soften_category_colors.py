"""soften default category colors

Revision ID: 7c1d2e3f4a5b
Revises: 55e9b1ccd8e0
Create Date: 2026-10-29 13:55:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1d2e3f4a5b"
down_revision: str | Sequence[str] | None = "55e9b1ccd8e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Old default -> new default. Colors a user picked themselves are left alone.
COLORS = {
    "#22c55e": "#5f9a78",
    "#f97316": "#cf8a5c",
    "#3b82f6": "#5c84b0",
    "#ec4899": "#c27996",
    "#eab308": "#c4a04f",
    "#ef4444": "#c26a68",
    "#a855f7": "#8b7bb5",
    "#06b6d4": "#4f969e",
    "#6366f1": "#6d76b3",
    "#84cc16": "#8a9a5b",
    "#f472b6": "#c48aa8",
    "#14b8a6": "#4f9a8a",
    "#94a3b8": "#9a958e",
}


def _swap(pairs: dict[str, str]) -> None:
    stmt = sa.text("UPDATE categories SET color = :new WHERE color = :old")
    for old, new in pairs.items():
        op.execute(stmt.bindparams(old=old, new=new))


def upgrade() -> None:
    _swap(COLORS)


def downgrade() -> None:
    _swap({new: old for old, new in COLORS.items()})
