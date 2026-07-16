#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}

echo "[1/5] Server 测试与 OpenAPI 漂移检查"
uv sync --project "$ROOT/server" --locked
uv run --project "$ROOT/server" pytest
uv run --project "$ROOT/server" python "$ROOT/server/scripts/generate_openapi.py" --check

echo "[2/5] Web 单元测试、类型检查与构建"
npm ci --prefix "$ROOT/web"
npm test --prefix "$ROOT/web"
npm run typecheck --prefix "$ROOT/web"
npm run build --prefix "$ROOT/web"

echo "[3/5] Android lint 与 JVM 测试"
"$ROOT/android/gradlew" -p "$ROOT/android" lintDebug testDebugUnitTest

echo "[4/5] Android debug APK"
"$ROOT/android/gradlew" -p "$ROOT/android" assembleDebug

echo "[5/5] Docker 健康、自检与持久化"
"$ROOT/scripts/acceptance/stage-00-docker.sh"

echo "阶段 0 验收通过"
