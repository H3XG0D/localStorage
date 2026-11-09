#!/usr/bin/env bash
# Create a local PostgreSQL backup. This script is stateful; do not run in CI.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${FOCUSPAY_ENV_FILE:-$BOT_DIR/.env}"
BACKUP_DIR="${FOCUSPAY_BACKUP_DIR:-/var/backups/focuspay}"
KEEP_DAYS="${FOCUSPAY_BACKUP_KEEP_DAYS:-7}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep-days)
            [[ $# -ge 2 ]] || { printf 'Missing value for --keep-days\n' >&2; exit 2; }
            KEEP_DAYS="$2"
            shift 2
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

[[ "$KEEP_DAYS" =~ ^[0-9]+$ ]] || { printf 'Retention must be a non-negative integer\n' >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { printf 'Environment file not found: %s\n' "$ENV_FILE" >&2; exit 1; }
command -v pg_dump >/dev/null || { printf 'pg_dump is not installed\n' >&2; exit 1; }
command -v gzip >/dev/null || { printf 'gzip is not installed\n' >&2; exit 1; }

read_env_value() {
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

DATABASE_DSN="$(read_env_value DATABASE_DSN)"
[[ -n "$DATABASE_DSN" ]] || { printf 'DATABASE_DSN is missing or empty in %s\n' "$ENV_FILE" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="$BACKUP_DIR/.exchange_bot_backup_${timestamp}.dump.partial"
final="$BACKUP_DIR/exchange_bot_backup_${timestamp}.dump.gz"
cleanup() { rm -f -- "$partial" "${partial}.gz"; }
trap cleanup EXIT HUP INT TERM

printf 'Creating PostgreSQL backup in %s\n' "$BACKUP_DIR"
pg_dump --dbname="$DATABASE_DSN" --format=custom --file="$partial"
gzip -9 "$partial"
mv -- "${partial}.gz" "$final"
chmod 600 "$final"

# Only remove files produced by this script, and only after a successful dump.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'exchange_bot_backup_*.dump.gz' \
    -mtime "+$KEEP_DAYS" -delete

printf 'Backup created: %s\n' "$final"
