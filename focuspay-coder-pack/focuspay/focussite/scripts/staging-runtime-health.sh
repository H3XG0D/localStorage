#!/usr/bin/env bash
# Verify the only host entrypoint and dependencies after Compose reports healthy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.staging-runtime.yml"
ENV_FILE="${STAGING_RUNTIME_ENV_FILE:-$SCRIPT_DIR/../.env.staging-runtime}"
export STAGING_RUNTIME_ENV_FILE="$ENV_FILE"
PORT="${STAGING_RUNTIME_HTTP_PORT:-18080}"

fail() {
  printf 'staging runtime health check failed: %s\n' "$*" >&2
  exit 1
}

[[ -r "$ENV_FILE" ]] || fail "environment file is missing or unreadable"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
PORT="${STAGING_RUNTIME_HTTP_PORT:-$PORT}"

curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:${PORT}/healthz" >/dev/null
curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:${PORT}/api/health" >/dev/null

for service in postgres redis fake-payfast backend gateway; do
  status="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --format json "$service" | python3 -c 'import json, sys; rows = json.load(sys.stdin); row = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else {}; print(row.get("Health", row.get("State", "")))')"
  [[ "$status" == healthy ]] || fail "$service is not healthy (status: ${status:-missing})"
done

for service_flag in "bot:STAGING_RUNTIME_ENABLE_BOT" "casino-bot:STAGING_RUNTIME_ENABLE_CASINO"; do
  service="${service_flag%%:*}"
  enabled_flag="${service_flag##*:}"
  if [[ "${!enabled_flag}" == 1 ]]; then
    status="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --format json "$service" | python3 -c 'import json, sys; rows = json.load(sys.stdin); row = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else {}; print(row.get("State", ""))')"
    [[ "$status" == running ]] || fail "$service is not running (status: ${status:-missing})"
  fi
done

printf 'staging runtime health check passed\n'
