#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}
REPORT=${DOKURA_STAGE_01_REPORT:-/tmp/dokura-stage-01-content-report.json}

echo "[1/5] 依赖锁定与 Alembic 初始迁移"
uv sync --project "$ROOT/server" --locked
tmp_db=$(mktemp /tmp/dokura-stage-01-migration.XXXXXX.sqlite3)
DOKURA_MIGRATION_URL="sqlite:///$tmp_db" uv run --project "$ROOT/server" alembic -c "$ROOT/server/alembic.ini" upgrade head
DOKURA_MIGRATION_URL="sqlite:///$tmp_db" uv run --project "$ROOT/server" alembic -c "$ROOT/server/alembic.ini" check

echo "[2/5] 文件名状态机、Unicode 与自然排序"
uv run --project "$ROOT/server" pytest \
  "$ROOT/server/tests/unit/test_filename_parser.py" \
  "$ROOT/server/tests/unit/test_natural_sort.py"

echo "[3/5] 恶意 ZIP、CRC、像素炸弹与安全限制"
uv run --project "$ROOT/server" pytest "$ROOT/server/tests/unit/test_zip_analyzer.py"

echo "[4/5] 数据库设置、事务边界与原子替换"
uv run --project "$ROOT/server" pytest \
  "$ROOT/server/tests/integration/test_database.py" \
  "$ROOT/server/tests/integration/test_analysis_transaction.py"

echo "[5/5] 201 个真实 ZIP 只读分析"
uv run --project "$ROOT/server" python "$ROOT/server/scripts/analyze_content_report.py" \
  "$ROOT/content" --output "$REPORT"

echo "阶段 1 验收通过；真实内容报告: $REPORT"
