#!/usr/bin/env bash
# release-android.sh — assembleRelease APK with FOCUSVPN_API_BASE (needs ANDROID_HOME).
# Restores libwg-go.so from ABI tarball if jniLibs empty.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${FOCUSVPN_DIST:-$ROOT/dist}"
API="${FOCUSVPN_API_BASE:?set FOCUSVPN_API_BASE e.g. https://api.example.com}"
AND="$ROOT/clients/android"
JNILIBs="$AND/app/src/main/jniLibs"

fail() { echo "release-android FAIL: $*" >&2; exit 1; }

echo "==> release-android API=$API"

n=$(find "$JNILIBs" -name 'libwg-go.so' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$n" -eq 0 ]]; then
  echo "==> no jniLibs — trying android-native-restore / docker"
  if [[ -f "$ROOT/.cache/native/abi/libwg-go-v2.0.2-com.focusvpn.app-v0.2.19.tgz" ]]; then
    make -C "$ROOT" android-native-restore
  elif command -v podman >/dev/null || command -v docker >/dev/null; then
    make -C "$ROOT" android-native-docker
  else
    fail "need libwg-go.so (make android-native-docker or restore ABI tarball)"
  fi
fi

[[ -n "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}" ]] || fail "set ANDROID_HOME (or skip APK and use linux/windows first)"
mkdir -p "$DIST/android"

(
  cd "$AND"
  ./gradlew :app:assembleRelease \
    -PFOCUSVPN_API_BASE="$API" \
    --no-daemon
)

OUT="$AND/app/build/outputs/apk/release"
for abi in arm64-v8a armeabi-v7a x86_64; do
  APK=$(find "$OUT" -name "*-${abi}-*.apk" | head -1)
  [[ -n "$APK" && -f "$APK" ]] || fail "no release APK produced for $abi"
  cp -f "$APK" "$DIST/android/focusvpn-release-${abi}.apk"
done
cp -f "$DIST/android/focusvpn-release-arm64-v8a.apk" "$DIST/android/focusvpn-release.apk"
CODE=$(grep -E 'versionCode[[:space:]]*=' "$AND/app/build.gradle.kts" | head -1 | grep -oE '[0-9]+')
NAME=$(grep -E 'versionName[[:space:]]*=' "$AND/app/build.gradle.kts" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
APK_URL="${FOCUSVPN_APK_URL:-https://focuspay.org/vpn.apk}"
cat >"$DIST/android/vpn-version.json" <<EOF
{"versionCode":${CODE},"versionName":"${NAME}","url":"${APK_URL}"}
EOF
cat >"$DIST/android/README.txt" <<EOF
FocusVPN Android sideload (Launch-L1)
DEFAULT_API_BASE baked in: $API

Install (allow unknown sources):
  adb install -r focusvpn-release.apk          # arm64-v8a, almost all modern phones
  vpn-version.json                             # put next to the public APK so the app can update itself
  focusvpn-release-armeabi-v7a.apk             # old 32-bit phones
  focusvpn-release-x86_64.apk                  # emulator / Chromebook

Signed release: set FOCUSVPN_STORE_FILE / FOCUSVPN_STORE_PASSWORD /
FOCUSVPN_KEY_ALIAS / FOCUSVPN_KEY_PASSWORD before this script.
Unsigned debug-keystore release is OK for closed testers only.
EOF
echo "release-android PASS → $DIST/android/focusvpn-release.apk"
