# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM node:24.16.0-alpine@sha256:21f403ab171f2dc89bad4dd69d7721bfd15f084ccb46cdd225f31f2bc59b5c9a AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run typecheck && npm run build

FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818 AS sqlite-build
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

FROM python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /uvx /bin/
COPY --from=sqlite-build /sqlite/lib/libsqlite3.so* /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOKURA_CONTENT_DIR=/data/content \
    DOKURA_METADATA_DIR=/data/metadata \
    DOKURA_CONFIG_DIR=/data/config

WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=120 uv sync --locked --no-dev \
    && .venv/bin/python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version" \
    && .venv/bin/python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE probe USING fts5(value, tokenize='trigram')\")"
COPY server/alembic.ini ./alembic.ini
COPY server/alembic ./alembic
COPY server/dokura ./dokura
COPY --from=web-build /build/web/dist /app/web/dist

RUN groupadd --gid 10001 dokura \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin dokura \
    && chown -R dokura:dokura /app

EXPOSE 8000
USER 10001:10001
CMD [".venv/bin/uvicorn", "dokura.main:app", "--host", "0.0.0.0", "--port", "8000"]
