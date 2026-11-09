#!/usr/bin/env bash
# Create and remove only a uniquely named disposable Casino E2E Compose project.
set -euo pipefail

if [[ "${STAGING_E2E_CASINO:-}" != "1" ]]; then
  printf 'Refusing Casino E2E: set STAGING_E2E_CASINO=1.\n' >&2
  exit 64
fi

run_id="${1:-}"
if [[ ! "$run_id" =~ ^[a-z0-9]{12,32}$ ]]; then
  printf 'Run ID must be 12-32 lowercase alphanumeric characters.\n' >&2
  exit 64
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
casino_root="${CASINO_E2E_WORKSPACE:-$repo_root/../focuspay-casino}"
if [[ ! -f "$casino_root/tests/e2e/test_staging_pvp_recovery.py" ]]; then
  printf 'Casino E2E workspace is unavailable or not an approved synthetic test checkout.\n' >&2
  exit 66
fi

for env_file in "${STAGING_E2E_CASINO_ENV_FILE:-}" "${STAGING_E2E_CASINO_CASINO_ENV_FILE:-}"; do
  if [[ -z "$env_file" || ! -r "$env_file" ]]; then
    printf 'Casino E2E requires supplied readable synthetic env files.\n' >&2
    exit 66
  fi
  if grep -Eqi '(focuspay\.org|153\.80\.249\.77)' "$env_file"; then
    printf 'Casino E2E rejected production marker in supplied env file.\n' >&2
    exit 65
  fi
done

project="focuspay-casino-e2e-$run_id"
volume="${project}-postgres"
export COMPOSE_PROJECT_NAME="$project"
export STAGING_E2E_CASINO_DB="e2e_casino_$run_id"
export STAGING_E2E_CASINO_VOLUME="$volume"

cd "$repo_root"
docker compose -f focussite/docker-compose.casino-e2e.yml config --quiet
cleanup() {
  docker compose -f focussite/docker-compose.casino-e2e.yml down --remove-orphans
  printf 'Retained disposable E2E volume for audit: %s\n' "$volume" >&2
}
trap cleanup EXIT
if ! docker compose -f focussite/docker-compose.casino-e2e.yml up --build --wait backend; then
  docker compose -f focussite/docker-compose.casino-e2e.yml logs --tail=120 backend >&2 || true
  exit 1
fi
docker compose -f focussite/docker-compose.casino-e2e.yml run --no-deps --rm casino-e2e