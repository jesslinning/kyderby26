# syntax=docker/dockerfile:1
# Multi-stage: Node builds Vite dist; Python runtime serves FastAPI + static files.
# Railway/Nixpacks Node-only images omit Python at runtime — this image includes both.

FROM node:20-bookworm-slim AS web-build
WORKDIR /web
COPY app/web/package.json app/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

COPY requirements.txt .
COPY app ./app
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=web-build /web/dist ./app/web/dist

EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn app.odds_api:app --host 0.0.0.0 --port ${PORT:-8000}"]
