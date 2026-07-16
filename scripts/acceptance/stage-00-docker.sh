#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
RUNTIME=$(mktemp -d)
export DOKURA_ACCEPTANCE_CONTENT="$RUNTIME/content"
export DOKURA_ACCEPTANCE_METADATA="$RUNTIME/metadata"
export DOKURA_ACCEPTANCE_CONFIG="$RUNTIME/config"
export DOKURA_PORT=${DOKURA_PORT:-18080}
COMPOSE=(
    docker compose
    --project-name "${DOKURA_ACCEPTANCE_PROJECT:-dokura-stage-00-acceptance}"
    -f "$ROOT/compose.yaml"
    -f "$ROOT/scripts/acceptance/docker-compose.stage-00.yaml"
)

cleanup() {
    "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$RUNTIME"
}
trap cleanup EXIT

mkdir -p "$DOKURA_ACCEPTANCE_CONTENT" "$DOKURA_ACCEPTANCE_METADATA" "$DOKURA_ACCEPTANCE_CONFIG"
touch "$DOKURA_ACCEPTANCE_CONTENT/read-only-sample.zip"

"${COMPOSE[@]}" up -d --build

for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${DOKURA_PORT}/api/v1/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS "http://127.0.0.1:${DOKURA_PORT}/api/v1/health"
curl -fsS "http://127.0.0.1:${DOKURA_PORT}/" | grep -q "<title>Dokura</title>"

"${COMPOSE[@]}" exec -T dokura .venv/bin/python -c \
    "from dokura.sqlite_check import verify_sqlite_capabilities; print(verify_sqlite_capabilities())"
"${COMPOSE[@]}" exec -T dokura sh -c \
    "printf metadata > /data/metadata/persistence-check && printf config > /data/config/persistence-check"
"${COMPOSE[@]}" up -d --force-recreate
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${DOKURA_PORT}/api/v1/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS "http://127.0.0.1:${DOKURA_PORT}/api/v1/health" >/dev/null
"${COMPOSE[@]}" exec -T dokura test -r /data/content/read-only-sample.zip
if "${COMPOSE[@]}" exec -T dokura touch /data/content/must-not-write 2>/dev/null; then
    echo "Content 挂载必须为只读" >&2
    exit 1
fi
"${COMPOSE[@]}" exec -T dokura test -f /data/metadata/persistence-check
"${COMPOSE[@]}" exec -T dokura test -f /data/config/persistence-check

echo "Docker 健康、自检和三个持久化挂载验收通过"
