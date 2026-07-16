# syntax=docker/dockerfile:1.7

FROM node:24.16.0-alpine AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run typecheck && npm run build

FROM debian:bookworm-slim AS sqlite-build
ARG SQLITE_VERSION=3510300
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
ADD --checksum=sha256:81f5be397049b0cae1b167f2225af7646fc0f82e4a9b3c48c9ea3a533e21d77a \
    https://www.sqlite.org/2026/sqlite-autoconf-3510300.tar.gz \
    sqlite-autoconf-3510300.tar.gz
RUN tar -xzf "sqlite-autoconf-${SQLITE_VERSION}.tar.gz" \
    && cd "sqlite-autoconf-${SQLITE_VERSION}" \
    && ./configure --prefix=/sqlite --enable-shared --disable-static --fts5 \
    && make -j"$(nproc)" \
    && make install

FROM python:3.14.5-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/
COPY --from=sqlite-build /sqlite/lib/libsqlite3.so* /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib \
    PYTHONUNBUFFERED=1 \
    DOKURA_CONTENT_DIR=/data/content \
    DOKURA_METADATA_DIR=/data/metadata \
    DOKURA_CONFIG_DIR=/data/config

WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --locked --no-dev \
    && .venv/bin/python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version" \
    && .venv/bin/python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE probe USING fts5(value, tokenize='trigram')\")"
COPY server/dokura ./dokura
COPY --from=web-build /build/web/dist /app/web/dist

EXPOSE 8000
CMD [".venv/bin/uvicorn", "dokura.main:app", "--host", "0.0.0.0", "--port", "8000"]
