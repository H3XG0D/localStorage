#!/usr/bin/env bash
# Open the ecosystem brain (~/Documents/brain) in Obsidian.
# FocusVPN docs are part of it via symlink Projects/FocusVPN -> focusvpn/docs.
set -euo pipefail
VAULT="$HOME/Documents/brain"

if ! command -v flatpak >/dev/null 2>&1; then
  echo "flatpak not found; install Obsidian manually and open: $VAULT" >&2
  exit 1
fi

if ! flatpak info md.obsidian.Obsidian >/dev/null 2>&1; then
  echo "Obsidian flatpak missing. Install:" >&2
  echo "  flatpak install -y flathub md.obsidian.Obsidian" >&2
  exit 1
fi

ENC_PATH="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$VAULT")"
exec flatpak run md.obsidian.Obsidian "obsidian://open?path=${ENC_PATH}"
