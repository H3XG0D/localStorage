#!/usr/bin/env bash
# Controlled staging runtime rollout. This script never removes volumes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.staging-runtime.yml"
ENV_FILE="${STAGING_RUNTIME_ENV_FILE:-$SCRIPT_DIR/../.env.staging-runtime}"
export STAGING_RUNTIME_ENV_FILE="$ENV_FILE"

if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  printf 'Usage: %s --apply\n' "${0##*/}" >&2
  printf 'This creates or updates the isolated staging runtime after preflight.\n' >&2
  exit 64
fi

"$SCRIPT_DIR/staging-runtime-preflight.sh"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

compose_profiles=()
if [[ "$STAGING_RUNTIME_ENABLE_BOT" == 1 ]]; then
  compose_profiles+=(--profile bot)
fi
if [[ "$STAGING_RUNTIME_ENABLE_CASINO" == 1 ]]; then
  compose_profiles+=(--profile casino)
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "${compose_profiles[@]}" up -d --build --wait --remove-orphans
"$SCRIPT_DIR/staging-runtime-health.sh"
printf 'staging runtime update completed\n'
