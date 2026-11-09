#!/usr/bin/env bash
# Fail closed before the long-lived staging runtime can create or update containers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.staging-runtime.yml"
ENV_FILE="${STAGING_RUNTIME_ENV_FILE:-$SCRIPT_DIR/../.env.staging-runtime}"
export STAGING_RUNTIME_ENV_FILE="$ENV_FILE"

fail() {
  printf 'staging runtime preflight failed: %s\n' "$*" >&2
  exit 1
}

[[ -f "$COMPOSE_FILE" ]] || fail "compose file is missing"
[[ -r "$ENV_FILE" ]] || fail "environment file is missing or unreadable"
[[ ! -L "$ENV_FILE" ]] || fail "environment file must not be a symlink"

permissions="$(stat -c '%a' "$ENV_FILE")"
(( 10#$permissions <= 600 )) || fail "environment file permissions must be 0600 or stricter"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

require_exact() {
  local name="$1" expected="$2"
  local actual="${!name:-}"
  [[ "$actual" == "$expected" ]] || fail "$name must equal $expected"
}

require_value() {
  local name="$1"
  local value="${!name:-}"
  local normalized
  normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  [[ -n "$value" ]] || fail "$name must be set"
  [[ "$normalized" != *change_me* && "$normalized" != *placeholder* && "$normalized" != *replace_* && "$normalized" != *example* ]] || fail "$name contains a placeholder"
}

require_exact ENVIRONMENT staging
require_exact STAGING_DISABLE_BACKGROUND_TASKS true
require_exact STAGING_BOOTSTRAP_PROFILE full-panel-pvp

verify_casino_bot_can_delete() {
  local token="$1" chat_id="$2" bot_id="$3"
  TELEGRAM_IDENTITY_TOKEN="$token" \
  TELEGRAM_GAME_CHAT_ID="$chat_id" \
  TELEGRAM_IDENTITY_ID="$bot_id" \
  python3 -c '
import json
import os
import sys
from urllib.request import Request, urlopen

token = os.environ["TELEGRAM_IDENTITY_TOKEN"]
chat_id = os.environ["TELEGRAM_GAME_CHAT_ID"]
bot_id = os.environ["TELEGRAM_IDENTITY_ID"]
request = Request(
    "https://api.telegram.org/bot" + token
    + "/getChatMember?chat_id=" + chat_id + "&user_id=" + bot_id
)
with urlopen(request, timeout=10) as response:
    payload = json.load(response)
result = payload.get("result", {})
status = str(result.get("status", ""))
can_delete = result.get("can_delete_messages")
if status in {"creator", "administrator"} and can_delete is None:
    can_delete = True
if not payload.get("ok") or status not in {"member", "administrator", "creator", "restricted"}:
    raise SystemExit("casino bot is not in GAME_CHAT_ID")
if status not in {"administrator", "creator"} or can_delete is not True:
    sys.stderr.write(
        "staging runtime preflight warning: casino bot status=%s can_delete_messages=%s "
        "(needs administrator + delete messages to purge player dice)\n"
        % (status, can_delete)
    )
' || fail "casino bot is missing from GAME_CHAT_ID"
}

verify_telegram_identity() {
  local label="$1" token="$2" expected_username="$3" expected_id="$4"

  TELEGRAM_IDENTITY_TOKEN="$token" \
  TELEGRAM_IDENTITY_USERNAME="$expected_username" \
  TELEGRAM_IDENTITY_ID="$expected_id" \
  python3 -c '
import json
import os
import sys
from urllib.request import Request, urlopen

try:
    request = Request(
        "https://api.telegram.org/bot" + os.environ["TELEGRAM_IDENTITY_TOKEN"] + "/getMe"
    )
    with urlopen(request, timeout=10) as response:
        payload = json.load(response)
    result = payload.get("result", {})
    actual_username = str(result.get("username", "")).lstrip("@").lower()
    actual_id = str(result.get("id", ""))
    expected_username = os.environ["TELEGRAM_IDENTITY_USERNAME"].lstrip("@").lower()
    expected_id = os.environ["TELEGRAM_IDENTITY_ID"]
    if not payload.get("ok") or actual_username != expected_username or actual_id != expected_id:
        raise ValueError
except Exception:
    sys.exit(1)
' || fail "$label Telegram identity does not match its staging allowlist"
}

for enabled_flag in STAGING_RUNTIME_ENABLE_BOT STAGING_RUNTIME_ENABLE_CASINO; do
  case "${!enabled_flag:-}" in
    0|1) ;;
    *) fail "$enabled_flag must equal 0 or 1" ;;
  esac
