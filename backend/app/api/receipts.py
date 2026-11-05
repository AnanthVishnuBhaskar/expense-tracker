import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import get_settings
from app.deps import AI, DB, CurrentUser
from app.ledger import expense_out, save_draft
from app.models import Receipt, ReceiptStatus
from app.pipeline.image import UnsupportedImage, prepare, sha256
from app.pipeline.process import process_receipt
from app.pipeline.queue import WAITING, pool
from app.schemas import ExpenseDraft, ExpenseOut, ReceiptOut
from app.security import RateLimiter, client_key

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Every processed photo costs Claude calls, so uploads and retries share one budget.
ai_limiter = RateLimiter(get_settings().uploads_per_hour, 3600)
OPEN_STATUSES = [
    ReceiptStatus.PROCESSING,
    ReceiptStatus.READY_TO_CONFIRM,
    ReceiptStatus.NEEDS_REVIEW,
    ReceiptStatus.RETAKE,
    ReceiptStatus.FAILED,
]


def _out(r: Receipt, already_uploaded: bool = False) -> ReceiptOut:
    out = ReceiptOut.model_validate(r)
    out.expense_id = r.expense.id if r.expense else None
    out.already_uploaded = already_uploaded
    return out


def _same_photo(db: DB, user_id: int, image_hash: str) -> Receipt | None:
    """An earlier upload of this exact photo that's saved or still waiting for review."""
    return db.scalar(
        select(Receipt)
        .where(
            Receipt.user_id == user_id,
            Receipt.image_hash == image_hash,
            Receipt.status.not_in(
                [ReceiptStatus.DISCARDED, ReceiptStatus.REJECTED, ReceiptStatus.FAILED]
            ),
        )
        .order_by(Receipt.uploaded_at)
        .limit(1)
    )


def delete_image(receipt: Receipt) -> None:
    """Remove the stored photo; the receipt row stays as a record of what happened."""
    (get_settings().upload_dir / receipt.image_path).unlink(missing_ok=True)


def _get(db: DB, user_id: int, receipt_id: int) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if receipt is None or receipt.user_id != user_id:
        raise HTTPException(404, "Receipt not found")
    return receipt


@router.post("", response_model=list[ReceiptOut], status_code=202)
async def upload_receipts(
    request: Request,
    files: list[UploadFile],
    db: DB,
    user: CurrentUser,
    ai: AI,
) -> list[ReceiptOut]:
    settings = get_settings()
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(413, f"Upload at most {settings.max_files_per_upload} photos at a time")
    ai_limiter.hit(client_key(request), cost=len(files))
    created: list[Receipt] = []
    # In upload order; an exact repeat returns the earlier receipt, flagged as already uploaded.
    results: list[tuple[Receipt, bool]] = []
    for file in files:
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{file.filename} is larger than 20 MB")
        earlier = _same_photo(db, user.id, sha256(raw)) or next(
            (r for r in created if r.image_hash == sha256(raw)), None
        )
        if earlier:
            # The exact same photo again: don't read (or pay for) it twice, just say so.
            results.append((earlier, True))
            continue
        try:
            prepared = prepare(raw)
        except UnsupportedImage as e:
            raise HTTPException(415, f"{file.filename}: {e}") from e
        now = datetime.now(UTC)
        rel = f"{now:%Y/%m}/{uuid.uuid4().hex}.jpg"
        path = settings.upload_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(prepared.data)
        receipt = Receipt(
            user_id=user.id,
            image_path=rel,
            image_hash=sha256(raw),
            content_type=prepared.media_type,
            status=ReceiptStatus.PROCESSING,
            status_detail=WAITING,
            quality={"sharpness": prepared.sharpness},
            issues=[],
        )
        db.add(receipt)
        created.append(receipt)
        results.append((receipt, False))
    db.commit()
    if settings.process_in_background:
        pool.wake()
    else:
        for receipt in created:
            process_receipt(db, ai, receipt.id, settings.upload_dir)
    return [_out(r, already_uploaded=again) for r, again in results]


@router.get("", response_model=list[ReceiptOut])
def list_receipts(db: DB, user: CurrentUser, status: str | None = None) -> list[ReceiptOut]:
    query = select(Receipt).where(Receipt.user_id == user.id).order_by(Receipt.uploaded_at.desc())
    if status == "open":
        query = query.where(Receipt.status.in_(OPEN_STATUSES))
    elif status:
        query = query.where(Receipt.status == status)
    return [_out(r) for r in db.scalars(query.limit(200))]


@router.get("/{receipt_id}", response_model=ReceiptOut)
def get_receipt(receipt_id: int, db: DB, user: CurrentUser) -> ReceiptOut:
    return _out(_get(db, user.id, receipt_id))


@router.get("/{receipt_id}/image")
def receipt_image(receipt_id: int, db: DB, user: CurrentUser) -> FileResponse:
    receipt = _get(db, user.id, receipt_id)
    path = get_settings().upload_dir / receipt.image_path
    if not path.is_file():
        raise HTTPException(404, "The photo for this receipt was deleted")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/{receipt_id}/confirm", response_model=ExpenseOut)
def confirm_receipt(receipt_id: int, draft: ExpenseDraft, db: DB, user: CurrentUser) -> ExpenseOut:
    receipt = _get(db, user.id, receipt_id)
    if receipt.status not in (ReceiptStatus.READY_TO_CONFIRM, ReceiptStatus.NEEDS_REVIEW):
        raise HTTPException(409, f"Receipt is {receipt.status}, it can't be confirmed")
    try:
        expense = save_draft(db, user, draft, receipt)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    receipt.status = ReceiptStatus.SAVED
    receipt.draft = draft.model_dump(mode="json")
    db.commit()
    db.refresh(expense)
    return expense_out(expense)


@router.post("/{receipt_id}/discard", response_model=ReceiptOut)
def discard_receipt(receipt_id: int, db: DB, user: CurrentUser) -> ReceiptOut:
    receipt = _get(db, user.id, receipt_id)
    if receipt.status == ReceiptStatus.SAVED:
        raise HTTPException(409, "Receipt is already saved; delete the expense instead")
    receipt.status = ReceiptStatus.DISCARDED
    receipt.draft = None
    receipt.raw_extraction = None
    receipt.full_text = None
    db.commit()
    delete_image(receipt)
    return _out(receipt)


@router.post("/{receipt_id}/retry", response_model=ReceiptOut, status_code=202)
def retry_receipt(
    receipt_id: int,
    request: Request,
    db: DB,
    user: CurrentUser,
    ai: AI,
) -> ReceiptOut:
    receipt = _get(db, user.id, receipt_id)
    ai_limiter.hit(client_key(request))
    if receipt.status in (ReceiptStatus.SAVED, ReceiptStatus.DISCARDED):
        raise HTTPException(409, f"Receipt is already {receipt.status}")
    if pool.is_reading(receipt.id):
        raise HTTPException(409, "This receipt is being read right now")
    receipt.status = ReceiptStatus.PROCESSING
    receipt.status_detail = WAITING
    receipt.claimed_at = None
    receipt.issues = []
    db.commit()
    if get_settings().process_in_background:
        pool.wake()
    else:
        process_receipt(db, ai, receipt.id, get_settings().upload_dir)
    return _out(receipt)
