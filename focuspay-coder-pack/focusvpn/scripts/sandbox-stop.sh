#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/infra/sandbox/run"
for f in focusvpn.pid focuspay.pid bot.pid; do
  if [[ -f "$RUN_DIR/$f" ]]; then
    kill "$(cat "$RUN_DIR/$f")" 2>/dev/null || true
    rm -f "$RUN_DIR/$f"
  fi
done
echo "SANDBOX SERVICES STOPPED"
