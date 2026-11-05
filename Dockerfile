# One image runs everything: the API, the receipt readers, and the built web app.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /web/dist ./static
ENV PATH="/app/.venv/bin:$PATH" STATIC_DIR=/app/static
# Apply database migrations, then serve on the port the host gives us. --proxy-headers lets
# rate limits see each visitor's address rather than the host's proxy.
CMD alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
