#!/usr/bin/env bash
# Run FocusVPN CP + FocusPay vpn_wallet against SANDBOX DBs only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=sandbox-lib.sh
source "$ROOT/scripts/sandbox-lib.sh"
load_sandbox_env

FP_ROOT="${FOCUSPAY_ROOT:-/home/qwe/Desktop/focuspay/site/exchange-backend}"
if [[ ! -d "$FP_ROOT" ]]; then
  echo "FOCUSPAY_ROOT not found: $FP_ROOT" >&2
  exit 1
fi
assert_not_prod_focuspay_dsn "$DATABASE_DSN"

RUN_DIR="$ROOT/infra/sandbox/run"
mkdir -p "$RUN_DIR"
kill_pid() { local f="$1"; [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; }
kill_pid "$RUN_DIR/focusvpn.pid"
kill_pid "$RUN_DIR/focuspay.pid"

echo "==> FocusVPN CP :${FOCUSVPN_HTTP_ADDR#:}"
(
  cd "$ROOT"
  env FOCUSVPN_SANDBOX=1 \
    FOCUSVPN_HTTP_ADDR="$FOCUSVPN_HTTP_ADDR" \
    FOCUSVPN_STORE=postgres \
    FOCUSVPN_DATABASE_URL="$FOCUSVPN_DATABASE_URL" \
    FOCUSVPN_INTERNAL_TOKEN="$FOCUSVPN_INTERNAL_TOKEN" \
    FOCUSVPN_ALLOCATION_AUTO_ACTIVE="${FOCUSVPN_ALLOCATION_AUTO_ACTIVE:-true}" \
    FOCUSVPN_AGENT_ADDR=off \
    go run ./backend/cmd/server
) >"$RUN_DIR/focusvpn.log" 2>&1 &
echo $! >"$RUN_DIR/focusvpn.pid"

echo "==> FocusPay vpn_wallet SANDBOX app on $FOCUSPAY_WALLET_ADDR"
FP_HOST="${FOCUSPAY_WALLET_ADDR%:*}"
FP_PORT="${FOCUSPAY_WALLET_ADDR##*:}"
(
  cd "$ROOT"
  for venv in "$FP_ROOT/.venv" "$FP_ROOT/venv"; do
    # shellcheck disable=SC1091
    [[ -f "$venv/bin/activate" ]] && { source "$venv/bin/activate"; break; }
  done
  env FOCUSVPN_SANDBOX=1 \
    FOCUSPAY_ROOT="$FP_ROOT" \
    DATABASE_DSN="$DATABASE_DSN" \
    VPN_INTERNAL_TOKEN="$VPN_INTERNAL_TOKEN" \
    FOCUSVPN_API_BASE="http://127.0.0.1${FOCUSVPN_HTTP_ADDR}" \
    FOCUSPAY_WALLET_ADDR="$FOCUSPAY_WALLET_ADDR" \
    python3 scripts/sandbox_focuspay_wallet.py
) >"$RUN_DIR/focuspay.log" 2>&1 &
echo $! >"$RUN_DIR/focuspay.pid"

MV_URL="http://127.0.0.1${FOCUSVPN_HTTP_ADDR}"
FP_URL="http://${FOCUSPAY_WALLET_ADDR}"
for _ in $(seq 1 60); do
  curl -sf "$MV_URL/v1/health" >/dev/null 2>&1 && curl -sf "$FP_URL/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -sf "$MV_URL/v1/health" >/dev/null || { echo "FocusVPN failed"; tail -40 "$RUN_DIR/focusvpn.log"; exit 1; }
curl -sf "$FP_URL/health" >/dev/null || { echo "FocusPay wallet failed"; tail -40 "$RUN_DIR/focuspay.log"; exit 1; }

echo "SANDBOX SERVICES RUNNING"
echo "  FocusVPN:    $MV_URL   (pid $(cat "$RUN_DIR/focusvpn.pid"))"
echo "  FocusPay: $FP_URL   (pid $(cat "$RUN_DIR/focuspay.pid"))"
echo "  logs:     $RUN_DIR/*.log"
echo "  stop:     make sandbox-stop"
