#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(podman compose -f "$ROOT/infra/sandbox/docker-compose.yml")
if ! podman compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose -f "$ROOT/infra/sandbox/docker-compose.yml")
fi
export FOCUSVPN_SANDBOX=1
"${COMPOSE[@]}" down
echo "SANDBOX DOWN (volumes kept). To wipe: make sandbox-reset"
