#!/usr/bin/env bash
# Start isolated E1 sandbox (FocusVPN PG :15432 + FocusPay PG :15433). Never touches prod.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=sandbox-lib.sh
source "$ROOT/scripts/sandbox-lib.sh"

COMPOSE=(podman compose -f "$ROOT/infra/sandbox/docker-compose.yml")
if ! podman compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose -f "$ROOT/infra/sandbox/docker-compose.yml")
fi

ENV_EX="$ROOT/infra/sandbox/.env.sandbox.example"
ENV_F="$ROOT/infra/sandbox/.env.sandbox"
if [[ ! -f "$ENV_F" ]]; then
  cp "$ENV_EX" "$ENV_F"
  echo "Created $ENV_F from example"
fi

export FOCUSVPN_SANDBOX=1
load_sandbox_env

echo "==> up sandbox postgres (15432 focusvpn / 15433 focuspay)"
"${COMPOSE[@]}" up -d

echo "==> wait healthy"
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T focusvpn-pg pg_isready -U focusvpn_sandbox -d myvpn_sandbox >/dev/null 2>&1 \
     && "${COMPOSE[@]}" exec -T focuspay-pg pg_isready -U focuspay_sandbox -d focuspay_sandbox >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
"${COMPOSE[@]}" exec -T focusvpn-pg pg_isready -U focusvpn_sandbox -d myvpn_sandbox
"${COMPOSE[@]}" exec -T focuspay-pg pg_isready -U focuspay_sandbox -d focuspay_sandbox

echo "==> migrate FocusVPN sandbox DB"
FOCUSVPN_DATABASE_URL="$FOCUSVPN_DATABASE_URL" go run ./backend/cmd/migrate -url "$FOCUSVPN_DATABASE_URL" up
FOCUSVPN_DATABASE_URL="$FOCUSVPN_DATABASE_URL" go run ./backend/cmd/seed -url "$FOCUSVPN_DATABASE_URL" || true

echo "==> ensure FocusPay sandbox seed (idempotent if volume already init)"
PGPASSWORD=focuspay_sandbox psql -h 127.0.0.1 -p 15433 -U focuspay_sandbox -d focuspay_sandbox \
  -f "$ROOT/infra/sandbox/focuspay-init.sql" >/dev/null

echo "SANDBOX UP"
echo "  FocusVPN PG:     postgres://focusvpn_sandbox:***@127.0.0.1:15432/focusvpn_sandbox"
echo "  FocusPay PG:  postgresql://focuspay_sandbox:***@127.0.0.1:15433/focuspay_sandbox"
echo "  Next: make sandbox-run   # CP + FocusPay wallet on :18080/:18081"
echo "        make sandbox-smoke"
