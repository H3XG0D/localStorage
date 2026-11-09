#!/usr/bin/env bash
# release-windows.sh — cross-compile Windows CLI with FOCUSVPN_API_BASE → dist/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${FOCUSVPN_DIST:-$ROOT/dist}"
API="${FOCUSVPN_API_BASE:?set FOCUSVPN_API_BASE e.g. https://api.example.com}"
mkdir -p "$DIST/windows"
LDFLAGS="-s -w -X main.defaultAPIBase=${API}"
echo "==> release-windows API=$API (GOOS=windows GOARCH=amd64)"
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "$LDFLAGS" \
  -o "$DIST/windows/focusvpn-windows.exe" "$ROOT/clients/windows/cmd/focusvpn-windows"
cat >"$DIST/windows/README.txt" <<EOF
FocusVPN Windows sideload (Launch-L1)
API default: $API

Place wintun.dll next to focusvpn-windows.exe when using the native tunnel
(see clients/windows/README.md). For smoke/dry-run:

  focusvpn-windows.exe register --email you@example.com --password ...
  focusvpn-windows.exe login --email you@example.com --password ...
  focusvpn-windows.exe connect --dry-run
EOF
# Copy wintun placeholder note if present
if [[ -f "$ROOT/clients/windows/README.md" ]]; then
  cp "$ROOT/clients/windows/README.md" "$DIST/windows/WINDOWS.md"
fi
echo "release-windows PASS → $DIST/windows/focusvpn-windows.exe"
