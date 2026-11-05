from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import serve_web_app
from app.security import SecurityHeadersMiddleware


def make_client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>ABC app</html>")
    (tmp_path / "assets" / "app-123.js").write_text("console.log('xyz')")
    (tmp_path.parent / "secret.txt").write_text("nope")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=False)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    serve_web_app(app, tmp_path)
    return TestClient(app)


def test_serves_index_for_pages_and_files_as_they_are(tmp_path):
    c = make_client(tmp_path)
    for page in ("/", "/expenses", "/settings/budgets"):
        r = c.get(page)
        assert r.status_code == 200 and "ABC app" in r.text
        assert r.headers["cache-control"] == "no-cache"
        assert "default-src 'self'" in r.headers["content-security-policy"]
    r = c.get("/assets/app-123.js")
    assert "xyz" in r.text and "immutable" in r.headers["cache-control"]


def test_api_paths_stay_api(tmp_path):
    c = make_client(tmp_path)
    assert c.get("/api/health").json() == {"ok": True}
    r = c.get("/api/nope")
    assert r.status_code == 404
    assert r.headers["content-security-policy"].startswith("default-src 'none'")


def test_cannot_escape_the_web_root(tmp_path):
    c = make_client(tmp_path)
    assert "nope" not in c.get("/..%2Fsecret.txt").text


def test_hosted_database_urls_use_psycopg():
    for url in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/db"
    kept = "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url=kept).database_url == kept
