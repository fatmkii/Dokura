#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}
tmp_root=$(mktemp -d /tmp/dokura-stage-05.XXXXXX)
export DOKURA_STAGE5_CONTENT="$tmp_root/content"
export DOKURA_STAGE5_METADATA="$tmp_root/metadata"
export DOKURA_STAGE5_CONFIG="$tmp_root/config"
export DOKURA_STAGE5_PORT=${DOKURA_STAGE5_PORT:-18005}
export DOKURA_STAGE5_UID=$(id -u)
export DOKURA_STAGE5_GID=$(id -g)
compose=(docker compose -p dokura-stage-05 -f "$ROOT/scripts/acceptance/docker-compose.stage-05.yaml")
mkdir -p "$DOKURA_STAGE5_CONTENT" "$DOKURA_STAGE5_METADATA" "$DOKURA_STAGE5_CONFIG"

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$tmp_root"
}
trap cleanup EXIT

echo "[1/4] 生成隔离的临时 Content 管理树"
uv run --project "$ROOT/server" python "$ROOT/scripts/acceptance/generate_stage5_content.py" "$DOKURA_STAGE5_CONTENT"
test ! -L "$DOKURA_STAGE5_CONTENT"

echo "[2/4] Server 阶段 5 领域测试、Web 检查与 OpenAPI 漂移"
uv sync --project "$ROOT/server" --locked
uv run --project "$ROOT/server" pytest "$ROOT/server/tests/integration/test_stage5_management.py" "$ROOT/server/tests/unit/test_logging.py" "$ROOT/server/tests/unit/test_image_scheduler.py"
uv run --project "$ROOT/server" python "$ROOT/server/scripts/generate_openapi.py" --check
npm --prefix "$ROOT/web" ci
npm --prefix "$ROOT/web" test
npm --prefix "$ROOT/web" run typecheck
npm --prefix "$ROOT/web" run build
if [[ -z "${PW_CHROMIUM_PATH:-}" ]]; then
  npm --prefix "$ROOT/web" exec playwright install chromium
fi

echo "[3/4] 构建并启动读写仅限临时树的生产 Docker"
"${compose[@]}" up -d --build --wait
curl --fail --silent --show-error "http://127.0.0.1:$DOKURA_STAGE5_PORT/api/v1/health" >/dev/null

echo "[4/4] Playwright Chromium Web 管理闭环"
PW_BASE_URL="http://127.0.0.1:$DOKURA_STAGE5_PORT" npm --prefix "$ROOT/web" run e2e -- --grep @stage5 --workers=1 --reporter=list

echo "阶段 5 验收通过；全部破坏性操作均位于已清理的临时 Content 树"
