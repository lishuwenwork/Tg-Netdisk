FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json tsconfig.json vite.config.ts ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend ./frontend
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy PATH="/opt/venv/bin:$PATH" \
    TG_MODE=web TG_DATA_DIR=/data TG_MEDIA_ROOT=/media TG_FRONTEND_DIR=/app/frontend-dist \
    TG_MIGRATIONS_DIR=/app/backend/migrations PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
COPY backend/migrations ./migrations
RUN uv sync --frozen --no-dev --no-editable && \
    useradd --uid 10001 --create-home app && \
    mkdir -p /data /media && chown app:app /data
COPY --from=frontend /build/dist /app/frontend-dist
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('TG_PORT','8080')+'/api/health',timeout=3)"
CMD ["python", "-m", "tg_netdisk.web"]
