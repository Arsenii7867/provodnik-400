# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

RUN groupadd --system --gid 10001 provodnik \
    && useradd --system --uid 10001 --gid provodnik \
        --home-dir /nonexistent --shell /usr/sbin/nologin provodnik \
    && mkdir -p /app/backend/data /app/content /app/frontend \
    && chown -R provodnik:provodnik /app/backend/data

COPY backend/app/ ./app/
COPY content/ /app/content/
COPY --from=frontend-build /build/frontend/dist/ /app/frontend/dist/

USER provodnik:provodnik

EXPOSE 8000
VOLUME ["/app/backend/data"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3).close()"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
