#!/usr/bin/env bash
# Safety helpers for E1 sandbox — refuse production FocusPay DSN.
set -euo pipefail

assert_sandbox() {
  if [[ "${FOCUSVPN_SANDBOX:-}" != "1" ]]; then
    echo "REFUSE: set FOCUSVPN_SANDBOX=1 (refusing to touch non-sandbox env)" >&2
    exit 2
  fi
}

assert_not_prod_focuspay_dsn() {
  local dsn="${1:-${DATABASE_DSN:-}}"
  if [[ -z "$dsn" ]]; then
    return 0
  fi
  # Production FocusPay in this workspace historically uses exchange_bot@:5432
  if echo "$dsn" | grep -Eq 'exchange_bot@|:5432/exchange_bot|/exchange_bot(\?|$)'; then
    if ! echo "$dsn" | grep -Eq ':15433/|focuspay_sandbox'; then
      echo "REFUSE: DATABASE_DSN looks like production FocusPay ($dsn)" >&2
      echo "Use sandbox: postgresql://focuspay_sandbox:...@127.0.0.1:15433/focuspay_sandbox" >&2
      exit 2
    fi
  fi
  if echo "$dsn" | grep -Eq '@127\.0\.0\.1:5432/|:5432/' && ! echo "$dsn" | grep -Eq ':15432/|:15433/'; then
    echo "REFUSE: port 5432 is reserved for non-sandbox / prod-like DBs" >&2
    exit 2
  fi
}

load_sandbox_env() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local envf="${SANDBOX_ENV:-$root/infra/sandbox/.env.sandbox}"
  if [[ ! -f "$envf" ]]; then
    echo "Missing $envf — copy from .env.sandbox.example" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$envf"
  set +a
  export FOCUSVPN_SANDBOX=1
  assert_sandbox
  assert_not_prod_focuspay_dsn
}
