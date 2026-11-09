#!/usr/bin/env bash
# Download the pinned XTLS/libXray Android artifact (MIT; embeds Xray-core MPL-2.0).
# Output: clients/android/.libxray/libXray.aar  (gitignored)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VER=${LIBXRAY_VERSION:-v26.9.30}
SHA=${LIBXRAY_SHA256:-394b59d147b37ab46003bd3f1d687ed3b2f637cabfc0cb863f179c5a87bddde3}
DEST="$ROOT/clients/android/.libxray"
ZIP="$DEST/libxray-android.zip"
URL="https://github.com/XTLS/libXray/releases/download/${VER}/libxray-android.zip"

mkdir -p "$DEST"
if [[ ! -f "$ZIP" ]] || ! echo "$SHA  $ZIP" | sha256sum -c - >/dev/null 2>&1; then
  curl -fL --retry 3 -o "$ZIP.partial" "$URL"
  mv "$ZIP.partial" "$ZIP"
  echo "$SHA  $ZIP" | sha256sum -c -
fi
rm -rf "$DEST/unzip"
mkdir -p "$DEST/unzip"
unzip -q -o "$ZIP" -d "$DEST/unzip"
AAR=$(find "$DEST/unzip" -name '*.aar' | head -1)
[[ -n "$AAR" ]] || { echo "no .aar in $ZIP" >&2; exit 1; }
cp "$AAR" "$DEST/libXray.aar"
echo "libXray ${VER} -> $DEST/libXray.aar"
