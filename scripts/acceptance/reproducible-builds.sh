#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK=$(mktemp -d /tmp/dokura-reproducible.XXXXXX)
BUILDER="dokura-reproducible-$$"
cleanup() {
    local status=$?
    docker buildx rm "$BUILDER" >/dev/null 2>&1 || true
    if ((status == 0)); then
        rm -rf "$WORK"
    else
        echo "失败产物保留在 $WORK" >&2
    fi
    return "$status"
}
trap cleanup EXIT
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git -C "$ROOT" log -1 --format=%ct)
export TZ=UTC

hash_tree() {
    local directory=$1
    (cd "$directory" && find . -type f -printf '%P\0' | sort -z | xargs -0 sha256sum)
}

build_oci() {
    local destination=$1
    local attempt
    for attempt in 1 2 3; do
        if docker buildx build --builder "$BUILDER" --no-cache --provenance=false \
            --build-arg "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
            --output "type=oci,dest=$destination,rewrite-timestamp=true,name=dokura:reproducible" \
            "$ROOT"; then
            return 0
        fi
        rm -f "$destination"
        if ((attempt < 3)); then
            echo "OCI 无缓存构建第 $attempt 次失败，重试" >&2
        fi
    done
    return 1
}

echo "[1/3] Web 静态资源两次独立构建"
npm --prefix "$ROOT/web" ci
rm -rf "$ROOT/web/dist"
npm --prefix "$ROOT/web" run build
hash_tree "$ROOT/web/dist" >"$WORK/web-1.sha256"
rm -rf "$ROOT/web/dist"
npm --prefix "$ROOT/web" run build
hash_tree "$ROOT/web/dist" >"$WORK/web-2.sha256"
diff -u "$WORK/web-1.sha256" "$WORK/web-2.sha256"

echo "[2/3] Android APK 两次独立构建"
"$ROOT/android/gradlew" -p "$ROOT/android" clean assembleDebug
sha256sum "$ROOT/android/app/build/outputs/apk/debug/app-debug.apk" | cut -d' ' -f1 >"$WORK/apk-1.sha256"
"$ROOT/android/gradlew" -p "$ROOT/android" clean assembleDebug
sha256sum "$ROOT/android/app/build/outputs/apk/debug/app-debug.apk" | cut -d' ' -f1 >"$WORK/apk-2.sha256"
diff -u "$WORK/apk-1.sha256" "$WORK/apk-2.sha256"

echo "[3/3] 生产 Docker 镜像两次无缓存构建"
docker buildx create --name "$BUILDER" --driver docker-container --bootstrap >/dev/null
build_oci "$WORK/image-1.oci.tar"
build_oci "$WORK/image-2.oci.tar"
sha256sum "$WORK/image-1.oci.tar" | cut -d' ' -f1 >"$WORK/image-1.txt"
sha256sum "$WORK/image-2.oci.tar" | cut -d' ' -f1 >"$WORK/image-2.txt"
diff -u "$WORK/image-1.txt" "$WORK/image-2.txt"

echo "Web、Android APK 和 Docker 镜像可复现构建通过"
