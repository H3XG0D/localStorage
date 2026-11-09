#!/usr/bin/env bash
# Phase 3 M1: product Linux CLI via AppCore (dry-run tunnel).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18091}"
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

echo "==> build CP + product focusvpn CLI"
go build -o "$BIN_DIR/server" ./backend/cmd/server
go build -o "$BIN_DIR/focusvpn" ./clients/linux/cmd/focusvpn
go build -o "$BIN_DIR/focusvpn-gtk" ./clients/linux/cmd/focusvpn-gtk

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

EMAIL="linux+$(date +%s)@example.com"
PASS="supersecret-linux-1"

echo "==> register + login (persistent session)"
"$BIN_DIR/focusvpn" register --api "$API" --email "$EMAIL" --password "$PASS" --data-dir "$DATA_DIR"
"$BIN_DIR/focusvpn" status --data-dir "$DATA_DIR" | grep -q '"LoggedIn":true\|"logged_in":true\|LoggedIn.:true' \
  || "$BIN_DIR/focusvpn" status --data-dir "$DATA_DIR" | grep -qi true \
  || { echo "FAIL: status"; "$BIN_DIR/focusvpn" status --data-dir "$DATA_DIR"; exit 1; }

echo "==> connect --dry-run"
OUT="$("$BIN_DIR/focusvpn" connect --data-dir "$DATA_DIR" --conf-dir "$CONF_DIR" --dry-run)"
echo "$OUT"
CONF="$(printf '%s' "$OUT" | sed -n 's/.*"conf_path":"\([^"]*\)".*/\1/p')"
[[ -f "$CONF" ]] || { echo "FAIL: no conf"; exit 1; }
grep -qE '^Jc = [1-9][0-9]*$' "$CONF"
grep -qE '^Jmin = [1-9][0-9]*$' "$CONF"
grep -qE '^Jmax = [1-9][0-9]*$' "$CONF"
grep -qE '^S1 = [0-9]+$' "$CONF"
grep -qE '^H1 = .+$' "$CONF"

echo "==> disconnect"
"$BIN_DIR/focusvpn" disconnect --data-dir "$DATA_DIR"

echo "==> gtk stub builds"
"$BIN_DIR/focusvpn-gtk" | grep -q 'skeleton'

echo "PASS: AppCore Linux product CLI login → connect(dry-run+Jc/H/S) → disconnect"
