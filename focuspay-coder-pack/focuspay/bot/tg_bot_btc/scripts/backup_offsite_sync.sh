#!/usr/bin/env bash
# Copy completed database backups to an offsite host. This script is stateful.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${FOCUSPAY_ENV_FILE:-$BOT_DIR/.env}"
BACKUP_DIR="${FOCUSPAY_BACKUP_DIR:-/var/backups/focuspay}"

[[ -f "$ENV_FILE" ]] || { printf 'Environment file not found: %s\n' "$ENV_FILE" >&2; exit 1; }

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

OFFSITE_ENABLED="$(read_env_value OFFSITE_BACKUP_ENABLED)"
[[ "${OFFSITE_ENABLED,,}" == "true" ]] || { printf 'Offsite backup is disabled\n'; exit 0; }

OFFSITE_HOST="$(read_env_value OFFSITE_BACKUP_HOST)"
OFFSITE_USER="$(read_env_value OFFSITE_BACKUP_USER)"
OFFSITE_PATH="$(read_env_value OFFSITE_BACKUP_PATH)"
OFFSITE_SSH_KEY="$(read_env_value OFFSITE_BACKUP_SSH_KEY)"

[[ "$OFFSITE_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || { printf 'Invalid OFFSITE_BACKUP_HOST\n' >&2; exit 1; }
[[ "$OFFSITE_USER" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || { printf 'Invalid OFFSITE_BACKUP_USER\n' >&2; exit 1; }
[[ "$OFFSITE_PATH" == /* && "$OFFSITE_PATH" != *$'\n'* ]] || { printf 'OFFSITE_BACKUP_PATH must be an absolute remote path\n' >&2; exit 1; }
[[ -d "$BACKUP_DIR" ]] || { printf 'Backup directory not found: %s\n' "$BACKUP_DIR" >&2; exit 1; }
command -v rsync >/dev/null || { printf 'rsync is not installed\n' >&2; exit 1; }

shopt -s nullglob
backups=("$BACKUP_DIR"/exchange_bot_backup_*.dump.gz)
((${#backups[@]} > 0)) || { printf 'No completed backups to synchronize\n'; exit 0; }

ssh_command=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes)
if [[ -n "$OFFSITE_SSH_KEY" ]]; then
    [[ -f "$OFFSITE_SSH_KEY" ]] || { printf 'SSH key not found: %s\n' "$OFFSITE_SSH_KEY" >&2; exit 1; }
    ssh_command+=(-i "$OFFSITE_SSH_KEY")
fi
printf -v rsync_shell '%q ' "${ssh_command[@]}"
rsync_shell="${rsync_shell% }"

printf 'Synchronizing %d backup(s) to %s@%s\n' "${#backups[@]}" "$OFFSITE_USER" "$OFFSITE_HOST"
rsync --archive --compress --protect-args --partial \
    --rsh="$rsync_shell" \
    --include='exchange_bot_backup_*.dump.gz' --exclude='*' \
    "$BACKUP_DIR/" "$OFFSITE_USER@$OFFSITE_HOST:$OFFSITE_PATH/"
printf 'Offsite backup synchronization completed\n'
