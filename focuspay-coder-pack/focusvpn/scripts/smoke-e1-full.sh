#!/usr/bin/env bash
# E1 full path: FocusPay-stub billing saga + FocusVPN grants (plans, trial, gate, idempotency).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MV_PORT="${FOCUSVPN_SMOKE_PORT:-18093}"
FP_PORT="${FOCUSPAY_SMOKE_PORT:-18094}"
MV_API="http://127.0.0.1:${MV_PORT}"
FP_API="http://127.0.0.1:${FP_PORT}"
TOKEN="e1-full-smoke-token"
TG=900042
BIN="$(mktemp -d)"
cleanup() {
  [[ -n "${MV_PID:-}" ]] && kill "$MV_PID" 2>/dev/null || true
  [[ -n "${FP_PID:-}" ]] && kill "$FP_PID" 2>/dev/null || true
  rm -rf "$BIN"
}
trap cleanup EXIT

echo "==> deps (fastapi/uvicorn/httpx for stub + bot client)"
python3 -c "import fastapi,uvicorn,httpx" 2>/dev/null || pip install -q fastapi uvicorn httpx

echo "==> build FocusVPN CP"
go build -o "$BIN/server" ./backend/cmd/server

echo "==> start FocusPay stub :${FP_PORT}"
VPN_INTERNAL_TOKEN="$TOKEN" FOCUSVPN_API_BASE="$MV_API" FOCUSVPN_INTERNAL_TOKEN="$TOKEN" PORT="$FP_PORT" \
  python3 scripts/e1_focuspay_stub.py >"$BIN/fp.log" 2>&1 &
FP_PID=$!

echo "==> start FocusVPN :${MV_PORT}"
FOCUSVPN_HTTP_ADDR=":${MV_PORT}" FOCUSVPN_STORE=memory FOCUSVPN_MEMORY_SEED=1 \
FOCUSVPN_INTERNAL_TOKEN="$TOKEN" FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true FOCUSVPN_AGENT_ADDR=off \
  "$BIN/server" >"$BIN/mv.log" 2>&1 &
MV_PID=$!

for _ in $(seq 1 50); do
  curl -sf "$FP_API/health" >/dev/null 2>&1 && curl -sf "$MV_API/v1/health" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$FP_API/health" >/dev/null || { echo FAIL fp; cat "$BIN/fp.log"; exit 1; }
curl -sf "$MV_API/v1/health" >/dev/null || { echo FAIL mv; cat "$BIN/mv.log"; exit 1; }

