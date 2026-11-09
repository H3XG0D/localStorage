#!/usr/bin/env bash
# P3-M4c: validate Apple AmneziaWG packet-IO bridge without requiring Xcode.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/clients/apple"

fail() { echo "apple-check FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> apple-check (P3-M4c packet IO bridge)"

[[ -f "$APP/project.yml" ]] || fail "missing project.yml"
[[ -f "$APP/Package.swift" ]] || fail "missing Package.swift"
[[ -f "$APP/README.md" ]] || fail "missing clients/apple/README.md"
ok "project.yml + Package.swift + README"

need=(
  "Sources/Shared/Models.swift"
  "Sources/Shared/ControlPlaneClient.swift"
  "Sources/Shared/ConfigPartsParse.swift"
  "Sources/Shared/TunnelConfig.swift"
  "Sources/Shared/AwgConfig.swift"
  "Sources/Shared/X25519Keys.swift"
  "Sources/Shared/SessionStore.swift"
  "Sources/Shared/Theme.swift"
  "Sources/Shared/TunnelController.swift"
  "Sources/Tunnel/PacketTunnelProvider.swift"
  "Sources/Tunnel/AmneziaTunnelEngine.swift"
  "Sources/Tunnel/AmneziaGoBridge.swift"
  "Sources/App/FocusVPNApp.swift"
  "Sources/App/AppModel.swift"
  "Sources/App/Views/AuthView.swift"
  "Sources/App/Views/HomeView.swift"
  "Sources/App/Views/LocationsView.swift"
  "Sources/App/Views/AccountView.swift"
  "Tests/ConfigPartsParseTests.swift"
  "TestsSPM/ConfigPartsParseSPMTests.swift"
  "Config/App.entitlements"
  "Config/Tunnel.entitlements"
)
for f in "${need[@]}"; do
  [[ -f "$APP/$f" ]] || fail "missing $f"
done
ok "SwiftUI screens + PacketTunnel + AwgConfig + engine + tests"

grep -q 'junk_packet_count' "$APP/Sources/Shared/ConfigPartsParse.swift" \
  || fail "ConfigPartsParse missing Jc fields"
grep -q 'TunnelConfig' "$APP/Sources/Tunnel/PacketTunnelProvider.swift" \
  || fail "PacketTunnelProvider must use TunnelConfig"
grep -q 'AmneziaTunnelEngine' "$APP/Sources/Tunnel/PacketTunnelProvider.swift" \
  || fail "PacketTunnelProvider must drive AmneziaTunnelEngine"
grep -q 'toUapi' "$APP/Sources/Shared/AwgConfig.swift" \
  || fail "AwgConfig.toUapi missing"
grep -q 'jc=' "$APP/Sources/Shared/AwgConfig.swift" \
  || fail "UAPI must include jc="
grep -q 'wgTurnOn\|AmneziaGoBridge' "$APP/Sources/Tunnel/AmneziaGoBridge.swift" \
  || fail "AmneziaGoBridge missing"
grep -q 'tunnelFileDescriptor' "$APP/Sources/Tunnel/AmneziaTunnelEngine.swift" \
  || fail "engine must locate utun FD"
grep -q 'X25519Keys' "$APP/Sources/Shared/ControlPlaneClient.swift" \
  || fail "keygen must use X25519Keys"
grep -q 'preferredNode\|preferred_node' "$APP/Sources/Shared/ControlPlaneClient.swift" \
  || fail "createConnection must send preferred_node"
grep -q 'AwgConfig.swift' "$APP/project.yml" \
  || fail "project.yml must compile AwgConfig into tunnel extension"
grep -q 'kSecAttrAccessibleAfterFirstUnlock' "$APP/Sources/Shared/SessionStore.swift" \
  || fail "SessionStore must use Keychain AfterFirstUnlock"
grep -qi 'wireguard-apple' "$ROOT/NOTICE.md" || fail "NOTICE.md missing wireguard-apple note"
grep -qi 'amneziawg-apple' "$ROOT/NOTICE.md" || fail "NOTICE.md missing amneziawg-apple note"
grep -q 'wizard-apple-native\|v2.0.3' "$APP/README.md" \
  || fail "README must document apple native wizard / v2.0.3"
ok "UAPI + engine + preferred_node + NOTICE"

if command -v xcodebuild >/dev/null 2>&1 && command -v xcodegen >/dev/null 2>&1; then
  echo "==> Xcode + xcodegen present — generating and building iOS simulator"
  (cd "$APP" && xcodegen generate && xcodebuild -scheme FocusVPN -destination 'generic/platform=iOS Simulator' -quiet build)
elif command -v swift >/dev/null 2>&1; then
  echo "==> swift present — running Package.swift ConfigParts/TunnelConfig/AwgConfig tests"
  (cd "$APP" && swift test --package-path .)
else
  echo "==> skip build (no Xcode/swift on this host)"
fi

echo "apple-check PASS"
