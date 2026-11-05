import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import auth, expenses, receipts, settings, summary
from app.config import get_settings
from app.db import SessionLocal
from app.deps import current_user, get_ai
from app.pipeline.queue import pool, requeue_interrupted
from app.security import SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO)

config = get_settings()
log = logging.getLogger(__name__)
if not (config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")):
    log.warning("ANTHROPIC_API_KEY is not set: receipts can't be read until it is.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as db:
        resumed = requeue_interrupted(db)
    if resumed:
        log.info("put %s interrupted receipt(s) back in line", resumed)
    if config.process_in_background:
        pool.start(config.reader_workers, get_ai, config.upload_dir)
    yield
    pool.stop()


app = FastAPI(title="Expense Tracker", version="0.1.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware, hsts=config.hsts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(auth.router)
protected = [Depends(current_user)]
for module in (receipts, expenses, settings, summary):
    app.include_router(module.router, dependencies=protected)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


def serve_web_app(app: FastAPI, root: Path) -> None:
    """Serve the built frontend; any page that isn't a file gets index.html so routes work."""
    root = root.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            # Vite fingerprints everything under assets/, so it can be cached for good.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else None
            return FileResponse(file, headers={"Cache-Control": cache} if cache else None)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})


if config.static_dir and (config.static_dir / "index.html").is_file():
    serve_web_app(app, config.static_dir)
