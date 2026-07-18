#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PROFILE=${DOKURA_RELEASE_PROFILE:-release}
PORT=${DOKURA_STAGE9_PORT:-18009}
BASE_URL="http://127.0.0.1:$PORT"
COMPOSE_FILE="$ROOT/scripts/acceptance/docker-compose.stage-09.yaml"
PROJECT="dokura-stage09-$$"
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/dokura-uv-cache}
export DOKURA_STAGE9_PORT=$PORT
export DOKURA_STAGE9_DATA
DOKURA_STAGE9_DATA=$(mktemp -d /tmp/dokura-stage-09.XXXXXX)
REPORT_DIR=${DOKURA_RELEASE_REPORT_DIR:-$(mktemp -d /tmp/dokura-release-report.XXXXXX)}

if [[ "$PROFILE" == release ]]; then
    DATASET_COUNT=100000
    SERVER_DURATION=3600
    ANDROID_DURATION_MS=3600000
    ANDROID_CACHE_BYTES=21474836480
    IDLE_SECONDS=300
    BENCHMARK_EXTRA=()
elif [[ "$PROFILE" == smoke ]]; then
    DATASET_COUNT=${DOKURA_STAGE9_DATASET_COUNT:-1000}
    SERVER_DURATION=${DOKURA_STAGE9_SERVER_DURATION:-20}
    ANDROID_DURATION_MS=${DOKURA_ANDROID_DURATION_MS:-10000}
    ANDROID_CACHE_BYTES=${DOKURA_ANDROID_CACHE_BYTES:-104857600}
    IDLE_SECONDS=${DOKURA_STAGE9_IDLE_SECONDS:-2}
    BENCHMARK_EXTRA=(--allow-failures)
else
    echo "DOKURA_RELEASE_PROFILE 只支持 release 或 smoke" >&2
    exit 2
fi

cleanup() {
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down --remove-orphans >/dev/null 2>&1 || true
    docker run --rm --user 0:0 -v "$DOKURA_STAGE9_DATA:/wipe" dokura:release \
        chmod -R a+rwX /wipe >/dev/null 2>&1 || true
    rm -rf "$DOKURA_STAGE9_DATA"
}
trap cleanup EXIT
mkdir -p "$REPORT_DIR"

if [[ "$PROFILE" == release ]]; then
    echo "[1/7] 阶段 0～8 全量回归"
    for stage in 00 01 02 03 04 05 06 07 08; do
        "$ROOT/scripts/acceptance/stage-$stage.sh"
    done
else
    echo "[1/7] smoke 配置：显式跳过阶段 0～8 全量回归，不构成发布验收"
fi

echo "[2/7] 固化 10 万条代表性元数据、扫描文件树和真实 ZIP 图片样本"
uv sync --project "$ROOT/server" --locked
uv run --project "$ROOT/server" python -m dokura.real_zip_benchmark "$ROOT/content" \
    --count 9 --pages 3 --report "$REPORT_DIR/real-zip.json"
uv run --project "$ROOT/server" python -m dokura.stage9_prepare \
    --data-root "$DOKURA_STAGE9_DATA" --real-content "$ROOT/content" \
    --count "$DATASET_COUNT" --real-count 3 --report "$REPORT_DIR/dataset.json"
chmod -R a+rwX "$DOKURA_STAGE9_DATA/MetaData" "$DOKURA_STAGE9_DATA/Config"

echo "[3/7] 生产容器、启动扫描和真实图片分析"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" build
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --wait
CASES="$DOKURA_STAGE9_DATA/Config/cases.json"
KEY_FILE="$DOKURA_STAGE9_DATA/Config/api-key"
uv run --project "$ROOT/server" python -m dokura.stage9_cases \
    --base-url "$BASE_URL" --cases "$CASES" --api-key-file "$KEY_FILE"

