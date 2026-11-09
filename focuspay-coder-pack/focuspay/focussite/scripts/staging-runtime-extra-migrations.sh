#!/usr/bin/env bash
# Apply the migrations that the full-panel bootstrap deliberately leaves out.
#
# The `full-panel-pvp` profile ships a curated schema subset and pairs it with
# STAGING_DISABLE_BACKGROUND_TASKS=true. With background tasks enabled the backend
# startup path and the SELL payout hooks touch tables outside that subset
# (broadcast_jobs, exchanger_bot_config, orders.overpay_credit_rub, …), so a
# click pass that needs those flows must top the schema up first.
#
# Staging only — it points at the disposable Compose database.
#
#   cd focussite
#   ./scripts/staging-runtime-extra-migrations.sh
#
# Re-running is safe: every migration is written to be idempotent, and files that
# depend on a later one are retried on the following pass.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SITE_DIR/.." && pwd)"

ENV_FILE="${STAGING_RUNTIME_ENV_FILE:-$SITE_DIR/.env.staging-runtime}"
COMPOSE_FILE="$SITE_DIR/docker-compose.staging-runtime.yml"
BOOTSTRAP="$SITE_DIR/docker/staging-db/20-full-panel-bootstrap.sh"
MAX_PASSES=4

# Drops objects on purpose; never part of a schema top-up.
EXCLUDE=("rollback_owner_finance_ledger.sql")

[[ -r "$ENV_FILE" ]] || { printf 'environment file is missing: %s\n' "$ENV_FILE" >&2; exit 1; }

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

compose_extra=()
if [[ -n "${STAGING_RUNTIME_COMPOSE_OVERRIDE:-}" ]]; then
  compose_extra=(-f "$STAGING_RUNTIME_COMPOSE_OVERRIDE")
fi

psql_apply() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "${compose_extra[@]}" \
    exec -T postgres psql -q -v ON_ERROR_STOP=1 \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$1" >/dev/null 2>&1
}

is_excluded() {
  local name="$1" skip
  for skip in "${EXCLUDE[@]}"; do
    [[ "$name" == "$skip" ]] && return 0
  done
  return 1
}

pending=()
for dir in "$REPO_ROOT/site/exchange-backend/migrations" "$REPO_ROOT/bot/tg_bot_btc/migrations"; do
  for path in "$dir"/*.sql; do
    name="$(basename "$path")"
    is_excluded "$name" && continue
    grep -qF "$name" "$BOOTSTRAP" && continue
    pending+=("$path")
  done
done

printf 'migrations outside the full-panel bootstrap: %d\n' "${#pending[@]}"

for (( pass = 1; pass <= MAX_PASSES; pass++ )); do
  failed=()
  applied=0
  for path in "${pending[@]}"; do
    if psql_apply "$path"; then
      applied=$(( applied + 1 ))
    else
      failed+=("$path")
    fi
  done
  printf 'pass %d: applied=%d deferred=%d\n' "$pass" "$applied" "${#failed[@]}"
  (( ${#failed[@]} == 0 )) && break
  # No progress means the rest cannot be resolved by reordering.
  if (( applied == 0 )); then
    printf 'stuck on %d migration(s):\n' "${#failed[@]}" >&2
    printf '  %s\n' "${failed[@]}" >&2
    exit 1
  fi
  pending=("${failed[@]}")
done

if (( ${#failed[@]} > 0 )); then
  printf 'still failing after %d passes:\n' "$MAX_PASSES" >&2
  printf '  %s\n' "${failed[@]}" >&2
  exit 1
fi

# asyncpg caches prepared statements; a schema change invalidates them.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "${compose_extra[@]}" \
  up -d --force-recreate backend >/dev/null
printf 'schema topped up; backend recreated to drop stale statement caches\n'
