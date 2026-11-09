#!/usr/bin/env bash
# Автонастройка Cloudflare для focuspay.org через API.
# Требует: CLOUDFLARE_API_TOKEN (и опционально CLOUDFLARE_ZONE_ID, ORIGIN_IP).
#
# Использование:
#   export CLOUDFLARE_API_TOKEN='...'
#   ./deploy/cloudflare-apply.sh
#
# Или положить токен в deploy/.cloudflare.env (chmod 600, не коммитить):
#   CLOUDFLARE_API_TOKEN=...
#   ORIGIN_IP=178.236.252.170

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${CLOUDFLARE_ENV_FILE:-$SCRIPT_DIR/.cloudflare.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

: "${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN or create deploy/.cloudflare.env}"
ZONE_NAME="${CLOUDFLARE_ZONE_NAME:-focuspay.org}"
ORIGIN_IP="${ORIGIN_IP:-178.236.252.170}"
API="https://api.cloudflare.com/client/v4"

cf_api() {
  local method="$1" path="$2"
  shift 2
  curl -sf -X "$method" "${API}${path}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    "$@"
}

echo "==> Проверка токена"
cf_api GET /user/tokens/verify | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('success'), d; print('OK:', d['result']['status'])"

echo "==> Zone ID для ${ZONE_NAME}"
if [[ -n "${CLOUDFLARE_ZONE_ID:-}" ]]; then
  ZONE_ID="$CLOUDFLARE_ZONE_ID"
else
  ZONE_ID=$(cf_api GET "/zones?name=${ZONE_NAME}&status=active" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('result') or []
if not r:
    raise SystemExit('Zone not found or not active. Add domain to Cloudflare and update NS at Njalla.')
print(r[0]['id'])
")
fi
echo "    zone_id=${ZONE_ID}"

echo "==> SSL: Full (strict)"
cf_api PATCH "/zones/${ZONE_ID}/settings/ssl" --data '{"value":"strict"}' >/dev/null

echo "==> Always Use HTTPS"
cf_api PATCH "/zones/${ZONE_ID}/settings/always_use_https" --data '{"value":"on"}' >/dev/null

echo "==> DNS: A-записи с прокси (оранжевое облако)"
for host in "focuspay.org" "www.focuspay.org"; do
  records=$(cf_api GET "/zones/${ZONE_ID}/dns_records?type=A&name=${host}")
  rid=$(echo "$records" | python3 -c "import sys,json; r=json.load(sys.stdin).get('result') or []; print(r[0]['id'] if r else '')")
  if [[ -n "$rid" ]]; then
    cf_api PATCH "/zones/${ZONE_ID}/dns_records/${rid}" \
      --data "{\"content\":\"${ORIGIN_IP}\",\"proxied\":true,\"ttl\":1}" >/dev/null
    echo "    updated ${host} (proxied)"
  else
    cf_api POST "/zones/${ZONE_ID}/dns_records" \
      --data "{\"type\":\"A\",\"name\":\"${host}\",\"content\":\"${ORIGIN_IP}\",\"proxied\":true,\"ttl\":1}" >/dev/null
    echo "    created ${host} (proxied)"
  fi
done

echo "==> WAF: Skip managed rules для /callback"
# rulesets phase http_request_firewall_custom
ENTRYPOINT=$(cf_api GET "/zones/${ZONE_ID}/rulesets/phases/http_request_firewall_custom/entrypoint" 2>/dev/null || true)
RULESET_ID=$(echo "$ENTRYPOINT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('result',{}).get('id',''))
except Exception:
    print('')
" 2>/dev/null || true)

if [[ -z "$RULESET_ID" ]]; then
  RULESET_ID=$(cf_api POST "/zones/${ZONE_ID}/rulesets" \
    --data '{
      "name": "FocusPay custom",
      "kind": "zone",
      "phase": "http_request_firewall_custom",
      "rules": [{
        "description": "Skip WAF for merchant webhook",
        "expression": "(http.request.uri.path eq \"/callback\")",
        "action": "skip",
        "action_parameters": {
          "ruleset": "current",
          "phases": ["http_request_firewall_managed", "http_ratelimit"]
        },
        "enabled": true
      }]
    }' | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['id'])")
  echo "    created ruleset ${RULESET_ID}"
else
  echo "    ruleset exists ${RULESET_ID} (update manually if needed)"
fi

echo "==> Rate limit: /callback 30 req/min (Block, не Challenge)"
# http_ratelimit phase - may need paid plan; try anyway
RL=$(cf_api POST "/zones/${ZONE_ID}/rulesets" \
  --data '{
    "name": "FocusPay callback rate limit",
    "kind": "zone",
    "phase": "http_ratelimit",
    "rules": [{
      "description": "Webhook rate limit",
      "expression": "(http.request.uri.path eq \"/callback\")",
      "action": "block",
      "ratelimit": {
        "characteristics": ["ip.src"],
        "period": 60,
        "requests_per_period": 30,
        "mitigation_timeout": 60
      },
      "enabled": true
    }]
  }' 2>/dev/null || echo '{"success":false}')
if echo "$RL" | python3 -c "import sys,json; assert json.load(sys.stdin).get('success')" 2>/dev/null; then
  echo "    rate limit rule created"
else
  echo "    WARN: rate limit via rulesets API may need Pro plan — set manually in dashboard:"
  echo "    Security → WAF → Rate limiting → /callback → Block 30/min"
fi

echo "==> Проверка (подождите 1–2 мин после смены NS)"
sleep 2
if curl -sfI "https://${ZONE_NAME}/api/health" 2>/dev/null | grep -qi cf-ray; then
  echo "✅ Cloudflare proxy активен (cf-ray найден)"
else
  echo "⚠️  cf-ray пока нет — если NS ещё на Njalla, смените nameservers:"
  cf_api GET "/zones/${ZONE_ID}" | python3 -c "
import sys, json
z = json.load(sys.stdin)['result']
for ns in z.get('name_servers', []):
    print('   ', ns)
"
  echo "   В Njalla: Domain → Nameservers → Custom → вставить NS выше"
fi

echo "✅ cloudflare-apply.sh завершён"
