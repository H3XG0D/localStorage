#!/usr/bin/env bash
# Push both working trees to isolated staging and rebuild the runtime.
# Never touches production. Never uses --delete-excluded, down -v, or volume prune.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOCUSPAY_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CASINO_ROOT="$(cd "$FOCUSPAY_ROOT/../focuspay-casino" && pwd)"

HOST="${FOCUSPAY_SSH_HOST:-178.63.247.233}"
USER="${FOCUSPAY_SSH_USER:-}"

if [[ "$HOST" == "178.63.247.233" && -z "$USER" ]]; then
  USER="focuspay-staging"
fi

if [[ ! -d "$CASINO_ROOT" ]]; then
  printf 'staging-sync: sibling focuspay-casino is missing at %s\n' "$CASINO_ROOT" >&2
  exit 1
fi

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15)
if [[ -n "${FOCUSPAY_SSH_IDENTITY:-}" ]]; then
  SSH_OPTS+=(-i "$FOCUSPAY_SSH_IDENTITY")
elif [[ -n "$USER" && -f "${HOME}/.ssh/focuspay-staging-178.63.247.233" ]]; then
  SSH_OPTS+=(-i "${HOME}/.ssh/focuspay-staging-178.63.247.233")
fi

if [[ -n "${FOCUSPAY_SSH_PASSWORD:-}" ]] && command -v sshpass >/dev/null 2>&1; then
  export SSHPASS="${FOCUSPAY_SSH_PASSWORD}"
  SSH_PREFIX=(sshpass -e ssh "${SSH_OPTS[@]}")
else
  SSH_PREFIX=(ssh "${SSH_OPTS[@]}")
fi

if [[ -n "$USER" ]]; then
  TARGET="${USER}@${HOST}"
else
  TARGET="${HOST}"
fi

RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='node_modules/'
  --exclude='dist/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.venv/'
  --exclude='venv/'
  --exclude='.env'
  --exclude='.env.*'
  --exclude='*.dump'
  --exclude='*.dump.gz'
)

remote() {
  "${SSH_PREFIX[@]}" "$TARGET" "$@"
}

printf 'staging-sync: rsync %s -> %s:/opt/focuspay/\n' "$FOCUSPAY_ROOT" "$TARGET"
remote 'mkdir -p /opt/focuspay /opt/focuspay-casino'
# Dest-only leftovers that --delete cannot remove: excluded `.env.*` files
# keep empty-looking trees alive, and root-owned dirs deny rmdir.
remote 'rm -rf /opt/focuspay/casino-client; sudo rm -rf /opt/focuspay-casino/.staging-e2e'
rsync -az --delete --force "${RSYNC_EXCLUDES[@]}" -e "${SSH_PREFIX[*]}" \
  "$FOCUSPAY_ROOT/" "$TARGET:/opt/focuspay/"
printf 'staging-sync: rsync %s -> %s:/opt/focuspay-casino/\n' "$CASINO_ROOT" "$TARGET"
rsync -az --delete --force "${RSYNC_EXCLUDES[@]}" -e "${SSH_PREFIX[*]}" \
  "$CASINO_ROOT/" "$TARGET:/opt/focuspay-casino/"

printf 'staging-sync: staging-runtime-update.sh --apply\n'
remote 'cd /opt/focuspay/focussite && sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env ./scripts/staging-runtime-update.sh --apply'

printf 'staging-sync: staging-runtime-health.sh\n'
remote 'cd /opt/focuspay/focussite && sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env ./scripts/staging-runtime-health.sh'

printf 'staging-sync: completed\n'
