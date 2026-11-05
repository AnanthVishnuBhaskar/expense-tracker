"""Reads waiting receipts with a small pool of threads, using the receipts table as the queue.

A receipt waits in line while its status is "processing" and claimed_at is empty. Because the
queue lives in Postgres, receipts uploaded before a restart are picked up again afterwards.
Designed for a single server process.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Receipt, ReceiptStatus
from app.pipeline.ai import ReceiptAI
from app.pipeline.process import process_receipt

log = logging.getLogger(__name__)

WAITING = "Waiting in line…"
IDLE_POLL_SECONDS = 5.0


def claim_next(db: Session) -> int | None:
    """Take the oldest waiting receipt; SKIP LOCKED keeps two readers off the same one."""
    receipt = db.scalar(
        select(Receipt)
        .where(Receipt.status == ReceiptStatus.PROCESSING, Receipt.claimed_at.is_(None))
        .order_by(Receipt.uploaded_at, Receipt.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if receipt is None:
        db.rollback()
        return None
    receipt.claimed_at = datetime.now(UTC)
    db.commit()
    return receipt.id


def requeue_interrupted(db: Session) -> int:
    """At startup: anything claimed by the previous run was cut off, so put it back in line."""
    count = db.execute(
        update(Receipt)
        .where(Receipt.status == ReceiptStatus.PROCESSING, Receipt.claimed_at.is_not(None))
        .values(claimed_at=None, status_detail=WAITING)
    ).rowcount
    db.commit()
    return count


class ReaderPool:
    def __init__(self) -> None:
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._in_flight: set[int] = set()
        self._lock = threading.Lock()

    def start(self, workers: int, get_ai: Callable[[], ReceiptAI], upload_dir: Path) -> None:
        self._stop.clear()
        for n in range(workers):
            t = threading.Thread(
                target=self._loop, args=(get_ai, upload_dir), name=f"reader-{n}", daemon=True
            )
            t.start()
            self._threads.append(t)
        self.wake()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()

    def wake(self) -> None:
        """New work arrived: stop idling and check the queue."""
        self._wake.set()

    def is_reading(self, receipt_id: int) -> bool:
        with self._lock:
            return receipt_id in self._in_flight

    def _loop(self, get_ai: Callable[[], ReceiptAI], upload_dir: Path) -> None:
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    receipt_id = claim_next(db)
                    if receipt_id is None:
                        self._wake.wait(IDLE_POLL_SECONDS)
                        self._wake.clear()
                        continue
                    with self._lock:
                        self._in_flight.add(receipt_id)
                    try:
                        process_receipt(db, get_ai(), receipt_id, upload_dir)
                    finally:
                        with self._lock:
                            self._in_flight.discard(receipt_id)
            except Exception:
                # process_receipt records its own failures; this only guards the loop itself.
                log.exception("reader loop error")
                self._stop.wait(1)


pool = ReaderPool()
