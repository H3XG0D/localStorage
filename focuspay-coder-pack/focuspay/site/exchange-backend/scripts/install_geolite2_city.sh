#!/usr/bin/env bash
# Скачать GeoLite2-City.mmdb (нужен бесплатный ключ MaxMind).
# export MAXMIND_LICENSE_KEY=...
# ./scripts/install_geolite2_city.sh
set -euo pipefail
KEY="${MAXMIND_LICENSE_KEY:-}"
DEST="${GEOIP_CITY_DB_PATH:-/opt/exchange-backend/GeoLite2-City.mmdb}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if [ -z "$KEY" ]; then
  echo "Задайте MAXMIND_LICENSE_KEY (https://www.maxmind.com/en/geolite2/signup)"
  exit 1
fi

curl -fsSL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${KEY}&suffix=tar.gz" \
  -o "$TMP/GeoLite2-City.tar.gz"
tar -xzf "$TMP/GeoLite2-City.tar.gz" -C "$TMP"
MMDB=$(find "$TMP" -name 'GeoLite2-City.mmdb' | head -1)
[ -n "$MMDB" ] || { echo "mmdb not found in archive"; exit 1; }
cp "$MMDB" "$DEST"
chmod 644 "$DEST"
echo "OK: $DEST ($(du -h "$DEST" | cut -f1))"
