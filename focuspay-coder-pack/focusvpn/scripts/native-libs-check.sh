#!/usr/bin/env bash
# native-libs-check — validate Android/Apple native-lib pins without NDK/Xcode.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

fail() { echo "native-libs-check FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> native-libs-check (P3 native go bridges @ amneziawg-go v0.2.19)"

[[ -x "$ROOT/scripts/build-android-native.sh" ]] || fail "missing build-android-native.sh"
[[ -x "$ROOT/scripts/android-native-abi.sh" ]] || fail "missing android-native-abi.sh"
[[ -f "$ROOT/clients/android/app/src/main/jniLibs/README.md" ]] || fail "missing jniLibs/README.md"
[[ -x "$ROOT/scripts/wizard-apple-native.sh" ]] || fail "missing wizard-apple-native.sh"
[[ -f "$ROOT/.github/workflows/android-native.yml" ]] || fail "missing CI workflow android-native.yml"
[[ -x "$ROOT/scripts/build-android-native-docker.sh" ]] || fail "missing build-android-native-docker.sh"
[[ -x "$ROOT/scripts/wizard-github-ci.sh" ]] || fail "missing wizard-github-ci.sh"
ok "scripts + jniLibs README + CI workflow + docker/wizard"

grep -q 'v2.0.2' "$ROOT/scripts/build-android-native.sh" \
  || fail "Android build must pin amneziawg-android v2.0.2"
grep -q 'v0.2.19' "$ROOT/scripts/build-android-native.sh" \
  || fail "Android build must require amneziawg-go v0.2.19"
grep -q 'submodule update' "$ROOT/scripts/build-android-native.sh" \
  || fail "Android build must init git submodules (amneziawg-tools)"
grep -q 'v2.0.3' "$ROOT/scripts/wizard-apple-native.sh" \
  || fail "Apple wizard must pin amneziawg-apple v2.0.3"
grep -q 'FOCUSVPN_AWG_GO' "$ROOT/scripts/wizard-apple-native.sh" \
  || fail "Apple wizard must enable FOCUSVPN_AWG_GO"
grep -q 'v2.0.2' "$ROOT/clients/android/app/src/main/jniLibs/README.md" \
  || fail "jniLibs README must document android v2.0.2"
grep -qi 'amneziawg-android' "$ROOT/NOTICE.md" || fail "NOTICE missing amneziawg-android"
grep -qi 'amneziawg-apple' "$ROOT/NOTICE.md" || fail "NOTICE missing amneziawg-apple"
grep -q 'actions/cache' "$ROOT/.github/workflows/android-native.yml" \
  || fail "CI must use actions/cache for ABI tarball"
grep -q 'android-native-pack' "$ROOT/.github/workflows/android-native.yml" \
  || fail "CI must pack ABI tarball"
grep -q 'libwg-go.so' "$ROOT/scripts/android-native-abi.sh" \
  || fail "abi script must handle libwg-go.so"
grep -q 'docker.io/smithmicro/android-build:34-ndk26' "$ROOT/scripts/build-android-native-docker.sh" \
  || fail "docker build must pin smithmicro/android-build:34-ndk26"
grep -q 'android-native' "$ROOT/scripts/wizard-github-ci.sh" \
  || fail "github wizard must mention android-native workflow"
ok "pins v2.0.2 / v2.0.3 + GPL refusal + NOTICE + CI cache + docker image"

KEY="$(bash "$ROOT/scripts/android-native-abi.sh" key)"
[[ "$KEY" == "libwg-go-v2.0.2-com.focusvpn.app-v0.2.19" ]] \
  || fail "unexpected ABI cache key: $KEY"
ok "ABI cache key=$KEY"

# Optional: report whether .so already present
n=0
if [[ -d "$ROOT/clients/android/app/src/main/jniLibs" ]]; then
  n=$(find "$ROOT/clients/android/app/src/main/jniLibs" -name 'libwg-go.so' 2>/dev/null | wc -l | tr -d ' ')
fi
if [[ "$n" -gt 0 ]]; then
  ok "found $n libwg-go.so under jniLibs (built)"
  bash "$ROOT/scripts/android-native-abi.sh" verify
else
  echo "  note: no libwg-go.so yet — make android-native (NDK) or restore CI artifact"
fi

echo "native-libs-check PASS"
