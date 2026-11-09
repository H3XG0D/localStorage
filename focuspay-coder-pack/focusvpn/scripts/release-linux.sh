#!/usr/bin/env bash
# release-linux.sh — build Linux CLI with baked-in FOCUSVPN_API_BASE → dist/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${FOCUSVPN_DIST:-$ROOT/dist}"
API="${FOCUSVPN_API_BASE:?set FOCUSVPN_API_BASE e.g. https://api.example.com}"
mkdir -p "$DIST/linux"
LDFLAGS="-s -w -X main.defaultAPIBase=${API}"
echo "==> release-linux API=$API"
CGO_ENABLED=0 go build -trimpath -ldflags "$LDFLAGS" \
  -o "$DIST/linux/focusvpn" "$ROOT/clients/linux/cmd/focusvpn"
# Optional GTK stub
if [[ "${FOCUSVPN_RELEASE_GTK:-0}" == "1" ]]; then
  CGO_ENABLED=0 go build -trimpath -ldflags "$LDFLAGS" \
    -o "$DIST/linux/focusvpn-gtk" "$ROOT/clients/linux/cmd/focusvpn-gtk" || true
fi
cat >"$DIST/linux/README.txt" <<EOF
FocusVPN Linux sideload (Launch-L1)
API default: $API

  ./focusvpn register --email you@example.com --password '…'
  ./focusvpn login    --email you@example.com --password '…'
  ./focusvpn connect
  ./focusvpn status
  ./focusvpn disconnect

Override API: --api URL on login/register.
EOF
echo "release-linux PASS → $DIST/linux/focusvpn"
