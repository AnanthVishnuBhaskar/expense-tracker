"""social sign-in (Google, Microsoft, Apple)

Revision ID: c4d8e2f6a1b3
Revises: b7e3c1a9d2f4
Create Date: 2026-11-05 07:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d8e2f6a1b3"
down_revision: str | Sequence[str] | None = "b7e3c1a9d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_logins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_social_logins_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_social_logins"),
        sa.UniqueConstraint("provider", "subject", name="uq_social_logins_provider"),
    )
    op.create_index("ix_social_logins_user_id", "social_logins", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_social_logins_user_id", table_name="social_logins")
    op.drop_table("social_logins")
