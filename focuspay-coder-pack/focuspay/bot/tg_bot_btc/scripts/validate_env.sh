#!/usr/bin/env bash
# Validate the bot environment before a production deployment. Read-only.

set -euo pipefail
ENV_FILE="${1:-.env}"
errors=0

fail() { printf 'ERROR: %s\n' "$*" >&2; errors=$((errors + 1)); }
ok() { printf 'OK: %s\n' "$*"; }

[[ -f "$ENV_FILE" ]] || { printf 'ERROR: environment file not found: %s\n' "$ENV_FILE" >&2; exit 1; }

value() {
    local name="$1" line
    line="$(grep -m1 -E "^[[:space:]]*${name}=" "$ENV_FILE" || true)"
    line="${line#*=}"
    if [[ "$line" == \"*\" && "$line" == *\" ]]; then
        line="${line:1:${#line}-2}"
    elif [[ "$line" == \'*\' && "$line" == *\' ]]; then
        line="${line:1:${#line}-2}"
    fi
    printf '%s' "$line"
}

require_non_placeholder() {
    local name="$1" minimum="${2:-1}" current
    current="$(value "$name")"
    if [[ -z "$current" ]]; then
        fail "$name is missing or empty"
    elif [[ "${current^^}" == *CHANGE_ME* || "${current^^}" == *CHANGEME* || "${current^^}" == *PASSWORD* || ${#current} -lt $minimum ]]; then
        fail "$name is a placeholder or shorter than $minimum characters"
    else
        ok "$name is configured"
    fi
}

require_non_placeholder TELEGRAM_BOT_TOKEN 20
require_non_placeholder DATABASE_DSN 20
require_non_placeholder CALLBACK_SECRET 32
require_non_placeholder RECEIPT_SECRET 32
require_non_placeholder WEBHOOK_SECRET 32

allowed_ips="$(value WEBHOOK_ALLOWED_IPS)"
if [[ -z "$allowed_ips" ]]; then
    fail "WEBHOOK_ALLOWED_IPS is missing or empty"
elif [[ "$allowed_ips" == "127.0.0.1" || "$allowed_ips" == "::1" || "$allowed_ips" == "127.0.0.1,::1" ]]; then
    fail "WEBHOOK_ALLOWED_IPS contains only loopback addresses"
else
    ok "WEBHOOK_ALLOWED_IPS is configured"
fi

trusted_proxies="$(value WEBHOOK_TRUSTED_PROXIES)"
if [[ -z "$trusted_proxies" ]]; then
    fail "WEBHOOK_TRUSTED_PROXIES is missing or empty"
elif [[ ",$trusted_proxies," == *,0.0.0.0/0,* || ",$trusted_proxies," == *,::/0,* ]]; then
    fail "WEBHOOK_TRUSTED_PROXIES must not trust the whole internet"
else
    ok "WEBHOOK_TRUSTED_PROXIES is configured"
fi

if [[ "$(value OFFSITE_BACKUP_ENABLED)" == "true" ]]; then
    for name in OFFSITE_BACKUP_HOST OFFSITE_BACKUP_USER OFFSITE_BACKUP_PATH; do
        [[ -n "$(value "$name")" ]] || fail "$name is required when offsite backup is enabled"
    done
    [[ "$(value OFFSITE_BACKUP_PATH)" == /* ]] || fail "OFFSITE_BACKUP_PATH must be absolute"
    key="$(value OFFSITE_BACKUP_SSH_KEY)"
    [[ -z "$key" || "$key" == /* ]] || fail "OFFSITE_BACKUP_SSH_KEY must be absolute when set"
fi

if ((errors > 0)); then
    printf 'Validation failed with %d error(s)\n' "$errors" >&2
    exit 1
fi
printf 'Environment validation passed\n'
