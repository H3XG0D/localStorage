#!/usr/bin/env bash
# P4-M3: Xray VLESS+REALITY engine (JSON only; no Xray source link).
# Uses FOCUSVPN_ENGINE=xray dry-run — CP still returns xray:null → synthetic client JSON.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18094}"
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

echo "==> build CP + focusvpn-desktop (xray engine)"
go build -o "$BIN_DIR/server" ./backend/cmd/server
go build -o "$BIN_DIR/focusvpn-desktop" ./clients/desktop/cmd/focusvpn-desktop

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

EMAIL="xray+$(date +%s)@example.com"
PASS="supersecret-xray-1"

echo "==> register"
FOCUSVPN_ENGINE=xray "$BIN_DIR/focusvpn-desktop" register --api "$API" --email "$EMAIL" --password "$PASS" --data-dir "$DATA_DIR"

echo "==> select + connect --dry-run (synthetic REALITY JSON)"
FOCUSVPN_ENGINE=xray "$BIN_DIR/focusvpn-desktop" select --node DE-01 --data-dir "$DATA_DIR"
OUT="$(FOCUSVPN_ENGINE=xray "$BIN_DIR/focusvpn-desktop" connect --data-dir "$DATA_DIR" --conf-dir "$CONF_DIR" --dry-run)"
echo "$OUT"
CONF="$(printf '%s' "$OUT" | sed -n 's/.*"conf_path":"\([^"]*\)".*/\1/p')"
[[ -f "$CONF" ]] || { echo "FAIL: no json"; exit 1; }
grep -q '"vless"' "$CONF"
grep -q '"reality"' "$CONF"
grep -q 'xtls-rprx-vision' "$CONF"

echo "==> status connected"
FOCUSVPN_ENGINE=xray "$BIN_DIR/focusvpn-desktop" status --data-dir "$DATA_DIR" | grep -q '"state":"connected"'

echo "==> disconnect + logout"
FOCUSVPN_ENGINE=xray "$BIN_DIR/focusvpn-desktop" disconnect --data-dir "$DATA_DIR"
FOCUSVPN_ENGINE=xray "$BIN_DIR/focusvpn-desktop" logout --data-dir "$DATA_DIR"

echo "PASS: xray engine dry-run (VLESS+REALITY JSON) → disconnect"
