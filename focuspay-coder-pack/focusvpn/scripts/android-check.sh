#!/usr/bin/env bash
# Android client: VLESS via libXray. Full assemble runs when the SDK is present.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AND="$ROOT/clients/android"

fail() { echo "android-check FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> android-check (VLESS / libXray)"

[[ -f "$AND/settings.gradle.kts" ]] || fail "missing settings.gradle.kts"
[[ -f "$AND/app/build.gradle.kts" ]] || fail "missing app/build.gradle.kts"
[[ -f "$AND/README.md" ]] || fail "missing clients/android/README.md"
ok "gradle project files"

need=(
  "app/src/main/AndroidManifest.xml"
  "app/src/main/java/com/focusvpn/app/MainActivity.kt"
  "app/src/main/java/com/focusvpn/app/data/ControlPlaneClient.kt"
  "app/src/main/java/com/focusvpn/app/data/SessionStore.kt"
  "app/src/main/java/com/focusvpn/app/crypto/X25519Keys.kt"
  "app/src/main/java/com/focusvpn/app/vpn/XrayClientConfig.kt"
  "app/src/main/java/com/focusvpn/app/vpn/XrayTunnelEngine.kt"
  "app/src/main/java/com/focusvpn/app/vpn/FocusVpnService.kt"
  "app/src/main/java/com/focusvpn/app/ui/theme/Theme.kt"
  "app/src/main/java/com/focusvpn/app/ui/screens/AuthScreen.kt"
  "app/src/main/java/com/focusvpn/app/ui/screens/HomeScreen.kt"
  "app/src/main/java/com/focusvpn/app/ui/screens/LocationsScreen.kt"
  "app/src/main/java/com/focusvpn/app/ui/screens/AccountScreen.kt"
  "app/src/test/java/com/focusvpn/app/crypto/X25519KeysTest.kt"
  "app/src/test/java/com/focusvpn/app/vpn/XrayClientConfigTest.kt"
)
for f in "${need[@]}"; do
  [[ -f "$AND/$f" ]] || fail "missing $f"
done
ok "Compose screens + VpnService + Xray config"

grep -q '"vless"' "$AND/app/src/main/java/com/focusvpn/app/data/ControlPlaneClient.kt" \
  || fail "createConnection must request vless"
grep -q 'X25519Keys' "$AND/app/src/main/java/com/focusvpn/app/data/ControlPlaneClient.kt" \
  || fail "keygen must use X25519Keys"
grep -q 'ActiveTunnel' "$AND/app/src/main/java/com/focusvpn/app/vpn/FocusVpnService.kt" \
  || fail "FocusVpnService must read ActiveTunnel"
grep -q 'XrayTunnelEngine' "$AND/app/src/main/java/com/focusvpn/app/vpn/FocusVpnService.kt" \
  || fail "FocusVpnService must drive XrayTunnelEngine"
grep -q 'libXray' "$AND/app/src/main/java/com/focusvpn/app/vpn/XrayTunnelEngine.kt" \
  || fail "engine must call libXray"
grep -q 'protectFd' "$AND/app/src/main/java/com/focusvpn/app/vpn/XrayTunnelEngine.kt" \
  || fail "engine must protect Xray sockets"
grep -q 'preferred_node\|preferredNode' "$AND/app/src/main/java/com/focusvpn/app/data/ControlPlaneClient.kt" \
  || fail "createConnection must send preferred_node"
grep -q 'EncryptedSharedPreferences' "$AND/app/src/main/java/com/focusvpn/app/data/SessionStore.kt" \
  || fail "SessionStore must use EncryptedSharedPreferences"
grep -qi 'libXray' "$ROOT/NOTICE.md" || fail "NOTICE.md missing libXray note"
grep -qi 'bouncycastle\|Bouncy Castle' "$ROOT/NOTICE.md" || fail "NOTICE.md missing BouncyCastle note"
grep -q 'bcprov-jdk18on' "$AND/app/build.gradle.kts" || fail "bcprov dependency missing"
grep -q 'libXray.aar' "$AND/app/build.gradle.kts" || fail "libXray.aar dependency missing"
grep -q 'fetch-libxray-android' "$AND/README.md" || fail "README must document the libXray fetch"
ok "VLESS + libXray + preferred_node + NOTICE"

if [[ -n "${ANDROID_HOME:-}${ANDROID_SDK_ROOT:-}" ]]; then
  echo "==> ANDROID_HOME set — running unit tests + assembleDebug"
  [[ -f "$AND/.libxray/libXray.aar" ]] || bash "$ROOT/scripts/fetch-libxray-android.sh"
  if [[ -x "$AND/gradlew" ]]; then
    (cd "$AND" && ./gradlew :app:testDebugUnitTest :app:assembleDebug)
  else
    fail "ANDROID_HOME set but clients/android/gradlew missing"
  fi
else
  echo "==> skip assemble (ANDROID_HOME unset)"
fi

echo "android-check PASS"
