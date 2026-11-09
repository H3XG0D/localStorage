#!/usr/bin/env bash
# Pack / restore / verify Android libwg-go.so ABI bundles (CI cache + local reuse).
#
# Never packs GPL libwg.so / libwg-quick.so.
# Cache key embeds amneziawg-android tag, package name, and go pin.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JNILIBs="$ROOT/clients/android/app/src/main/jniLibs"
CACHE="${FOCUSVPN_NATIVE_CACHE:-$ROOT/.cache/native}"
ABI_DIR="${FOCUSVPN_NATIVE_ABI_DIR:-$CACHE/abi}"
AWG_TAG="${FOCUSVPN_AWG_ANDROID_TAG:-v2.0.2}"
PKG="${FOCUSVPN_ANDROID_PACKAGE:-com.focusvpn.app}"
GO_PIN="v0.2.19"

fail() { echo "android-native-abi FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

abi_key() {
  # Stable identity for actions/cache and tarball names.
  echo "libwg-go-${AWG_TAG}-${PKG}-${GO_PIN}"
}

tarball_path() {
  echo "$ABI_DIR/$(abi_key).tgz"
}

cmd_key() {
  abi_key
}

cmd_verify() {
  [[ -d "$JNILIBs" ]] || fail "jniLibs missing: $JNILIBs"
  n=$(find "$JNILIBs" -name 'libwg-go.so' 2>/dev/null | wc -l | tr -d ' ')
  [[ "$n" -gt 0 ]] || fail "no libwg-go.so under jniLibs (build or restore first)"
  if find "$JNILIBs" \( -name 'libwg.so' -o -name 'libwg-quick.so' \) | grep -q .; then
    fail "GPL libwg*.so must not be in jniLibs"
  fi
  # Require at least one production ABI.
  [[ -f "$JNILIBs/arm64-v8a/libwg-go.so" ]] || fail "missing arm64-v8a/libwg-go.so"
  ok "verified $n libwg-go.so (no GPL tools)"
  find "$JNILIBs" -name 'libwg-go.so' -printf '    %P (%s bytes)\n' 2>/dev/null \
    || find "$JNILIBs" -name 'libwg-go.so' | while read -r f; do
         echo "    ${f#"$JNILIBs"/} ($(wc -c <"$f") bytes)"
       done
}

cmd_pack() {
  cmd_verify
  mkdir -p "$ABI_DIR"
  local tar
  tar="$(tarball_path)"
  # Pack relative ABI dirs only (libwg-go.so).
  (
    cd "$JNILIBs"
    mapfile -t files < <(find . -name 'libwg-go.so' | sort)
    [[ ${#files[@]} -gt 0 ]] || fail "nothing to pack"
    tar -czf "$tar" "${files[@]}"
  )
  ok "packed $(abi_key).tgz ($(wc -c <"$tar") bytes) → $tar"
  echo "$tar"
}

cmd_restore() {
  local tar="${1:-${FOCUSVPN_NATIVE_ABI_TGZ:-}}"
  if [[ -z "$tar" ]]; then
    tar="$(tarball_path)"
  fi
  [[ -f "$tar" ]] || fail "ABI tarball not found: $tar (run make android-native && make android-native-pack)"
  mkdir -p "$JNILIBs"
  tar -xzf "$tar" -C "$JNILIBs"
  ok "restored from $tar"
  cmd_verify
}

usage() {
  cat <<EOF
Usage: $0 <key|pack|restore|verify> [tarball]

  key      Print cache key (libwg-go-<tag>-<pkg>-v0.2.19)
  pack     Tar jniLibs/*/libwg-go.so → \$FOCUSVPN_NATIVE_CACHE/abi/<key>.tgz
  restore  Unpack tarball into jniLibs (default: cached <key>.tgz)
  verify   Ensure libwg-go.so present and no GPL libwg*.so

Env: FOCUSVPN_AWG_ANDROID_TAG FOCUSVPN_ANDROID_PACKAGE FOCUSVPN_NATIVE_CACHE FOCUSVPN_NATIVE_ABI_TGZ
EOF
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    key) cmd_key ;;
    pack) cmd_pack ;;
    restore) cmd_restore "${1:-}" ;;
    verify) cmd_verify ;;
    ""|-h|--help) usage; exit 0 ;;
    *) usage; fail "unknown command: $cmd" ;;
  esac
}

main "$@"
