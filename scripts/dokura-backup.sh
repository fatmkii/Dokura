#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DESTINATION=${1:-}
COMPOSE_FILE=${DOKURA_COMPOSE_FILE:-$ROOT/compose.yaml}
COMPOSE_PROJECT_ARGS=()
if [[ -n "${DOKURA_COMPOSE_PROJECT:-}" ]]; then
    COMPOSE_PROJECT_ARGS=(-p "$DOKURA_COMPOSE_PROJECT")
fi

if [[ -z "$DESTINATION" ]]; then
    echo "用法: scripts/dokura-backup.sh <备份目录>" >&2
    exit 2
fi

if [[ -n "$(docker compose "${COMPOSE_PROJECT_ARGS[@]}" -f "$COMPOSE_FILE" ps --status running -q)" ]]; then
    echo "Dokura 仍在运行；冷备份前请先执行 docker compose stop dokura" >&2
    exit 1
fi

mkdir -p "$DESTINATION"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="$DESTINATION/dokura-$STAMP.tar.gz"
TEMPORARY="$ARCHIVE.tmp"
trap 'rm -f "$TEMPORARY"' EXIT

docker compose "${COMPOSE_PROJECT_ARGS[@]}" -f "$COMPOSE_FILE" \
    run --rm --no-deps -T dokura tar -C /data -czf - metadata config > "$TEMPORARY"
tar -tzf "$TEMPORARY" >/dev/null
mv "$TEMPORARY" "$ARCHIVE"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"

printf '%s\n' "$ARCHIVE"
