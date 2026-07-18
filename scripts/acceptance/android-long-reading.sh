#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ANDROID_DIR="$ROOT/android"
ADB_EXE=${ADB_EXE:-/mnt/c/Users/47155/AppData/Local/Android/Sdk/platform-tools/adb.exe}
DEVICE=${ANDROID_DEVICE:-emulator-5554}
DURATION_MS=${DOKURA_ANDROID_DURATION_MS:-3600000}
CACHE_BYTES=${DOKURA_ANDROID_CACHE_BYTES:-21474836480}
: "${DOKURA_ANDROID_IMAGE_URLS:?需设置由逗号分隔的代表性原图 URL}"
: "${DOKURA_ANDROID_API_KEY:?需设置发布验收专用 APIkey}"

"$ANDROID_DIR/gradlew" -p "$ANDROID_DIR" assembleDebug assembleDebugAndroidTest
"$ADB_EXE" -s "$DEVICE" get-state >/dev/null
"$ADB_EXE" -s "$DEVICE" install -r "$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk" >/dev/null
"$ADB_EXE" -s "$DEVICE" install -r "$ANDROID_DIR/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk" >/dev/null

started=$(date +%s)
output=$("$ADB_EXE" -s "$DEVICE" shell am instrument -w \
    -e stage9 true \
    -e durationMs "$DURATION_MS" \
    -e cacheBytes "$CACHE_BYTES" \
    -e imageUrls "$DOKURA_ANDROID_IMAGE_URLS" \
    -e apiKey "$DOKURA_ANDROID_API_KEY" \
    -e class com.dokura.app.Stage9StabilityTest \
    com.dokura.app.test/androidx.test.runner.AndroidJUnitRunner | tr -d '\r')
printf '%s\n' "$output"
grep -Eq '^OK \(1 test\)$' <<<"$output"
elapsed=$(( $(date +%s) - started ))
minimum=$(( DURATION_MS / 1000 ))
test "$elapsed" -ge "$minimum"

echo "Android 长时阅读、20GB 边界、清空缓存和网络恢复验收通过（${elapsed}s）"
