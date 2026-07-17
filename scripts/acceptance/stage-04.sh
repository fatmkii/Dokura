#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}
tmp_root=$(mktemp -d /tmp/dokura-stage-04.XXXXXX)
export DOKURA_STAGE4_CONTENT="$tmp_root/content"
export DOKURA_STAGE4_METADATA="$tmp_root/metadata"
export DOKURA_STAGE4_CONFIG="$tmp_root/config"
export DOKURA_STAGE4_PORT=${DOKURA_STAGE4_PORT:-18004}
compose=(docker compose -p dokura-stage-04 -f "$ROOT/scripts/acceptance/docker-compose.stage-04.yaml")
mkdir -p "$DOKURA_STAGE4_CONTENT" "$DOKURA_STAGE4_METADATA" "$DOKURA_STAGE4_CONFIG"

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$tmp_root"
}
trap cleanup EXIT

echo "[1/4] Web 单元测试、类型检查与生产构建"
npm --prefix "$ROOT/web" ci
npm --prefix "$ROOT/web" test
npm --prefix "$ROOT/web" run typecheck
npm --prefix "$ROOT/web" run build
if [[ -z "${PW_CHROMIUM_PATH:-}" ]]; then
  npm --prefix "$ROOT/web" exec playwright install chromium
fi

echo "[2/4] 服务端 SPA 历史路由与阶段 0–3 回归"
uv sync --project "$ROOT/server" --locked
uv run --project "$ROOT/server" pytest
uv run --project "$ROOT/server" python "$ROOT/server/scripts/generate_openapi.py" --check

echo "[3/4] 构建并启动隔离卷的生产 Docker"
"${compose[@]}" up -d --build --wait
curl --fail --silent --show-error "http://127.0.0.1:$DOKURA_STAGE4_PORT/api/v1/health" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:$DOKURA_STAGE4_PORT/files/test-history-route" | grep -q '<div id="app"></div>'

echo "[4/4] Playwright Chromium 阶段 4 浏览闭环"
PW_BASE_URL="http://127.0.0.1:$DOKURA_STAGE4_PORT" npm --prefix "$ROOT/web" run e2e -- --grep-invert @stage5 --reporter=list

echo "阶段 4 验收通过；Docker 数据与测试内容均位于已清理的临时目录"
