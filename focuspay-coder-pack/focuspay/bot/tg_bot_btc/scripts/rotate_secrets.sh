#!/usr/bin/env bash
# Rotate bot-owned secrets. Explicit invocation only; supports --dry-run.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${FOCUSPAY_ENV_FILE:-$BOT_DIR/.env}"
TIMESTAMP_FILE="${FOCUSPAY_ROTATION_TIMESTAMP_FILE:-$BOT_DIR/.secrets_rotated_at}"
DRY_RUN=false
RESTART=false

usage() {
    printf 'Usage: %s [--dry-run] [--restart-services]\n' "$0"
}
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --restart-services) RESTART=true ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done

[[ -f "$ENV_FILE" ]] || { printf 'Environment file not found: %s\n' "$ENV_FILE" >&2; exit 1; }
command -v openssl >/dev/null || { printf 'openssl is not installed\n' >&2; exit 1; }

secret_names=(CALLBACK_SECRET RECEIPT_SECRET)
for name in "${secret_names[@]}"; do
    count="$(grep -c -E "^[[:space:]]*${name}=" "$ENV_FILE" || true)"
    [[ "$count" == 1 ]] || { printf '%s must occur exactly once in %s\n' "$name" "$ENV_FILE" >&2; exit 1; }
done

if $DRY_RUN; then
    printf 'Validation passed; %d secrets would be rotated in %s\n' "${#secret_names[@]}" "$ENV_FILE"
    exit 0
fi

backup="${ENV_FILE}.backup-$(date -u +%Y%m%dT%H%M%SZ)"
tmp="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
trap 'rm -f -- "$tmp"' EXIT HUP INT TERM
cp --preserve=mode,ownership,timestamps -- "$ENV_FILE" "$backup"

new_callback="$(openssl rand -hex 32)"
new_receipt="$(openssl rand -hex 32)"
awk -v callback="$new_callback" -v receipt="$new_receipt" '
    /^CALLBACK_SECRET=/ { print "CALLBACK_SECRET=" callback; next }
    /^RECEIPT_SECRET=/ { print "RECEIPT_SECRET=" receipt; next }
    { print }
' "$ENV_FILE" > "$tmp"
chmod --reference="$ENV_FILE" "$tmp"
chown --reference="$ENV_FILE" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$ENV_FILE"
printf '%s\n' "$(date +%s)" > "$TIMESTAMP_FILE"
chmod 600 "$TIMESTAMP_FILE"

printf 'Bot-owned secrets rotated; encrypted/offline handling of old backup is required: %s\n' "$backup"
printf 'WEBHOOK_SECRET is shared with the API and was intentionally not changed. Rotate shared secrets with a coordinated procedure.\n'

if $RESTART; then
    command -v systemctl >/dev/null || { printf 'systemctl is not available\n' >&2; exit 1; }
    systemctl try-restart focuspay-exchange-api.service
    systemctl try-restart tg-bot.service tg-bot-webhook.service
    printf 'Configured services were asked to restart\n'
else
    printf 'Services were not restarted; use --restart-services only in an approved maintenance window.\n'
fi
