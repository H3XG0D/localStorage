#!/usr/bin/env bash
# Phase 3 M2: desktop AppCore bindings (FocusPay-styled GUI companion).
# login → servers → select → connect(dry-run+Jc/Jmin/Jmax) → disconnect → logout
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18092}"
API="http://127.0.0.1:${PORT}"
BIN_DIR="$(mktemp -d)"
DATA_DIR="$(mktemp -d)"
CONF_DIR="$(mktemp -d)"
SERVER_LOG="$(mktemp)"
cleanup() {
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$BIN_DIR" "$DATA_DIR" "$CONF_DIR" "$SERVER_LOG"
}
trap cleanup EXIT

echo "==> build CP + focusvpn-desktop + focusvpn-gui stub"
go build -o "$BIN_DIR/server" ./backend/cmd/server
go build -o "$BIN_DIR/focusvpn-desktop" ./clients/desktop/cmd/focusvpn-desktop
go build -o "$BIN_DIR/focusvpn-gui" ./clients/desktop/cmd/focusvpn-gui
"$BIN_DIR/focusvpn-gui" 2>&1 | grep -qiE 'wails|webkit|smoke-desktop'

echo "==> start CP (memory seed + auto-active)"
FOCUSVPN_HTTP_ADDR=":${PORT}" FOCUSVPN_STORE=memory FOCUSVPN_MEMORY_SEED=1 \
FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true FOCUSVPN_AGENT_ADDR=off \
  "$BIN_DIR/server" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do
  curl -sf "$API/v1/health" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$API/v1/health" >/dev/null || { echo "FAIL: health"; cat "$SERVER_LOG"; exit 1; }

EMAIL="desktop+$(date +%s)@example.com"
PASS="supersecret-desktop-1"

echo "==> register"
"$BIN_DIR/focusvpn-desktop" register --api "$API" --email "$EMAIL" --password "$PASS" --data-dir "$DATA_DIR"

echo "==> status"
"$BIN_DIR/focusvpn-desktop" status --data-dir "$DATA_DIR" | grep -q '"logged_in":true'

echo "==> servers + select"
SERVERS="$("$BIN_DIR/focusvpn-desktop" servers --data-dir "$DATA_DIR")"
echo "$SERVERS"
echo "$SERVERS" | grep -q 'DE-01'
"$BIN_DIR/focusvpn-desktop" select --node DE-01 --data-dir "$DATA_DIR"

echo "==> connect --dry-run"
OUT="$("$BIN_DIR/focusvpn-desktop" connect --data-dir "$DATA_DIR" --conf-dir "$CONF_DIR" --dry-run)"
echo "$OUT"
CONF="$(printf '%s' "$OUT" | sed -n 's/.*"conf_path":"\([^"]*\)".*/\1/p')"
[[ -f "$CONF" ]] || { echo "FAIL: no conf"; exit 1; }
grep -qE '^Jc = [1-9][0-9]*$' "$CONF"
grep -qE '^Jmin = [1-9][0-9]*$' "$CONF"
grep -qE '^Jmax = [1-9][0-9]*$' "$CONF"
grep -qE '^S1 = [0-9]+$' "$CONF"
grep -qE '^H1 = .+$' "$CONF"

echo "==> status connected"
"$BIN_DIR/focusvpn-desktop" status --data-dir "$DATA_DIR" | grep -q '"state":"connected"'

echo "==> disconnect + logout"
"$BIN_DIR/focusvpn-desktop" disconnect --data-dir "$DATA_DIR"
"$BIN_DIR/focusvpn-desktop" logout --data-dir "$DATA_DIR"

echo "PASS: desktop bindings login → locations → connect(dry-run) → disconnect → logout"