done

for key in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD STAGING_RUNTIME_POSTGRES_VOLUME DATABASE_DSN REDIS_URL SECRET_KEY INTERNAL_API_SECRET STAGING_INTERNAL_API_SECRET CASINO_EXCHANGER_ID TELEGRAM_BOT_TOKEN TELEGRAM_BOT_USERNAME STAGING_TELEGRAM_BOT_USERNAME STAGING_TELEGRAM_BOT_ID STAGING_TELEGRAM_CHAT_IDS STAGING_SYNTHETIC_ADMIN_USERNAME STAGING_SYNTHETIC_ADMIN_PASSWORD STAGING_SYNTHETIC_CLIENT_OPERATOR_PASSWORD STAGING_SYNTHETIC_FINANCE_OPERATOR_PASSWORD ADMIN_TELEGRAM_IDS FINANCE_OWNER_TELEGRAM_ID PUBLIC_SITE_URL MERCHANT_BASE_URL MERCHANT_API_KEY MERCHANT_SECRET_KEY FAKE_PAYFAST_API_KEY FAKE_PAYFAST_SECRET_KEY MERCHANT_CALLBACK_URL RECEIPT_PUBLIC_BASE_URL BOT_TOKEN BOT_USERNAME CASINO_STAGING_TELEGRAM_BOT_USERNAME CASINO_STAGING_TELEGRAM_BOT_ID CASINO_BOT_USERNAME GAME_CHAT_ID ALLOWED_CHAT_ID ADMIN_IDS FOCUSPAY_API_URL FOCUSPAY_INTERNAL_TOKEN WEBHOOK_URL CASINO_FAIRNESS_URL; do
  require_value "$key"
done

[[ ",$ADMIN_TELEGRAM_IDS," == *",940001,"* ]] || fail "ADMIN_TELEGRAM_IDS must include synthetic full-panel admin telegram_user_id 940001"
[[ "$FINANCE_OWNER_TELEGRAM_ID" == "940001" ]] || fail "FINANCE_OWNER_TELEGRAM_ID must equal synthetic full-panel admin telegram_user_id 940001"

