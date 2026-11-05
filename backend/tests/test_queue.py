import threading
import time
from datetime import UTC, datetime

from app.config import get_settings
from app.db import SessionLocal
from app.models import Receipt
from app.pipeline.queue import ReaderPool, requeue_interrupted
from tests.conftest import receipt_png


class SlowAI:
    """Wraps the fake model, takes a moment per read and records how many run at once."""

    def __init__(self, inner, delay=0.4):
        self.inner, self.delay = inner, delay
        self.running = self.peak = 0
        self.lock = threading.Lock()

    def check_quality(self, *a, **k):
        return self.inner.check_quality(*a, **k)

    def categorize(self, *a, **k):
        return self.inner.categorize(*a, **k)

    def extract(self, *a, **k):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        time.sleep(self.delay)
        with self.lock:
            self.running -= 1
        return self.inner.extract(*a, **k)


def wait_until_done(client, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        receipts = client.get("/api/receipts").json()
        if receipts and all(r["status"] != "processing" for r in receipts):
            return receipts
        time.sleep(0.2)
    raise AssertionError("receipts were still being read")


def upload_batch(client, n):
    files = [("files", (f"r{i}.png", receipt_png(str(i)), "image/png")) for i in range(n)]
    resp = client.post("/api/receipts", files=files)
    assert resp.status_code == 202, resp.text
    return resp.json()


def test_a_batch_is_read_several_at_a_time(client, fake_ai, monkeypatch):
    monkeypatch.setattr(get_settings(), "process_in_background", True)
    ai = SlowAI(fake_ai)
    pool = ReaderPool()
    pool.start(3, lambda: ai, get_settings().upload_dir)
    try:
        queued = upload_batch(client, 6)
        assert all(r["status_detail"] == "Waiting in line…" for r in queued)
        receipts = wait_until_done(client)
    finally:
        pool.stop()
    assert len(receipts) == 6
    assert all(r["status"] in ("ready_to_confirm", "needs_review") for r in receipts)
    assert 1 < ai.peak <= 3


def test_reads_cut_off_by_a_restart_are_picked_up_again(client, fake_ai, monkeypatch):
    monkeypatch.setattr(get_settings(), "process_in_background", True)
    queued = upload_batch(client, 2)  # no pool running: they wait in line
    with SessionLocal() as db:
        # Pretend the previous run had started reading the first one when it stopped.
        db.get(Receipt, queued[0]["id"]).claimed_at = datetime.now(UTC)
        db.commit()
        assert requeue_interrupted(db) == 1

    pool = ReaderPool()
    pool.start(2, lambda: fake_ai, get_settings().upload_dir)
    try:
        receipts = wait_until_done(client)
    finally:
        pool.stop()
    assert {r["id"] for r in receipts} == {r["id"] for r in queued}
    assert all(r["status"] != "failed" for r in receipts)
