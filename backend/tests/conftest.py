import io
import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://expense:expense@localhost:5432/expense_test"
)
os.environ["PROCESS_IN_BACKGROUND"] = "false"
TEST_EMAIL = "abc@example.com"
TEST_PASSWORD = "correct horse battery staple"

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api.auth import login_limiter
from app.api.receipts import ai_limiter
from app.config import get_settings
from app.db import Base, engine
from app.deps import get_ai
from app.main import app
from app.pipeline import fx
from app.pipeline.schemas import (
    CategoryChoice,
    CustomerInfo,
    LineItemOut,
    MerchantInfo,
    QualityCheck,
    ReceiptExtraction,
    TaxId,
    TaxLine,
)


def make_extraction(**overrides) -> ReceiptExtraction:
    data = {
        "country_code": "IN",
        "language": "en",
        "currency": "INR",
        "document_type": "tax_invoice",
        "receipt_number": "INV-1042",
        "order_number": None,
        "purchase_date": "2026-10-20",
        "purchase_date_as_printed": "20/10/2026",
        "purchase_time": "19:42",
        "order_type": "in_store",
        "table_number": None,
        "guests": None,
        "cashier": "Ravi",
        "terminal_id": None,
        "merchant": MerchantInfo(
            name="ABC Fresh Mart",
            legal_name="ABC Retail Ltd",
            branch="Indiranagar",
            address="12 XYZ Road, ABC City",
            city="ABC City",
            postcode="560038",
            country_code="IN",
            phone=None,
            email=None,
            website=None,
            tax_ids=[TaxId(type="GSTIN", value="29AABCR1718E1ZL")],
            registrations=[],
        ),
        "customer": CustomerInfo(
            name="Customer ABC",
            phone=None,
            email=None,
            billing_address=None,
            delivery_address=None,
            loyalty_id="LOY-77",
            tax_id=None,
        ),
        "line_items": [
            LineItemOut(
                description="Milk 1L",
                description_en=None,
                sku=None,
                hsn_sac_code="0401",
                quantity=2,
                unit="pcs",
                unit_price=60,
                discount=None,
                tax_rate_percent=5,
                amount=120,
            ),
            LineItemOut(
                description="Bread",
                description_en=None,
                sku=None,
                hsn_sac_code=None,
                quantity=1,
                unit="pcs",
                unit_price=50,
                discount=None,
                tax_rate_percent=5,
                amount=50,
            ),
        ],
        "subtotal": 170,
        "tax_lines": [
            TaxLine(name="CGST", rate_percent=2.5, taxable_amount=170, amount=4.25),
            TaxLine(name="SGST", rate_percent=2.5, taxable_amount=170, amount=4.25),
        ],
        "tax_inclusive": False,
        "service_charge": None,
        "delivery_fee": None,
        "packaging_fee": None,
        "tip": None,
        "discount_total": None,
        "rounding": 0.5,
        "total": 179,
        "amount_tendered": None,
        "change_given": None,
        "payments": [],
        "warranty_until": None,
        "return_by": None,
        "qr_and_barcodes": [],
        "extras": [],
        "full_text": "ABC FRESH MART\nMilk 1L 2 x 60.00 120.00\nBread 50.00\nTOTAL 179.00",
        "confidence": 0.95,
        "low_confidence_fields": [],
        "notes": None,
    }
    data.update(overrides)
    return ReceiptExtraction(**data)


class FakeAI:
    def __init__(self):
        self.quality = QualityCheck(
            is_receipt=True, readable=True, receipt_count=1, issues=[], retake_hint=None
        )
        self.extractions: list[ReceiptExtraction] = [make_extraction()]
        self.category = "Groceries"
        self.extract_calls = 0
        self.categorize_calls = 0

    def check_quality(self, image, media_type):
        return self.quality

    def extract(
        self,
        image,
        media_type,
        *,
        home_country_hint,
        decoded_codes,
        previous_problems=None,
        categories=None,
    ):
        result = self.extractions[min(self.extract_calls, len(self.extractions) - 1)]
        self.extract_calls += 1
        return result, "fake-model"

    def categorize(self, merchant, items, categories):
        self.categorize_calls += 1
        return CategoryChoice(category=self.category, item_categories=[])


def receipt_png(tag: str = "") -> bytes:
    """A receipt-like image; a different tag gives a different photo of the same receipt."""
    img = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 10), tag, fill="black")
    for y in range(40, 860, 28):
        draw.text((40, y), "ITEM 123.45   ABC FRESH MART  TOTAL 179.00", fill="black")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def fake_ai():
    return FakeAI()


@pytest.fixture
def client(fake_ai, tmp_path):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    get_settings().upload_dir = tmp_path
    app.dependency_overrides[get_ai] = lambda: fake_ai
    ai_limiter.reset()
    fx.forget_misses()
    login_limiter.reset()
    with TestClient(app) as c:
        resp = c.post(
            "/api/auth/signup",
            json={"name": "ABC User", "email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 201, resp.text
        yield c
    app.dependency_overrides.clear()


def upload(client, data: bytes | None = None):
    resp = client.post(
        "/api/receipts", files=[("files", ("r.png", data or receipt_png(), "image/png"))]
    )
    assert resp.status_code == 202, resp.text
    return resp.json()[0]