[[ "$INTERNAL_API_SECRET" == "$STAGING_INTERNAL_API_SECRET" ]] || fail "internal API secret confirmation differs"
[[ "$FOCUSPAY_INTERNAL_TOKEN" == "$STAGING_INTERNAL_API_SECRET" ]] || fail "casino internal API secret confirmation differs"
(( ${#SECRET_KEY} >= 32 )) || fail "SECRET_KEY must have at least 32 characters"
[[ "$STAGING_RUNTIME_POSTGRES_VOLUME" == focuspay_staging_runtime_* ]] || fail "STAGING_RUNTIME_POSTGRES_VOLUME must use the staging namespace"
[[ "$DATABASE_DSN" == *"@postgres:"* ]] || fail "DATABASE_DSN must target the Compose postgres service"
[[ "$REDIS_URL" == redis://redis:* || "$REDIS_URL" == rediss://redis:* ]] || fail "REDIS_URL must target the Compose redis service"
[[ "$PUBLIC_SITE_URL" == http://gateway:8080* ]] || fail "PUBLIC_SITE_URL must target gateway:8080"
[[ "$RECEIPT_PUBLIC_BASE_URL" == http://gateway:8080* ]] || fail "RECEIPT_PUBLIC_BASE_URL must target gateway:8080"
[[ "$MERCHANT_BASE_URL" == http://fake-payfast:8081* ]] || fail "MERCHANT_BASE_URL must target fake-payfast:8081"
[[ "$MERCHANT_CALLBACK_URL" == http://backend:8000/* ]] || fail "MERCHANT_CALLBACK_URL must target backend:8000"
[[ "$FOCUSPAY_API_URL" == http://backend:8000* ]] || fail "FOCUSPAY_API_URL must target backend:8000"
[[ "$WEBHOOK_URL" == http://casino-bot:8001/* ]] || fail "WEBHOOK_URL must target casino-bot:8001"
[[ "$CASINO_FAIRNESS_URL" == "http://127.0.0.1:18081/casino/fairness" ]] || fail "CASINO_FAIRNESS_URL must be the staging tunnel fairness page"

if [[ "$STAGING_RUNTIME_ENABLE_BOT" == 1 ]]; then
  verify_telegram_identity \
    "exchange bot" \
    "$TELEGRAM_BOT_TOKEN" \
    "$STAGING_TELEGRAM_BOT_USERNAME" \
    "$STAGING_TELEGRAM_BOT_ID"
fi
[[ "$CASINO_BOT_USERNAME" == "$CASINO_STAGING_TELEGRAM_BOT_USERNAME" ]] || fail "CASINO_BOT_USERNAME must match the staging casino bot username"
[[ "$CASINO_BOT_USERNAME" != "$TELEGRAM_BOT_USERNAME" ]] || fail "casino login bot must not be the exchange bot"

if [[ "$STAGING_RUNTIME_ENABLE_CASINO" == 1 ]]; then
  verify_telegram_identity \
    "casino bot" \
    "$BOT_TOKEN" \
    "$CASINO_STAGING_TELEGRAM_BOT_USERNAME" \
    "$CASINO_STAGING_TELEGRAM_BOT_ID"
  [[ -n "${GAME_CHAT_ID:-}" && "$GAME_CHAT_ID" != "0" ]] || fail "GAME_CHAT_ID must be the staging game group"
  verify_casino_bot_can_delete \
    "$BOT_TOKEN" \
    "$GAME_CHAT_ID" \
    "$CASINO_STAGING_TELEGRAM_BOT_ID"
fi

if ! command -v iptables >/dev/null 2>&1; then
  fail "iptables is required to verify production egress blocks"
fi
has_host_egress_block=false
if iptables -C OUTPUT -d 153.80.249.77 -j DROP 2>/dev/null \
  || iptables -C OUTPUT -d 153.80.249.77 -j REJECT 2>/dev/null; then
  has_host_egress_block=true
elif command -v ufw >/dev/null 2>&1 \
  && ufw status numbered 2>/dev/null | grep -Eq '153\.80\.249\.77[[:space:]]+DENY[[:space:]]+OUT'; then
  # UFW installs its matching rule in an OUTPUT subchain reached from OUTPUT.
  has_host_egress_block=true
fi
"$has_host_egress_block" || fail "host OUTPUT lacks a verified DROP/REJECT rule for production IP 153.80.249.77"

if ! iptables -C DOCKER-USER -d 153.80.249.77 -j DROP 2>/dev/null \
  && ! iptables -C DOCKER-USER -d 153.80.249.77 -j REJECT 2>/dev/null; then
  fail "DOCKER-USER lacks a DROP/REJECT rule for production IP 153.80.249.77"
fi

for value in "$DATABASE_DSN" "$REDIS_URL" "$PUBLIC_SITE_URL" "$MERCHANT_BASE_URL" "$MERCHANT_CALLBACK_URL" "$RECEIPT_PUBLIC_BASE_URL" "$FOCUSPAY_API_URL" "$WEBHOOK_URL"; do
  normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  [[ "$normalized" != *focuspay.org* && "$normalized" != *153.80.249.77* ]] || fail "production target is forbidden"
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
rendered="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --no-interpolate)"
[[ "$rendered" == *'name: focuspay-staging-runtime'* ]] || fail "unexpected Compose namespace"
for forbidden in '"5432:' '"6379:' '"8000:' '"8081:'; do
  [[ "$rendered" != *"$forbidden"* ]] || fail "internal service port is published"
done
[[ "$rendered" == *'127.0.0.1:'* ]] || fail "gateway must bind to loopback"

printf 'staging runtime preflight passed\n'
