#!/usr/bin/env bash
# Build libwg-go.so for FocusVPN Android from amneziawg-android @ v2.0.2
# (amneziawg-go pin v0.2.19 — NOT upstream master/v3).
#
# Requires: ANDROID_HOME (or ANDROID_SDK_ROOT), NDK 26.x, JDK 17, curl, git, flock.
# Copies only MIT libwg-go.so — never ships GPL libwg.so / libwg-quick.so.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AND="$ROOT/clients/android"
JNILIBs="$AND/app/src/main/jniLibs"
CACHE="${FOCUSVPN_NATIVE_CACHE:-$ROOT/.cache/native}"
AWG_TAG="${FOCUSVPN_AWG_ANDROID_TAG:-v2.0.2}"
AWG_REPO="${FOCUSVPN_AWG_ANDROID_REPO:-https://github.com/amnezia-vpn/amneziawg-android.git}"
PKG="${FOCUSVPN_ANDROID_PACKAGE:-com.focusvpn.app}"
SRC="$CACHE/amneziawg-android-$AWG_TAG"

fail() { echo "build-android-native FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

echo "==> build-android-native (amneziawg-android $AWG_TAG → libwg-go.so)"
echo "    package=$PKG  (must match applicationId for socket paths)"

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
[[ -n "$SDK" ]] || fail "set ANDROID_HOME or ANDROID_SDK_ROOT"
[[ -d "$SDK" ]] || fail "SDK not found: $SDK"

# Prefer NDK 26.1.10909125 (amneziawg-android v2.0.2 settings) else any ndk.
NDK="${ANDROID_NDK_HOME:-}"
if [[ -z "$NDK" ]]; then
  if [[ -d "$SDK/ndk/26.1.10909125" ]]; then
    NDK="$SDK/ndk/26.1.10909125"
  else
    NDK="$(ls -d "$SDK"/ndk/* 2>/dev/null | sort -V | tail -1 || true)"
  fi
fi
[[ -n "$NDK" && -d "$NDK" ]] || fail "Android NDK not found under $SDK/ndk (need ~26.1)"
ok "SDK=$SDK"
ok "NDK=$NDK"

command -v git >/dev/null || fail "git required"
command -v flock >/dev/null || fail "flock required (util-linux; macOS: brew install flock)"

mkdir -p "$CACHE" "$JNILIBs"
if [[ ! -d "$SRC/.git" ]]; then
  echo "==> cloning $AWG_REPO @ $AWG_TAG"
  rm -rf "$SRC"
  git clone --depth 1 --branch "$AWG_TAG" "$AWG_REPO" "$SRC"
else
  echo "==> using cached $SRC"
  git -C "$SRC" fetch --depth 1 origin "refs/tags/$AWG_TAG:refs/tags/$AWG_TAG" 2>/dev/null || true
  git -C "$SRC" checkout -q "$AWG_TAG"
fi

# amneziawg-tools (+ elf-cleaner) are git submodules required by CMakeLists.
echo "==> git submodule update --init --depth 1"
git -C "$SRC" submodule update --init --depth 1 --recursive

# Confirm go pin before building.
GOMOD="$SRC/tunnel/tools/libwg-go/go.mod"
grep -q 'github.com/amnezia-vpn/amneziawg-go v0.2.19' "$GOMOD" \
  || fail "expected amneziawg-go v0.2.19 in $GOMOD (refusing v3)"
ok "go.mod pins amneziawg-go v0.2.19"

# Override package name for FocusVPN (upstream default is org.amnezia.awg).
PROP="$SRC/gradle.properties"
if grep -q '^amneziawgPackageName=' "$PROP"; then
  sed -i.bak "s/^amneziawgPackageName=.*/amneziawgPackageName=$PKG/" "$PROP"
else
  echo "amneziawgPackageName=$PKG" >>"$PROP"
fi
ok "amneziawgPackageName=$PKG"

export ANDROID_HOME="$SDK"
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_NDK_HOME="$NDK"
export ANDROID_PACKAGE_NAME="$PKG"

echo "==> gradle :tunnel:assembleRelease (JDK 17 recommended)"
(
  cd "$SRC"
  if [[ -x ./gradlew ]]; then
    ./gradlew :tunnel:assembleRelease --no-daemon
  else
    fail "gradlew missing in $SRC"
  fi
)

# Locate built libwg-go.so per ABI
mapfile -t SOS < <(find "$SRC/tunnel/build" -name 'libwg-go.so' 2>/dev/null | sort)
[[ ${#SOS[@]} -gt 0 ]] || fail "no libwg-go.so under tunnel/build — NDK/cmake failed?"

copied=0
for so in "${SOS[@]}"; do
  # Path usually .../intermediates/cxx/.../obj/<abi>/libwg-go.so or cmake outs
  abi=""
  case "$so" in
    */arm64-v8a/*) abi=arm64-v8a ;;
    */armeabi-v7a/*) abi=armeabi-v7a ;;
    */x86_64/*) abi=x86_64 ;;
    */x86/*) abi=x86 ;;
  esac
  if [[ -z "$abi" ]]; then
    # Fallback: parent dir name
    abi="$(basename "$(dirname "$so")")"
  fi
  case "$abi" in
    arm64-v8a|armeabi-v7a|x86_64|x86) ;;
    *) echo "  skip unrecognized path: $so"; continue ;;
  esac
  dest="$JNILIBs/$abi"
  mkdir -p "$dest"
  cp -f "$so" "$dest/libwg-go.so"
  ok "copied $abi/libwg-go.so ($(wc -c <"$dest/libwg-go.so") bytes)"
  copied=$((copied + 1))
done
[[ "$copied" -gt 0 ]] || fail "copied 0 ABIs"

# Refuse accidental GPL tool binaries in jniLibs
if find "$JNILIBs" -name 'libwg.so' -o -name 'libwg-quick.so' | grep -q .; then
  fail "GPL libwg*.so must not be shipped in jniLibs — remove them"
fi

echo "build-android-native PASS ($copied ABI(s) → $JNILIBs)"
echo "Next: make android-native-pack   # CI ABI tarball"
echo "      cd clients/android && ./gradlew :app:assembleDebug"
