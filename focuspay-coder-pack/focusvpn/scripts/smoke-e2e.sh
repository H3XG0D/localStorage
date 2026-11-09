#!/usr/bin/env bash
# Phase 2 Milestone 5 E2E smoke: register → device → connect → config → awg conf
# (with Jc/Jmin/Jmax) → disconnect. Real awg-quick/handshake is optional when tools
# and CAP_NET_ADMIN are available (set FOCUSVPN_E2E_REAL_TUNNEL=1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FOCUSVPN_SMOKE_PORT:-18081}"
API="http://127.0.0.1:${PORT}"
BIN_DIR="$(mktemp -d)"
SERVER_LOG="$(mktemp)"
CONF_DIR="$(mktemp -d)"
cleanup() {
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$BIN_DIR" "$SERVER_LOG" "$CONF_DIR"
}
trap cleanup EXIT

echo "==> building server and CLI"
go build -o "$BIN_DIR/server" ./backend/cmd/server
go build -o "$BIN_DIR/focusvpn-cli" ./clients/cli

echo "==> starting CP (memory + smoke seed + AllocationAutoActive for harness without agent)"
FOCUSVPN_HTTP_ADDR=":${PORT}" \
FOCUSVPN_STORE=memory \
FOCUSVPN_MEMORY_SEED=1 \
FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true \
FOCUSVPN_AGENT_ADDR=off \
  "$BIN_DIR/server" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

echo "==> waiting for /v1/health"
for _ in $(seq 1 50); do
  if "$BIN_DIR/focusvpn-cli" health --api "$API" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! "$BIN_DIR/focusvpn-cli" health --api "$API" >/dev/null 2>&1; then
  echo "FAIL: server unhealthy"; cat "$SERVER_LOG"; exit 1
fi

EMAIL="e2e+$(date +%s)@example.com"
PASS="supersecret-e2e-1"

echo "==> register + login"
REG="$("$BIN_DIR/focusvpn-cli" register --api "$API" --email "$EMAIL" --password "$PASS")"
ACCESS="$(printf '%s' "$REG" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
[[ -n "$ACCESS" ]] || { echo "FAIL: no access_token"; echo "$REG"; exit 1; }

echo "==> keygen (private key stays on device)"
KEYS="$("$BIN_DIR/focusvpn-cli" keygen)"
PRIV="$(printf '%s' "$KEYS" | sed -n 's/.*"private_key":"\([^"]*\)".*/\1/p')"
PUB="$(printf '%s' "$KEYS" | sed -n 's/.*"public_key":"\([^"]*\)".*/\1/p')"
[[ -n "$PRIV" && -n "$PUB" ]] || { echo "FAIL: keygen"; echo "$KEYS"; exit 1; }

echo "==> device-add"
DEV_OUT="$("$BIN_DIR/focusvpn-cli" device-add --api "$API" --access "$ACCESS" --name e2e --platform linux --pubkey "$PUB")"
DEVICE_ID="$(printf '%s' "$DEV_OUT" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)"
DEVICE_TOKEN="$(printf '%s' "$DEV_OUT" | sed -n 's/.*"device_token":"\([^"]*\)".*/\1/p')"
[[ -n "$DEVICE_ID" && -n "$DEVICE_TOKEN" ]] || { echo "FAIL: device-add"; echo "$DEV_OUT"; exit 1; }

echo "==> servers"
SRV="$("$BIN_DIR/focusvpn-cli" servers --api "$API" --access "$ACCESS")"
echo "$SRV" | grep -q 'amneziawg' || { echo "FAIL: no amneziawg endpoint"; echo "$SRV"; exit 1; }

echo "==> tunnel-up --dry-run (ConfigParts → .conf with Jc/Jmin/Jmax)"
UP="$("$BIN_DIR/focusvpn-cli" tunnel-up \
  --api "$API" --access "$ACCESS" \
  --device-id "$DEVICE_ID" --device-token "$DEVICE_TOKEN" \
  --private-key "$PRIV" --iface focusvpn0 --conf-dir "$CONF_DIR" --dry-run)"
echo "$UP"
CONN_ID="$(printf '%s' "$UP" | sed -n 's/.*"connection_id":"\([^"]*\)".*/\1/p')"
CONF_PATH="$(printf '%s' "$UP" | sed -n 's/.*"conf_path":"\([^"]*\)".*/\1/p')"
[[ -n "$CONN_ID" && -f "$CONF_PATH" ]] || { echo "FAIL: tunnel-up dry-run"; echo "$UP"; exit 1; }

echo "==> assert conf contains AmneziaWG obfuscation (Jc + H/S)"
grep -qE '^Jc = [1-9][0-9]*$' "$CONF_PATH" || { echo "FAIL: missing Jc"; cat "$CONF_PATH"; exit 1; }
grep -qE '^Jmin = [1-9][0-9]*$' "$CONF_PATH" || { echo "FAIL: missing Jmin"; cat "$CONF_PATH"; exit 1; }
grep -qE '^Jmax = [1-9][0-9]*$' "$CONF_PATH" || { echo "FAIL: missing Jmax"; cat "$CONF_PATH"; exit 1; }
grep -qE '^S1 = [0-9]+$' "$CONF_PATH" || { echo "FAIL: missing S1"; cat "$CONF_PATH"; exit 1; }
grep -qE '^H1 = .+$' "$CONF_PATH" || { echo "FAIL: missing H1"; cat "$CONF_PATH"; exit 1; }
grep -q '^\[Peer\]$' "$CONF_PATH" || { echo "FAIL: missing [Peer]"; cat "$CONF_PATH"; exit 1; }
grep -q 'PrivateKey =' "$CONF_PATH" || { echo "FAIL: missing PrivateKey"; exit 1; }

if [[ "${FOCUSVPN_E2E_REAL_TUNNEL:-0}" == "1" ]]; then
  if command -v awg-quick >/dev/null 2>&1 && command -v awg >/dev/null 2>&1; then
    echo "==> REAL tunnel: awg-quick up + handshake (requires CAP_NET_ADMIN + live peer)"
    # Bring interface up from already-written conf; handshake may fail without real node.
    if awg-quick up "$CONF_PATH"; then
      if "$BIN_DIR/focusvpn-cli" handshake --iface focusvpn0 --timeout 15s; then
        echo "PASS: handshake OK"
      else
        echo "WARN: handshake not observed (no live peer / agent); conf + awg-quick up succeeded"
      fi
      awg-quick down "$CONF_PATH" || true
    else
      echo "WARN: awg-quick up failed (permissions?); dry-run path already passed"
    fi
  else
    echo "WARN: FOCUSVPN_E2E_REAL_TUNNEL=1 but awg/awg-quick not installed — skipping real tunnel"
  fi
else
  echo "==> skip real tunnel (set FOCUSVPN_E2E_REAL_TUNNEL=1 when awg tools + node-agent available)"
fi

echo "==> tunnel-down (API revoke)"
"$BIN_DIR/focusvpn-cli" tunnel-down --api "$API" --access "$ACCESS" --id "$CONN_ID" --dry-run

echo "PASS: register → device → servers → tunnel-up(dry-run+Jc/Jmin/Jmax) → disconnect"
