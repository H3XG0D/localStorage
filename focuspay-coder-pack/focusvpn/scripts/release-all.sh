#!/usr/bin/env bash
# release-all.sh — Linux + Windows always; Android when ANDROID_HOME set.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="${FOCUSVPN_API_BASE:?set FOCUSVPN_API_BASE}"
DIST="${FOCUSVPN_DIST:-$ROOT/dist}"
mkdir -p "$DIST"
echo "==> release-all API=$API → $DIST"
bash "$ROOT/scripts/release-linux.sh"
bash "$ROOT/scripts/release-windows.sh"
if [[ -n "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}" ]]; then
  bash "$ROOT/scripts/release-android.sh"
else
  echo "  skip android (ANDROID_HOME unset) — linux/windows artifacts ready"
  mkdir -p "$DIST/android"
  echo "Set ANDROID_HOME and re-run make release-android" >"$DIST/android/SKIPPED.txt"
fi
# Manifest for landing page
cat >"$DIST/MANIFEST.txt" <<EOF
FocusVPN Launch-L1 sideload artifacts
API: $API
Built: $(date -u +%Y-%m-%dT%H:%MZ)
linux/focusvpn
windows/focusvpn-windows.exe
android/focusvpn-release.apk (if built)
EOF
echo "release-all PASS"
ls -la "$DIST"/*/ 2>/dev/null || ls -la "$DIST"
