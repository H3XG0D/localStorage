#!/usr/bin/env bash
# Smoke against running sandbox services (make sandbox-up && make sandbox-run).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=sandbox-lib.sh
source "$ROOT/scripts/sandbox-lib.sh"
load_sandbox_env

MV_URL="http://127.0.0.1${FOCUSVPN_HTTP_ADDR}"
FP_URL="http://${FOCUSPAY_WALLET_ADDR}"
TOKEN="$SANDBOX_INTERNAL_TOKEN"
TG=900042
HDR=(-H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json")

echo "==> health"
curl -sf "$MV_URL/v1/health" >/dev/null
curl -sf "$FP_URL/health" >/dev/null

echo "==> FocusPay status (seeded 300₽)"
STATUS=$(curl -sf "${HDR[@]}" "$FP_URL/api/internal/vpn/status/$TG")
echo "$STATUS" | grep -q available_rub
AVAIL=$(printf '%s' "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('available_rub',0))")
if python3 -c "import sys; sys.exit(0 if float('$AVAIL')<300 else 1)"; then
  echo "==> re-seed cashback on sandbox DB"
  PGPASSWORD=focuspay_sandbox psql -h 127.0.0.1 -p 15433 -U focuspay_sandbox -d focuspay_sandbox -v ON_ERROR_STOP=1 <<SQL
INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
VALUES ($TG, 'accrual', 300.00, 'sandbox-reseed-' || extract(epoch from now())::bigint, 'SANDBOX reseed')
ON CONFLICT DO NOTHING;
SQL
fi

IDEM="sandbox-$(date +%s)"
echo "==> purchase week via FocusPay saga ($IDEM)"
curl -sf "${HDR[@]}" -d "{\"telegram_id\":$TG,\"plan_code\":\"week\",\"idem_key\":\"$IDEM\"}" \
  "$FP_URL/api/internal/vpn/purchase" | grep -q '"status":"paid"'
curl -sf "${HDR[@]}" -d "{\"telegram_id\":$TG,\"plan_code\":\"week\",\"idem_key\":\"$IDEM\"}" \
  "$FP_URL/api/internal/vpn/purchase" | grep -q '"replay":true'
curl -sf -H "X-Internal-Token: $TOKEN" \
  "$MV_URL/v1/internal/billing/status?telegram_id=$TG" | grep -q '"has_live":true'

echo "PASS: sandbox FocusPay wallet + FocusVPN billing (isolated from prod)"