HDR=(-H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json")

credit() { curl -sf -X POST "$FP_API/__smoke/credit" -H 'Content-Type: application/json' -d "$1" >/dev/null; }
code() { curl -s -o /dev/null -w '%{http_code}' "${HDR[@]}" -d "$2" "$FP_API/api/internal/vpn/$1"; }

echo "==> plans"
curl -sf "${HDR[@]}" "$FP_API/api/internal/vpn/plans" | grep -q '"code":"q3"'

echo "==> purchase week from balance (300₽)"
credit "{\"telegram_id\":$TG,\"amount_rub\":300}"
BUY="{\"telegram_id\":$TG,\"plan_code\":\"week\",\"idem_key\":\"smoke-buy-1\"}"
curl -sf "${HDR[@]}" -d "$BUY" "$FP_API/api/internal/vpn/purchase" | grep -q '"status":"paid"'
curl -sf -H "X-Internal-Token: $TOKEN" "$MV_API/v1/internal/billing/status?telegram_id=$TG" | grep -q '"has_live":true'

echo "==> double press = one charge"
curl -sf "${HDR[@]}" -d "$BUY" "$FP_API/api/internal/vpn/purchase" | grep -q '"replay":true'
curl -sf "${HDR[@]}" "$FP_API/api/internal/vpn/status/$TG" | grep -q '"available_rub":0.0'

echo "==> insufficient funds -> 402"
[[ "$(code purchase "{\"telegram_id\":$TG,\"plan_code\":\"month\",\"idem_key\":\"smoke-buy-2\"}")" == 402 ]]

echo "==> exchange gate: 3 of 10 exchanges -> purchase 403, trial still open"
TG2=$((TG + 1))
credit "{\"telegram_id\":$TG2,\"amount_rub\":5000,\"exchanges\":3}"
[[ "$(code purchase "{\"telegram_id\":$TG2,\"plan_code\":\"week\",\"idem_key\":\"smoke-buy-3\"}")" == 403 ]]
curl -s "${HDR[@]}" -d "{\"telegram_id\":$TG2,\"plan_code\":\"week\",\"idem_key\":\"smoke-buy-3\"}" "$FP_API/api/internal/vpn/purchase" | grep -q '"code":"exchange_gate"'
curl -sf "${HDR[@]}" "$FP_API/api/internal/vpn/status/$TG2" | grep -q '"exchanges":{"have":3,"need":10}'
curl -sf "${HDR[@]}" -d "{\"telegram_id\":$TG2,\"idem_key\":\"smoke-trial-gated\"}" "$FP_API/api/internal/vpn/trial" | grep -q '"status":"paid"'

echo "==> trial once"
TG3=$((TG + 2))
curl -sf "${HDR[@]}" -d "{\"telegram_id\":$TG3,\"idem_key\":\"smoke-trial-1\"}" "$FP_API/api/internal/vpn/trial" | grep -q '"status":"paid"'
curl -sf -H "X-Internal-Token: $TOKEN" "$MV_API/v1/internal/billing/status?telegram_id=$TG3" | grep -q '"status":"trialing"'
[[ "$(code trial "{\"telegram_id\":$TG3,\"idem_key\":\"smoke-trial-2\"}")" == 409 ]]

echo "==> CP refuses a second trial even if FocusPay forgot"
[[ "$(curl -s -o /dev/null -w '%{http_code}' "${HDR[@]}" -d "{\"external_id\":\"rogue-trial\",\"telegram_id\":$TG3,\"kind\":\"trial\",\"days\":1}" "$MV_API/v1/internal/billing/grant")" == 409 ]]

echo "==> CP lists subscriptions ending within a day (trials)"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ); TOMORROW=$(date -u -d '+2 days' +%Y-%m-%dT%H:%M:%SZ)
curl -sf -H "X-Internal-Token: $TOKEN" "$MV_API/v1/internal/billing/ending?from=$NOW&to=$TOMORROW" | grep -q "\"telegram_id\":$TG3"

echo "==> bot api module"
FOCUSPAY_API_BASE="$FP_API" FOCUSPAY_INTERNAL_TOKEN="$TOKEN" \
FOCUSVPN_API_BASE="$MV_API" FOCUSVPN_INTERNAL_TOKEN="$TOKEN" \
PYTHONPATH="$ROOT/bots/focusvpn-tg" python3 - <<'PY'
import asyncio
import os

import httpx

from bot import api


async def main():
    tid = 900077
    async with httpx.AsyncClient() as c:
        await c.post(os.environ["FOCUSPAY_API_BASE"] + "/__smoke/credit", json={"telegram_id": tid, "amount_rub": 990})
    st = await api.fp_status(tid)
    assert st["purchase_open"] and st["trial_available"], st
    assert st["plans"][1]["discount_pct"] == 23 and not st["subscription"]["active"], st
    res = await api.fp_purchase(tid, "month", "bot-smoke-1")
    assert res["status"] == "paid" and res["days"] == 30, res
    st = await api.mv_status(tid)
    assert st["has_live"], st
    st = await api.fp_status(tid)
    assert st["subscription"]["active"] and st["subscription"]["days_left"] == 30, st
    try:
        await api.fp_purchase(tid, "month", "bot-smoke-2")
    except api.APIError as e:
        assert e.detail.get("code") == "insufficient_funds", e.body
    else:
        raise AssertionError("expected insufficient_funds")
    assert await api.mv_devices(tid) == []

    # Trials of TG2/TG3 end in ~24 h, outside the 6 h "soon" window: no reminders yet.
    assert [r for r in await api.fp_expiring() if r["kind"] == "soon"] == []
    assert await api.fp_notified(tid, "soon", "2026-10-07T12:00:00+00:00") is True
    assert await api.fp_notified(tid, "soon", "2026-10-07T12:00:00+00:00") is False
    print("bot api OK")


asyncio.run(main())
PY

echo "PASS: E1 full FocusPay-stub + FocusVPN (plans, purchase, idempotency, exchange gate, trial, ending, bot api)"
