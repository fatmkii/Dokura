#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}

echo "[1/4] 依赖锁定与阶段 2 增量迁移"
uv sync --project "$ROOT/server" --locked
tmp_db=$(mktemp /tmp/dokura-stage-02-migration.XXXXXX.sqlite3)
trap 'rm -f "$tmp_db"' EXIT
DOKURA_MIGRATION_URL="sqlite:///$tmp_db" uv run --project "$ROOT/server" \
  alembic -c "$ROOT/server/alembic.ini" upgrade head
DOKURA_MIGRATION_URL="sqlite:///$tmp_db" uv run --project "$ROOT/server" \
  alembic -c "$ROOT/server/alembic.ini" check

echo "[2/4] 扫描、身份、稳定性、重试、恢复与查询计数"
uv run --project "$ROOT/server" pytest \
  "$ROOT/server/tests/integration/test_stage2_scanning.py"

echo "[3/4] 启动扫描、文件监听与管理接口"
uv run --project "$ROOT/server" pytest \
  "$ROOT/server/tests/integration/test_app.py"

echo "[4/4] 服务端回归与 OpenAPI 漂移检查"
uv run --project "$ROOT/server" pytest
uv run --project "$ROOT/server" python "$ROOT/server/scripts/generate_openapi.py" --check

echo "阶段 2 验收通过；全部文件系统写操作均位于 pytest 临时目录"
