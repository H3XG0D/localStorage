#!/usr/bin/env bash
# Manage a single isolated, synthetic PayFast E2E Compose project.
set -euo pipefail

COMMAND="${1:-}"
RUN_ID="${STAGING_E2E_PAYFAST_RUN_ID:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/focussite/docker-compose.payfast-e2e.yml"
STATE_DIR="${STAGING_E2E_PAYFAST_STATE_DIR:-${TMPDIR:-/tmp}/focuspay-payfast-e2e}"

fail() {
  printf '%s\n' "$1" >&2
  exit "${2:-64}"
}

[[ "$COMMAND" == "prepare" || "$COMMAND" == "run" || "$COMMAND" == "teardown" ]] \
  || fail "Usage: $0 prepare|run|teardown" 64
[[ "${STAGING_E2E_PAYFAST:-}" == "1" ]] || fail "STAGING_E2E_PAYFAST=1 is required" 64
[[ "$RUN_ID" =~ ^[a-z0-9]{12,32}$ ]] \
  || fail "STAGING_E2E_PAYFAST_RUN_ID must be 12-32 lowercase alphanumeric characters" 64
command -v docker >/dev/null 2>&1 || fail "docker is required for PayFast E2E lifecycle" 69

project="focuspay-payfast-e2e-${RUN_ID}"
state_file="$STATE_DIR/${RUN_ID}.env"
volume="${project}-postgres"

compose() {
  docker compose --project-name "$project" --env-file "$state_file" -f "$COMPOSE_FILE" "$@"
}

case "$COMMAND" in
  prepare)
    [[ ! -e "$state_file" ]] || fail "Refusing prepare: E2E state already exists for this run id" 65
    umask 077
    mkdir -p "$STATE_DIR"
    password="$(openssl rand -hex 32)"
    cat > "$state_file" <<EOF
STAGING_E2E_PAYFAST=1
STAGING_E2E_PAYFAST_INTERNAL=1
STAGING_E2E_PAYFAST_RUN_ID=${RUN_ID}
STAGING_E2E_PAYFAST_DB=e2e_payfast_${RUN_ID}
STAGING_E2E_PAYFAST_VOLUME=${volume}
POSTGRES_USER=e2e_payfast
POSTGRES_PASSWORD=${password}
EOF
    docker volume inspect "$volume" >/dev/null 2>&1 \
      && fail "Refusing prepare: disposable PayFast E2E volume already exists" 65
    compose config --quiet
    printf 'Prepared isolated PayFast E2E project %s. Run it explicitly, then tear it down explicitly.\n' "$project"
    ;;
  run)
    [[ -f "$state_file" ]] || fail "Run prepare before run" 65
    compose config --quiet
    compose up --build --abort-on-container-exit --exit-code-from payfast-e2e payfast-e2e
    ;;
  teardown)
    [[ -f "$state_file" ]] || fail "Refusing teardown: no owned E2E state exists for this run id" 65
    if docker volume inspect "$volume" >/dev/null 2>&1; then
      compose down --volumes --remove-orphans
    fi
    rm -f "$state_file"
    rmdir "$STATE_DIR" 2>/dev/null || true
    printf 'Tore down only isolated PayFast E2E project %s.\n' "$project"
    ;;
esac
