#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE_FILE="$ROOT/scripts/acceptance/docker-compose.stage-08.yaml"
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}
export DOKURA_STAGE8_DATA
DOKURA_STAGE8_DATA=$(mktemp -d /tmp/dokura-stage-08.XXXXXX)
export DOKURA_STAGE8_PORT=${DOKURA_STAGE8_PORT:-18008}
PROJECT="dokura-stage08-$$"
BACKUPS="$DOKURA_STAGE8_DATA/backups"
MIGRATION_DB="$DOKURA_STAGE8_DATA/previous.sqlite3"

cleanup() {
    chmod 755 "$DOKURA_STAGE8_DATA/Content" 2>/dev/null || true
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down --remove-orphans >/dev/null 2>&1 || true
    docker run --rm \
        -v "$DOKURA_STAGE8_DATA/MetaData:/wipe-metadata" \
        -v "$DOKURA_STAGE8_DATA/Config:/wipe-config" \
        dokura:stage-08 sh -c \
        'find /wipe-metadata -mindepth 1 -delete; find /wipe-config -mindepth 1 -delete' \
        >/dev/null 2>&1 || true
    rm -rf "$DOKURA_STAGE8_DATA"
}
trap cleanup EXIT

mkdir -p "$DOKURA_STAGE8_DATA"/{Content,MetaData,Config} "$BACKUPS"
chmod 777 "$DOKURA_STAGE8_DATA/MetaData" "$DOKURA_STAGE8_DATA/Config"

echo "[1/5] 前一迁移版本升级、服务端安全与故障恢复回归"
uv sync --project "$ROOT/server" --locked
DOKURA_MIGRATION_URL="sqlite:///$MIGRATION_DB" uv run --project "$ROOT/server" \
    alembic -c "$ROOT/server/alembic.ini" upgrade 9bc218db86e1
DOKURA_MIGRATION_URL="sqlite:///$MIGRATION_DB" uv run --project "$ROOT/server" \
    alembic -c "$ROOT/server/alembic.ini" upgrade head
DOKURA_MIGRATION_URL="sqlite:///$MIGRATION_DB" uv run --project "$ROOT/server" \
    alembic -c "$ROOT/server/alembic.ini" check
uv run --project "$ROOT/server" pytest

echo "[2/5] 固定摘要生产镜像与非特权运行"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" build
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --wait
CONTAINER=$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps -q dokura)
test "$(docker inspect -f '{{.Config.User}}' "$CONTAINER")" = "10001:10001"
test "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$CONTAINER")" = "true"
test "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" = "healthy"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T dokura \
    .venv/bin/python -c "import os; assert os.getuid() == 10001 and os.getgid() == 10001"

echo "[3/5] 扫描期间及 Content 不可访问时保持健康"
chmod 000 "$DOKURA_STAGE8_DATA/Content"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" restart dokura >/dev/null
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --wait
test "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" = "healthy"
chmod 755 "$DOKURA_STAGE8_DATA/Content"

echo "[4/5] 冷备份、空卷替换恢复与容器重建"
if DOKURA_COMPOSE_FILE="$COMPOSE_FILE" \
    DOKURA_COMPOSE_PROJECT="$PROJECT" "$ROOT/scripts/dokura-backup.sh" "$BACKUPS" \
    >/dev/null 2>&1; then
    echo "容器运行时冷备份必须被拒绝" >&2
    exit 1
fi
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" stop dokura >/dev/null
ARCHIVE=$(DOKURA_COMPOSE_FILE="$COMPOSE_FILE" \
    DOKURA_COMPOSE_PROJECT="$PROJECT" "$ROOT/scripts/dokura-backup.sh" "$BACKUPS")
sha256sum -c "$ARCHIVE.sha256"
CREDENTIAL_HASH=$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" run --rm --no-deps -T dokura \
    sha256sum /data/config/credentials.json | cut -d' ' -f1)
DOKURA_COMPOSE_FILE="$COMPOSE_FILE" DOKURA_COMPOSE_PROJECT="$PROJECT" \
    "$ROOT/scripts/dokura-restore.sh" "$ARCHIVE"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --force-recreate --wait
CONTAINER=$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps -q dokura)
test "$CREDENTIAL_HASH" = "$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T dokura \
    sha256sum /data/config/credentials.json | cut -d' ' -f1)"

echo "[5/5] 反复启动后的进程、临时文件与健康状态"
BASE_FDS=
BASE_THREADS=
for _ in 1 2 3; do
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" restart dokura >/dev/null
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --wait
    CONTAINER=$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps -q dokura)
    test "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" = "healthy"
    test "$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T dokura \
        sh -c 'find /tmp -type f | wc -l')" -eq 0
    read -r FDS THREADS TASKS < <(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T dokura \
        .venv/bin/python -c "from pathlib import Path; import sqlite3; processes=[p for p in Path('/proc').iterdir() if p.name.isdigit() and (p/'exe').resolve().name.startswith('python') and b'dokura.main:app' in (p/'cmdline').read_bytes().split(b'\\0')]; assert len(processes)==1; p=processes[0]; tasks=sqlite3.connect('/data/metadata/dokura.sqlite3').execute(\"SELECT count(*) FROM tasks WHERE status IN ('waiting_stable','retry_wait','analyzing')\").fetchone()[0]; print(len(list((p/'fd').iterdir())), len(list((p/'task').iterdir())), tasks)")
    test "$TASKS" -eq 0
    if [[ -z "$BASE_FDS" ]]; then
        BASE_FDS=$FDS
        BASE_THREADS=$THREADS
    else
        test "$FDS" -le $((BASE_FDS + 2))
        test "$THREADS" -eq "$BASE_THREADS"
    fi
done

echo "阶段 8 验收通过；全部部署、恢复和破坏性测试均使用临时卷"
