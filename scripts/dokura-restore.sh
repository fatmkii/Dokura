#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ARCHIVE=${1:-}
COMPOSE_FILE=${DOKURA_COMPOSE_FILE:-$ROOT/compose.yaml}
COMPOSE_PROJECT_ARGS=()
if [[ -n "${DOKURA_COMPOSE_PROJECT:-}" ]]; then
    COMPOSE_PROJECT_ARGS=(-p "$DOKURA_COMPOSE_PROJECT")
fi

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
    echo "用法: scripts/dokura-restore.sh <冷备份归档>" >&2
    exit 2
fi

if [[ -n "$(docker compose "${COMPOSE_PROJECT_ARGS[@]}" -f "$COMPOSE_FILE" ps --status running -q)" ]]; then
    echo "Dokura 仍在运行；冷恢复前请先执行 docker compose stop dokura" >&2
    exit 1
fi

if [[ -f "$ARCHIVE.sha256" ]]; then
    sha256sum -c "$ARCHIVE.sha256"
fi

while IFS= read -r member; do
    if [[ "/$member/" == *"/../"* ]]; then
        echo "备份归档包含路径穿越: $member" >&2
        exit 1
    fi
    case "$member" in
        metadata|metadata/*|config|config/*) ;;
        *)
            echo "备份归档包含非预期路径: $member" >&2
            exit 1
            ;;
    esac
done < <(tar -tzf "$ARCHIVE")

docker compose "${COMPOSE_PROJECT_ARGS[@]}" -f "$COMPOSE_FILE" \
    run --rm --no-deps -T dokura sh -eu -c '
restore_dir=$(mktemp -d)
trap "rm -rf \$restore_dir" EXIT
tar -C "$restore_dir" -xzf -
test -d "$restore_dir/metadata" && test -d "$restore_dir/config"
test -z "$(find "$restore_dir" ! -type f ! -type d -print -quit)"
find /data/metadata -mindepth 1 -delete
find /data/config -mindepth 1 -delete
find "$restore_dir/metadata" -mindepth 1 -maxdepth 1 -exec cp -a -t /data/metadata -- {} +
find "$restore_dir/config" -mindepth 1 -maxdepth 1 -exec cp -a -t /data/config -- {} +
' < "$ARCHIVE"
