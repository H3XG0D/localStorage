#!/bin/sh
set -eu

test -r /seed/exchange_bot.dump || {
  echo "Missing local schema dump: /seed/exchange_bot.dump" >&2
  exit 1
}

pg_restore \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --schema-only \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  /seed/exchange_bot.dump
