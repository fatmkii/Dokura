#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}
tmp_db=$(mktemp /tmp/dokura-stage-03-migration.XXXXXX.sqlite3)
tmp_report=$(mktemp /tmp/dokura-stage-03-scale.XXXXXX.json)
trap 'rm -f "$tmp_db" "$tmp_report"' EXIT

echo "[1/4] 依赖锁定与阶段 3 增量迁移"
uv sync --project "$ROOT/server" --locked
DOKURA_MIGRATION_URL="sqlite:///$tmp_db" uv run --project "$ROOT/server" \
  alembic -c "$ROOT/server/alembic.ini" upgrade head
DOKURA_MIGRATION_URL="sqlite:///$tmp_db" uv run --project "$ROOT/server" \
  alembic -c "$ROOT/server/alembic.ini" check

echo "[2/4] 合约、鉴权、目录搜索、评分与图片 HTTP 语义"
uv run --project "$ROOT/server" pytest \
  "$ROOT/server/tests/integration/test_stage3_api.py" \
  "$ROOT/server/tests/unit/test_image_scheduler.py"

echo "[3/4] 100,000 条代表性元数据与目标索引查询计划"
uv run --project "$ROOT/server" python -m dokura.stage3_dataset \
  --count 100000 --report "$tmp_report"

echo "[4/4] 服务端完整回归与 OpenAPI 漂移检查"
uv run --project "$ROOT/server" pytest
uv run --project "$ROOT/server" python "$ROOT/server/scripts/generate_openapi.py" --check

echo "阶段 3 验收通过；规模数据库、报告和图片测试数据均位于临时目录"
