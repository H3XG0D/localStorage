#!/usr/bin/env bash
# Reproducible Phase 2 Milestone 1 vertical-slice smoke test.
# Builds the server + CLI, starts the server with the in-memory store and
# ephemeral dev keys, then drives register -> login -> refresh through the CLI
# harness and asserts success. No external services required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18080}"
API="http://127.0.0.1:${PORT}"
BIN_DIR="$(mktemp -d)"
SERVER_LOG="$(mktemp)"
cleanup() {
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$BIN_DIR" "$SERVER_LOG"
}
trap cleanup EXIT

echo "==> building server and CLI"
go build -o "$BIN_DIR/server" ./backend/cmd/server
go build -o "$BIN_DIR/focusvpn-cli" ./clients/cli

echo "==> starting control plane on ${API} (memory store, ephemeral keys)"
FOCUSVPN_HTTP_ADDR=":${PORT}" FOCUSVPN_STORE=memory "$BIN_DIR/server" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

echo "==> waiting for /v1/health"
for _ in $(seq 1 50); do
  if "$BIN_DIR/focusvpn-cli" health --api "$API" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! "$BIN_DIR/focusvpn-cli" health --api "$API" >/dev/null 2>&1; then
  echo "FAIL: server did not become healthy"; cat "$SERVER_LOG"; exit 1
fi

EMAIL="smoke+$(date +%s)@example.com"
PASS="supersecret-smoke-1"

echo "==> register"
REG_OUT="$("$BIN_DIR/focusvpn-cli" register --api "$API" --email "$EMAIL" --password "$PASS")"
echo "$REG_OUT" | grep -q '"access_token"' || { echo "FAIL: no access_token in register"; echo "$REG_OUT"; exit 1; }

echo "==> login"
LOGIN_OUT="$("$BIN_DIR/focusvpn-cli" login --api "$API" --email "$EMAIL" --password "$PASS")"
REFRESH_TOKEN="$(printf '%s' "$LOGIN_OUT" | sed -n 's/.*"refresh_token":"\([^"]*\)".*/\1/p')"
[[ -n "$REFRESH_TOKEN" ]] || { echo "FAIL: no refresh_token in login"; echo "$LOGIN_OUT"; exit 1; }

echo "==> refresh"
REFRESH_OUT="$("$BIN_DIR/focusvpn-cli" refresh --api "$API" --refresh "$REFRESH_TOKEN")"
echo "$REFRESH_OUT" | grep -q '"access_token"' || { echo "FAIL: no access_token in refresh"; echo "$REFRESH_OUT"; exit 1; }

echo "==> reuse of old refresh token must fail (reuse detection)"
if "$BIN_DIR/focusvpn-cli" refresh --api "$API" --refresh "$REFRESH_TOKEN" >/dev/null 2>&1; then
  echo "FAIL: reused refresh token was accepted"; exit 1
fi

echo "PASS: register -> login -> refresh -> reuse-detected"
