#!/usr/bin/env bash
# Run backend pytest on isolated staging via the tests Compose profile.
# Optional first argument is passed to pytest -k (example: casino).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.staging-runtime.yml"
ENV_FILE="${STAGING_RUNTIME_ENV_FILE:-$SCRIPT_DIR/../.env.staging-runtime}"
export STAGING_RUNTIME_ENV_FILE="$ENV_FILE"

cd "$SCRIPT_DIR/.."

pytest_args=(python -m pytest tests/ -q)
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  pytest_args+=(-k "$1")
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  --profile tests run --rm -T --build backend-tests "${pytest_args[@]}"