VERSION=$(git -C "$ROOT" rev-parse HEAD)
STORAGE=${DOKURA_RELEASE_STORAGE:-"WSL2 本地文件系统（请在正式参考环境覆盖）"}
NETWORK=${DOKURA_RELEASE_NETWORK:-"容器本机回环；Android 使用局域网（请在正式参考环境覆盖）"}
DATASET="${DATASET_COUNT} 条固定代表性元数据、100 个目录、30 个 tag、3 个真实 ZIP HTTP 样本、9 个真实 ZIP 只读基准"

echo "[4/7] 冷热缓存 HTTP 性能矩阵"
uv run --project "$ROOT/server" python -m dokura.release_benchmark \
    --base-url "$BASE_URL" --cases "$CASES" --report "$REPORT_DIR/http-matrix.json" \
    --requests 100 --image-requests 20 --network "$NETWORK" --storage "$STORAGE" \
    --dataset "$DATASET" --version "$VERSION" --cache-condition mixed "${BENCHMARK_EXTRA[@]}"

echo "[5/7] 完整扫描、前后台混合负载和服务端资源稳定性"
SERVER_PID=$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T dokura \
    .venv/bin/python -c "from pathlib import Path; children=Path('/proc/1/task/1/children').read_text().split(); assert len(children)==1, children; print(children[0])")
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T dokura \
    .venv/bin/python -m dokura.release_benchmark \
    --base-url http://127.0.0.1:8000 --cases /data/config/cases.json --report /data/config/server-stability.json \
    --pid "$SERVER_PID" --scan --duration "$SERVER_DURATION" --idle-seconds "$IDLE_SECONDS" --sample-interval 5 \
    --requests 100 --image-requests 20 --network "$NETWORK" --storage "$STORAGE" \
    --dataset "$DATASET" --version "$VERSION" --cache-condition warm "${BENCHMARK_EXTRA[@]}"
cp "$DOKURA_STAGE9_DATA/Config/server-stability.json" "$REPORT_DIR/server-stability.json"

echo "[6/7] Android 长时阅读、热缓存、20GB 边界和网络恢复"
if [[ "$PROFILE" == release ]]; then
    : "${DOKURA_ANDROID_BASE_URL:?正式发布验收需设置模拟器可访问的服务端 URL，例如 http://10.0.2.2:18009}"
else
    DOKURA_ANDROID_BASE_URL=${DOKURA_ANDROID_BASE_URL:-http://10.0.2.2:$PORT}
fi
export DOKURA_ANDROID_BASE_URL
export DOKURA_ANDROID_API_KEY
DOKURA_ANDROID_API_KEY=$(<"$KEY_FILE")
export DOKURA_ANDROID_IMAGE_URLS
DOKURA_ANDROID_IMAGE_URLS=$(uv run --project "$ROOT/server" python -c \
    'import json,os,sys; data=json.load(open(sys.argv[1])); print(",".join(os.environ["DOKURA_ANDROID_BASE_URL"].rstrip("/")+path for path in data["originals"]))' "$CASES")
export DOKURA_ANDROID_DURATION_MS=$ANDROID_DURATION_MS
export DOKURA_ANDROID_CACHE_BYTES=$ANDROID_CACHE_BYTES
"$ROOT/scripts/acceptance/android-long-reading.sh" | tee "$REPORT_DIR/android-stability.txt"
unset DOKURA_ANDROID_API_KEY

if [[ "$PROFILE" == release ]]; then
    echo "[7/7] Docker、Web 静态资源和 Android APK 可复现构建"
    "$ROOT/scripts/acceptance/reproducible-builds.sh" | tee "$REPORT_DIR/reproducible-builds.txt"
    echo "阶段 9 与首版发布验收通过；报告目录: $REPORT_DIR"
else
    echo "[7/7] smoke 配置：跳过耗时的两次无缓存可复现构建"
    echo "阶段 9 smoke 流程执行完成；指标失败仍记录在报告中，且不构成发布验收；报告目录: $REPORT_DIR"
fi
