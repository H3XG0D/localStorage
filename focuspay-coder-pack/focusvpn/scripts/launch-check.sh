#!/usr/bin/env bash
# launch-check — validate Launch-L1 scripts/templates without VPS access.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail() { echo "launch-check FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> launch-check (Launch-L1 sideload path)"

[[ -f "$ROOT/docs/plans/Launch-L1.md" ]] || fail "missing plans/Launch-L1.md"
[[ -x "$ROOT/scripts/wizard-launch-l1.sh" ]] || fail "missing wizard-launch-l1.sh"
[[ -x "$ROOT/scripts/provision-cp.sh" ]] || fail "missing provision-cp.sh"
[[ -x "$ROOT/scripts/provision-node.sh" ]] || fail "missing provision-node.sh"
[[ -x "$ROOT/scripts/release-linux.sh" ]] || fail "missing release-linux.sh"
[[ -x "$ROOT/scripts/release-windows.sh" ]] || fail "missing release-windows.sh"
[[ -x "$ROOT/scripts/release-android.sh" ]] || fail "missing release-android.sh"
[[ -x "$ROOT/scripts/release-all.sh" ]] || fail "missing release-all.sh"
[[ -f "$ROOT/infra/launch/env.cp.example" ]] || fail "missing env.cp.example"
[[ -f "$ROOT/infra/launch/env.node.example" ]] || fail "missing env.node.example"
[[ -f "$ROOT/infra/launch/Caddyfile.example" ]] || fail "missing Caddyfile.example"
[[ -f "$ROOT/infra/launch/focusvpn-backend.service" ]] || fail "missing focusvpn-backend.service"
[[ -f "$ROOT/infra/launch/focusvpn-agent.service" ]] || fail "missing focusvpn-agent.service"
[[ -f "$ROOT/websites/landing/index.html" ]] || fail "missing landing index.html"
ok "plan + scripts + infra + landing"

grep -q 'FOCUSVPN_API_BASE' "$ROOT/clients/android/app/build.gradle.kts" \
  || fail "Android gradle must accept FOCUSVPN_API_BASE"
grep -q 'defaultAPIBase' "$ROOT/clients/linux/cmd/focusvpn/main.go" \
  || fail "Linux client must have defaultAPIBase ldflag"
grep -q 'defaultAPIBase' "$ROOT/clients/windows/cmd/focusvpn-windows/main.go" \
  || fail "Windows client must have defaultAPIBase ldflag"
grep -q 'Launch-L1' "$ROOT/docs/DEPLOYMENT.md" || fail "DEPLOYMENT must document Launch-L1"
ok "API bake-in + DEPLOYMENT"

# Dry build linux/windows with placeholder API (no network needed)
export FOCUSVPN_API_BASE="${FOCUSVPN_API_BASE:-https://api.example.com}"
export FOCUSVPN_DIST="${FOCUSVPN_DIST:-$ROOT/dist}"
bash "$ROOT/scripts/release-linux.sh"
bash "$ROOT/scripts/release-windows.sh"
[[ -x "$FOCUSVPN_DIST/linux/focusvpn" ]] || fail "linux binary missing"
[[ -f "$FOCUSVPN_DIST/windows/focusvpn-windows.exe" ]] || fail "windows exe missing"
ok "built linux + windows into dist/"

# Confirm ldflag baked
if grep -a -q 'api.example.com' "$FOCUSVPN_DIST/linux/focusvpn"; then
  ok "linux binary contains API host"
else
  echo "  note: API string not found in binary; binary still built"
fi

echo "launch-check PASS"
