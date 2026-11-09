#!/usr/bin/env bash
# Wipe sandbox volumes — still never touches production.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(podman compose -f "$ROOT/infra/sandbox/docker-compose.yml")
if ! podman compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose -f "$ROOT/infra/sandbox/docker-compose.yml")
fi
export FOCUSVPN_SANDBOX=1
"${COMPOSE[@]}" down -v
echo "SANDBOX RESET (volumes deleted)"
