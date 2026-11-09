#!/usr/bin/env bash
# P3-M5b: validate Windows amneziawg-go + wintun bridge.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WIN="$ROOT/clients/windows"

fail() { echo "windows-check FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> windows-check (P3-M5b amneziawg-go bridge)"

[[ -f "$WIN/README.md" ]] || fail "missing clients/windows/README.md"
[[ -f "$WIN/wails.json" ]] || fail "missing wails.json"
ok "README + wails.json"

need=(
  "app/app.go"
  "engine/wintun.go"
  "engine/wintun_load_windows.go"
  "engine/wintun_load_stub.go"
  "storage/store.go"
  "storage/protect_windows.go"
  "storage/protect_other.go"
  "cmd/focusvpn-windows/main.go"
  "cmd/focusvpn-windows-gui/stub.go"
  "engine/wintun_test.go"
  "storage/store_test.go"
)
for f in "${need[@]}"; do
  [[ -f "$WIN/$f" ]] || fail "missing $f"
done
ok "app + wintun engine + DPAPI storage + cmds"

grep -q 'LoadLibraryEx\|probeWintun' "$WIN/engine/wintun_load_windows.go" \
  || fail "Windows probe must use LoadLibraryEx"
grep -q 'CryptProtectData' "$WIN/storage/protect_windows.go" \
  || fail "DPAPI CryptProtectData missing"
grep -qi 'wintun' "$ROOT/NOTICE.md" || fail "NOTICE.md missing wintun note"
grep -qi 'amneziawg-windows' "$ROOT/NOTICE.md" || fail "NOTICE.md missing amneziawg-windows note"
grep -q 'NewGo\|GoEngine' "$WIN/engine/wintun.go" || fail "WintunEngine must delegate to GoEngine"
ok "LoadLibraryEx + DPAPI + NOTICE + GoEngine bridge"

echo "==> go test ./clients/windows/..."
(cd "$ROOT" && go test ./clients/windows/...)

echo "==> smoke-windows"
bash "$ROOT/scripts/smoke-windows.sh"

echo "windows-check PASS"
