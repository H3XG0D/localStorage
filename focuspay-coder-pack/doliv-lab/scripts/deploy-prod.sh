#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.prod.example..."
  cp .env.prod.example .env
  echo "Edit .env (SECRET_KEY, CORS_ORIGINS) then re-run."
  exit 1
fi

# Ensure HTTP cookie settings
if ! grep -q '^COOKIE_SECURE=' .env; then
  echo 'COOKIE_SECURE=false' >> .env
fi

echo "Building and starting production stack..."
docker compose -f docker-compose.prod.yml up -d --build

echo "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1/health >/dev/null 2>&1; then
    echo "OK: http://127.0.0.1/health"
    break
  fi
  sleep 2
done

echo "Done. Open http://$(hostname -I | awk '{print $1}')/login"
echo "Create users via admin panel or run: docker compose -f docker-compose.prod.yml exec backend python scripts/create_admin.py"
