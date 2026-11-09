#!/usr/bin/env bash
set -euo pipefail

profile="${STAGING_BOOTSTRAP_PROFILE:-payments}"
case "$profile" in
  pvp|payments)
    exec bash /bootstrap/00-apply-migrations.sh "$profile"
    ;;
  full-panel|full-panel-pvp)
    exec bash /bootstrap/20-full-panel-bootstrap.sh "$profile"
    ;;
  *)
    printf 'Unsupported staging bootstrap profile: %s (available: pvp, payments, full-panel, full-panel-pvp)\n' "$profile" >&2
    exit 64
    ;;
esac
