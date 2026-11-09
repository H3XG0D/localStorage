#!/usr/bin/env bash
# E2: Telegram app login (start → attach → wait + pair code).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18094}"
API="http://127.0.0.1:${PORT}"
TOKEN="e2-smoke-token"
BIN="$(mktemp -d)"
LOG="$(mktemp)"
cleanup() { [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$BIN" "$LOG"; }
trap cleanup EXIT

go build -o "$BIN/server" ./backend/cmd/server
FOCUSVPN_HTTP_ADDR=":${PORT}" FOCUSVPN_STORE=memory FOCUSVPN_MEMORY_SEED=1 \
FOCUSVPN_INTERNAL_TOKEN="$TOKEN" FOCUSVPN_TELEGRAM_BOT_USERNAME="TestBot" \
FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true FOCUSVPN_AGENT_ADDR=off \
  "$BIN/server" >"$LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do curl -sf "$API/v1/health" >/dev/null 2>&1 && break; sleep 0.1; done
curl -sf "$API/v1/health" >/dev/null || { cat "$LOG"; exit 1; }

echo "==> start"
START=$(curl -sf -X POST "$API/v1/auth/telegram/start")
echo "$START" | grep -q deep_link
WAIT=$(echo "$START" | sed -n 's/.*"wait_token":"\([^"]*\)".*/\1/p')
START_RAW=$(echo "$START" | sed -n 's/.*vpnauth_\([a-f0-9]*\).*/\1/p')
[[ -n "$WAIT" && -n "$START_RAW" ]]

echo "==> wait pending"
CODE=$(curl -s -o /tmp/wait.json -w "%{http_code}" "$API/v1/auth/telegram/wait?wait_token=$WAIT")
[[ "$CODE" == "202" ]]

echo "==> attach"
curl -sf -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"start_token\":\"vpnauth_$START_RAW\",\"telegram_id\":88001}" \
  "$API/v1/internal/telegram/attach-login" | grep -q attached

echo "==> wait tokens"
curl -sf "$API/v1/auth/telegram/wait?wait_token=$WAIT" | grep -q access_token

echo "==> pair code"
PC=$(curl -sf -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"telegram_id":88002}' "$API/v1/internal/telegram/login-code")
PAIR=$(echo "$PC" | sed -n 's/.*"code":"\([^"]*\)".*/\1/p')
curl -sf -H 'Content-Type: application/json' -d "{\"code\":\"$PAIR\"}" \
  "$API/v1/auth/telegram/code" | grep -q refresh_token

echo "PASS: applogin deep-link + pair code"
