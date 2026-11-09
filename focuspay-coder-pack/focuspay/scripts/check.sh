#!/usr/bin/env bash
# Local quality gate.
#   ./scripts/check.sh          # fast: stdlib operator, drift detector, tsc, smoke
#   ./scripts/check.sh --full   # also bot+backend pytest, vite build, bandit
#
# Use the project venv if you have one:
#   PYTHON=/path/to/venv/bin/python ./scripts/check.sh --full
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
FULL=0
if [[ "${1:-}" == "--full" ]]; then
  FULL=1
fi

failed=0
section() { printf '\n==> %s\n' "$*"; }

run() {
  local label="$1"
  shift
  section "$label"
  if "$@"; then
    printf 'OK  %s\n' "$label"
  else
    printf 'FAIL  %s\n' "$label" >&2
    failed=1
  fi
}

section "stdlib operator (backend cwd must not shadow it)"
if (
  cd "$ROOT/site/exchange-backend"
  "$PYTHON" -c "from operator import eq; assert eq(1, 1)"
); then
  printf 'OK  stdlib operator\n'
else
  printf 'FAIL  stdlib operator — is site/exchange-backend/operator.py back in the root?\n' >&2
  failed=1
fi

if ! "$PYTHON" -c "import pytest" 2>/dev/null; then
  echo "pytest is not installed. pip install pytest" >&2
  echo "Backend extras: pip install -r site/exchange-backend/requirements-dev.txt" >&2
  exit 1
fi

run "mirrored-module drift" "$PYTHON" -m pytest "$ROOT/site/exchange-backend/tests/test_mirrored_modules.py"

if [[ "$FULL" == "1" ]]; then
  run "bot pytest" "$PYTHON" -m pytest "$ROOT/bot/tg_bot_btc/tests"
  run "backend pytest" "$PYTHON" -m pytest "$ROOT/site/exchange-backend/tests"
fi

FRONTEND="$ROOT/focussite/frontend"
if [[ -d "$FRONTEND/node_modules" ]]; then
  run "frontend tsc" bash -lc "cd \"$FRONTEND\" && npx tsc -b"
  run "smoke ai-tasks" node "$FRONTEND/scripts/smoke-ai-tasks-regression.mjs"
  if [[ -f "$FRONTEND/scripts/smoke-admin-broadcast.mjs" ]]; then
    run "smoke broadcast" node "$FRONTEND/scripts/smoke-admin-broadcast.mjs"
  fi
  if [[ "$FULL" == "1" ]]; then
    run "frontend build" bash -lc "cd \"$FRONTEND\" && npm run build"
  fi
else
  echo "skip frontend: $FRONTEND/node_modules missing (npm install)"
fi

if [[ "$FULL" == "1" ]]; then
  if command -v bandit >/dev/null 2>&1; then
    run "bandit backend" bandit -c "$ROOT/site/exchange-backend/bandit.yaml" -r "$ROOT/site/exchange-backend"
    if [[ -f "$ROOT/bot/tg_bot_btc/bandit.yaml" ]]; then
      run "bandit bot" bandit -c "$ROOT/bot/tg_bot_btc/bandit.yaml" -r "$ROOT/bot/tg_bot_btc"
    fi
  else
    echo "bandit not installed; pip install bandit" >&2
    failed=1
  fi
fi

if [[ "$failed" != "0" ]]; then
  echo "check.sh failed" >&2
  exit 1
fi
echo
if [[ "$FULL" == "1" ]]; then
  echo "check.sh --full passed"
else
  echo "check.sh passed (fast). Full suites: ./scripts/check.sh --full"
fi
