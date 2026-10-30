# syntax=docker/dockerfile:1

# --- Frontend bauen -------------------------------------------------------
FROM node:24-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Python-Abhängigkeiten ------------------------------------------------
FROM python:3.13-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable

# --- Laufzeit -------------------------------------------------------------
FROM python:3.13-slim
LABEL org.opencontainers.image.title="paperless-pilot" \
      org.opencontainers.image.description="Bearbeitet Paperless-ngx-Dokumente automatisch mit lokalen LLMs"
RUN useradd --system --uid 10001 --create-home pilot
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /app/frontend/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PILOT_STATIC_DIR=/app/static \
    PILOT_PORT=8080
USER pilot
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"]
CMD ["paperless-pilot"]
