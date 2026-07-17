#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ANDROID_DIR="$ROOT/android"
ADB_EXE=${ADB_EXE:-/mnt/c/Users/47155/AppData/Local/Android/Sdk/platform-tools/adb.exe}
DEVICE=${ANDROID_DEVICE:-emulator-5554}

echo "[1/3] Android JVM、Compose 编译、lint 与 APK"
"$ANDROID_DIR/gradlew" -p "$ANDROID_DIR" testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest

echo "[2/3] Windows 模拟器可用性与 APK 安装"
"$ADB_EXE" -s "$DEVICE" get-state >/dev/null
"$ADB_EXE" -s "$DEVICE" install -r "$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk" >/dev/null
"$ADB_EXE" -s "$DEVICE" install -r "$ANDROID_DIR/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk" >/dev/null

echo "[3/3] emulator-5554 仪器测试"
INSTRUMENT_OUTPUT=$("$ADB_EXE" -s "$DEVICE" shell am instrument -w com.dokura.app.test/androidx.test.runner.AndroidJUnitRunner | tr -d '\r')
printf '%s\n' "$INSTRUMENT_OUTPUT"
if ! grep -Eq '^OK \([0-9]+ tests?\)$' <<<"$INSTRUMENT_OUTPUT"; then
    echo "阶段 6 仪器测试失败" >&2
    exit 1
fi

echo "阶段 6 验收通过"
