#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
}
trap cleanup EXIT

cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/uvicorn main:app --reload --port 8001 &
BACK_PID=$!

cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run dev -- --port 5174 --host &
FRONT_PID=$!

echo ""
echo "Battle Lab running:"
echo "  Frontend: http://localhost:5174"
echo "  Backend:  http://localhost:8001"
echo "Press Ctrl+C to stop."
wait
