"""Fill the database with sample expenses and two receipts waiting in the inbox.

Lets you try the UI without an API key:  uv run python -m scripts.seed_demo
Then sign in as abc@example.com with the password demo-password-123.
"""

import io
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.ledger import create_user, save_draft
from app.models import Budget, Category, Receipt, ReceiptStatus, User
from app.pipeline.image import prepare, sha256
from app.schemas import ExpenseDraft, LineItemDraft, MerchantDraft, TaxLineDraft
from app.security import hash_password

DEMO_EMAIL = "abc@example.com"
DEMO_PASSWORD = "demo-password-123"

MERCHANTS = [
    ("ABC Fresh Mart", "Groceries", (180, 1400)),
    ("XYZ Organics", "Groceries", (400, 2600)),
    ("ABC Bistro", "Dining", (450, 1800)),
    ("XYZ Coffee House", "Dining", (250, 700)),
    ("ABC Fuel Station", "Transport & fuel", (1000, 3000)),
    ("XYZ Cabs", "Transport & fuel", (150, 600)),
    ("ABC Sports", "Shopping", (800, 4500)),
    ("XYZ Pharmacy", "Health", (120, 900)),
    ("ABC Cinemas", "Entertainment", (400, 1200)),
    ("XYZ Electricity Board", "Bills & utilities", (900, 2400)),
]


def receipt_image(lines: list[str]) -> bytes:
    font = ImageFont.load_default(size=26)
    img = Image.new("RGB", (560, 80 + 40 * len(lines)), "#fbfaf6")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((36, 40 + 40 * i), line, fill="#222", font=font)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def main() -> None:
    random.seed(7)
    settings = get_settings()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL)) or create_user(
            db, name="ABC Demo", email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD)
        )
        cats = {
            c.name: c.id for c in db.scalars(select(Category).where(Category.user_id == user.id))
        }
        today = date.today()
        for n in range(70):
            name, cat, (lo, hi) = random.choice(MERCHANTS)
            total = Decimal(random.randint(lo, hi))
            draft = ExpenseDraft(
                merchant=MerchantDraft(name=name, city="ABC City", country="IN"),
                country="IN",
                currency="INR",
                purchased_on=today - timedelta(days=random.randint(0, 85)),
                total=total,
                line_items=[LineItemDraft(description="Items", amount=total)],
                category_id=cats[cat],
                suggested_category_id=cats[cat],
                payments=[],
            )
            save_draft(db, user, draft, None)
        trip = ExpenseDraft(
            merchant=MerchantDraft(name="Café ABC", city="XYZ Ville", country="FR"),
            country="FR",
            currency="EUR",
            purchased_on=today - timedelta(days=3),
            total=Decimal("23.40"),
            tax_lines=[TaxLineDraft(name="TVA", rate_percent=Decimal(10), amount=Decimal("2.13"))],
            tax_inclusive=True,
            category_id=cats["Dining"],
            suggested_category_id=cats["Dining"],
            fx_rate=Decimal("90.50"),
            home_currency=user.home_currency,
        )
        save_draft(db, user, trip, None)
        for cat, amount in (("Groceries", 9000), ("Dining", 5000), (None, 45000)):
            db.add(
                Budget(
                    user_id=user.id, category_id=cats.get(cat) if cat else None, amount=amount * 100
                )
            )

        inbox = [
            ExpenseDraft(
                merchant=MerchantDraft(
                    name="ABC Coffee Roasters",
                    city="ABC City",
                    country="IN",
                    address="12 XYZ Road",
                    tax_ids=[{"type": "GSTIN", "value": "29ABCDE1234F1Z5"}],
                ),
                country="IN",
                currency="INR",
                purchased_on=today,
                purchased_at_time="09:12",
                receipt_number="ABC-00123",
                subtotal=Decimal(520),
                tax_lines=[
                    TaxLineDraft(name="CGST", rate_percent=Decimal("2.5"), amount=Decimal(13)),
                    TaxLineDraft(name="SGST", rate_percent=Decimal("2.5"), amount=Decimal(13)),
                ],
                total=Decimal(546),
                total_home=Decimal(546),
                home_currency="INR",
                line_items=[
                    LineItemDraft(
                        description="Cappuccino", quantity=Decimal(2), amount=Decimal(380)
                    ),
                    LineItemDraft(
                        description="Almond croissant", quantity=Decimal(1), amount=Decimal(140)
                    ),
                ],
                category_id=cats["Dining"],
                suggested_category_id=cats["Dining"],
            ),
            ExpenseDraft(
                merchant=MerchantDraft(name="XYZ Home Store", city="ABC City", country="IN"),
                country="IN",
                currency="INR",
                purchased_on=today - timedelta(days=1),
                total=Decimal(4890),
                total_home=Decimal(4890),
                home_currency="INR",
                line_items=[
                    LineItemDraft(
                        description="Bookshelf", quantity=Decimal(1), amount=Decimal(3999)
                    ),
                    LineItemDraft(description="Snacks", quantity=Decimal(1), amount=Decimal(891)),
                ],
                category_id=cats["Home"],
                suggested_category_id=cats["Home"],
                low_confidence_fields=["total"],
            ),
        ]
        issues = [[], ["Line items add up to 4890 but the subtotal is 4790."]]
        for draft, problems in zip(inbox, issues, strict=True):
            raw = receipt_image(
                [draft.merchant.name.upper(), draft.merchant.city or "", "-" * 30]
                + [f"{i.description:<22}{i.amount:>8}" for i in draft.line_items]
                + ["-" * 30, f"TOTAL{draft.total:>25}"]
            )
            prepared = prepare(raw)
            rel = f"demo/{uuid.uuid4().hex}.jpg"
            path = settings.upload_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(prepared.data)
            db.add(
                Receipt(
                    user_id=user.id,
                    image_path=rel,
                    image_hash=sha256(raw),
                    content_type="image/jpeg",
                    status=ReceiptStatus.NEEDS_REVIEW
                    if problems
                    else ReceiptStatus.READY_TO_CONFIRM,
                    draft=draft.model_dump(mode="json"),
                    issues=problems,
                    confidence=0.72 if problems else 0.96,
                )
            )
        db.commit()
        print(f"Seeded demo data. Sign in as {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
