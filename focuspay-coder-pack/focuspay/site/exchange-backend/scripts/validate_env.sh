#!/usr/bin/env bash
# Validate the exchange API environment before a production deployment. Read-only.

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

require_secret() {
    local name="$1" current
    current="$(value "$name")"
    if [[ -z "$current" ]]; then
        fail "$name is missing or empty"
    elif [[ "${current^^}" == *CHANGE_ME* || "${current^^}" == *CHANGEME* || ${#current} -lt 32 ]]; then
        fail "$name is a placeholder or shorter than 32 characters"
    else
        ok "$name is configured"
    fi
}

require_secret SECRET_KEY
require_secret CALLBACK_SECRET
require_secret RECEIPT_SECRET
require_secret WEBHOOK_SECRET
require_secret INTERNAL_API_SECRET

DATABASE_DSN="$(value DATABASE_DSN)"
if [[ -z "$DATABASE_DSN" ]]; then
    fail "DATABASE_DSN is missing or empty"
elif [[ "${DATABASE_DSN^^}" == *PASSWORD* || "$DATABASE_DSN" == *':777@'* || "$DATABASE_DSN" == *'password=password'* ]]; then
    fail "DATABASE_DSN contains a placeholder or weak password"
else
    ok "DATABASE_DSN is configured"
fi

case "${DEBUG_VALUE:-$(value DEBUG)}" in
    1|true|True|TRUE|yes|YES) fail "DEBUG must be disabled in production" ;;
esac
case "$(value EXPOSE_OPENAPI_DOCS)" in
    1|true|True|TRUE|yes|YES) fail "EXPOSE_OPENAPI_DOCS must be disabled in production" ;;
esac
case "$(value EXPOSE_LOCAL_CORS)" in
    1|true|True|TRUE|yes|YES) fail "EXPOSE_LOCAL_CORS must be disabled in production" ;;
esac

trusted_proxies="$(value SECURITY_TRUSTED_PROXIES)"
if [[ -z "$trusted_proxies" ]]; then
    fail "SECURITY_TRUSTED_PROXIES is missing or empty"
elif [[ ",$trusted_proxies," == *,0.0.0.0/0,* || ",$trusted_proxies," == *,::/0,* ]]; then
    fail "SECURITY_TRUSTED_PROXIES must not trust the whole internet"
else
    ok "SECURITY_TRUSTED_PROXIES is configured"
fi

if ((errors > 0)); then
    printf 'Validation failed with %d error(s)\n' "$errors" >&2
    exit 1
fi
printf 'Environment validation passed\n'
