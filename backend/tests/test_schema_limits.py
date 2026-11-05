from anthropic.lib._parse._transform import to_json_output_format

from app.pipeline.schemas import CategoryChoice, QualityCheck, ReceiptExtraction


def _unions(node) -> int:
    if isinstance(node, dict):
        own = int("anyOf" in node or isinstance(node.get("type"), list))
        return own + sum(_unions(v) for v in node.values())
    if isinstance(node, list):
        return sum(_unions(v) for v in node)
    return 0


def test_schemas_stay_under_the_api_union_limit():
    # The API rejects structured-output schemas with more than 16 nullable/union fields.
    for model in (ReceiptExtraction, QualityCheck, CategoryChoice):
        assert _unions(to_json_output_format(model)["schema"]) <= 16, model.__name__


def test_blank_text_and_zero_fees_read_back_as_none():
    data = {
        "country_code": "",
        "language": "en",
        "currency": "USD",
        "document_type": "",
        "receipt_number": " ",
        "order_number": "",
        "purchase_date": "2026-10-01",
        "purchase_date_as_printed": "",
        "purchase_time": "",
        "order_type": "",
        "table_number": "",
        "guests": 0,
        "cashier": "",
        "terminal_id": "",
        "merchant": {
            "name": "ABC Store",
            **{k: "" for k in ("legal_name", "branch", "address", "city", "postcode")},
            **{k: "" for k in ("country_code", "phone", "email", "website")},
            "tax_ids": [],
            "registrations": [],
        },
        "customer": {
            k: ""
            for k in (
                "name",
                "phone",
                "email",
                "billing_address",
                "delivery_address",
                "loyalty_id",
                "tax_id",
            )
        },
        "line_items": [],
        "subtotal": None,
        "tax_lines": [],
        "tax_inclusive": None,
        **{
            k: 0
            for k in (
                "service_charge",
                "delivery_fee",
                "packaging_fee",
                "tip",
                "discount_total",
                "rounding",
            )
        },
        "total": 10.5,
        "amount_tendered": None,
        "change_given": None,
        "payments": [],
        "warranty_until": "",
        "return_by": "",
        "qr_and_barcodes": [],
        "extras": [],
        "full_text": "ABC Store",
        "confidence": 0.9,
        "low_confidence_fields": [],
        "notes": "",
        "category": "",
    }
    r = ReceiptExtraction.model_validate(data)
    assert r.receipt_number is None and r.merchant.phone is None and r.category is None
    assert r.tip is None and r.guests is None and r.total == 10.5
