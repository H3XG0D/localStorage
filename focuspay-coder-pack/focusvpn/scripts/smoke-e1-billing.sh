#!/usr/bin/env bash
# E1: FocusVPN internal billing (telegram upsert + extend idempotent).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18093}"
API="http://127.0.0.1:${PORT}"
TOKEN="e1-smoke-token"
BIN="$(mktemp -d)"
LOG="$(mktemp)"
cleanup() { [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$BIN" "$LOG"; }
trap cleanup EXIT

go build -o "$BIN/server" ./backend/cmd/server
FOCUSVPN_HTTP_ADDR=":${PORT}" FOCUSVPN_STORE=memory FOCUSVPN_MEMORY_SEED=1 \
FOCUSVPN_INTERNAL_TOKEN="$TOKEN" FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true FOCUSVPN_AGENT_ADDR=off \
  "$BIN/server" >"$LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do curl -sf "$API/v1/health" >/dev/null 2>&1 && break; sleep 0.1; done
curl -sf "$API/v1/health" >/dev/null || { cat "$LOG"; exit 1; }

TG=900001
echo "==> upsert"
curl -sf -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"telegram_id\":$TG}" "$API/v1/internal/telegram/upsert" | grep -q user_id

echo "==> grant"
GRANT_BODY="{\"external_id\":\"smoke-ord-1\",\"telegram_id\":$TG,\"kind\":\"paid\",\"plan_code\":\"week\",\"days\":7,\"amount_rub\":\"300.00\"}"
EXT=$(curl -sf -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "$GRANT_BODY" "$API/v1/internal/billing/grant")
echo "$EXT"
echo "$EXT" | grep -q '"idempotent":false'

echo "==> grant idempotent"
EXT2=$(curl -sf -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "$GRANT_BODY" "$API/v1/internal/billing/grant")
echo "$EXT2" | grep -q '"idempotent":true'

echo "==> grant lookup"
curl -sf -H "X-Internal-Token: $TOKEN" "$API/v1/internal/billing/grants/smoke-ord-1" | grep -q '"amount_kopecks":30000'

echo "==> status"
curl -sf -H "X-Internal-Token: $TOKEN" \
  "$API/v1/internal/billing/status?telegram_id=$TG" | grep -q '"has_live":true'

echo "PASS: E1 FocusVPN internal billing upsert → grant → idempotent → lookup → status"
