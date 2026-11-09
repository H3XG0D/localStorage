#!/usr/bin/env bash
# Build libwg-go.so via container (NDK 26.1) when host has no Android SDK.
# Prefer podman, else docker. Image: smithmicro/android-build:34-ndk26.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${FOCUSVPN_ANDROID_NATIVE_IMAGE:-docker.io/smithmicro/android-build:34-ndk26}"
PKG="${FOCUSVPN_ANDROID_PACKAGE:-com.focusvpn.app}"
AWG_TAG="${FOCUSVPN_AWG_ANDROID_TAG:-v2.0.2}"

fail() { echo "android-native-docker FAIL: $*" >&2; exit 1; }
ok() { echo "  ok  $*"; }

ENGINE=""
if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
else
  fail "need podman or docker"
fi
ok "engine=$ENGINE image=$IMAGE"

# Resolve ANDROID_HOME inside the image (smithmicro layout).
# Their images typically set ANDROID_SDK_ROOT=/opt/android-sdk-linux or similar.
INNER_SCRIPT=$(cat <<'EOS'
set -euo pipefail
cd /work
export FOCUSVPN_ANDROID_PACKAGE="${FOCUSVPN_ANDROID_PACKAGE:-com.focusvpn.app}"
export FOCUSVPN_AWG_ANDROID_TAG="${FOCUSVPN_AWG_ANDROID_TAG:-v2.0.2}"
export FOCUSVPN_NATIVE_CACHE=/work/.cache/native

# Locate SDK/NDK from common image layouts.
if [[ -z "${ANDROID_HOME:-}" || ! -d "${ANDROID_HOME:-}" ]]; then
  for d in /opt/android-sdk-linux /opt/android-sdk /usr/local/lib/android/sdk /sdk; do
    if [[ -d "$d" ]]; then
      export ANDROID_HOME="$d"
      break
    fi
  done
fi
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
[[ -n "${ANDROID_HOME:-}" && -d "$ANDROID_HOME" ]] || {
  echo "ANDROID_HOME not found in image" >&2
  ls -la /opt 2>/dev/null || true
  env | grep -i android || true
  exit 1
}

# Prefer pinned NDK 26.1 even if the image exported a stale ANDROID_NDK_HOME.
if [[ -d "$ANDROID_HOME/ndk/26.1.10909125" ]]; then
  export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/26.1.10909125"
elif [[ -z "${ANDROID_NDK_HOME:-}" || ! -d "${ANDROID_NDK_HOME}" ]]; then
  export ANDROID_NDK_HOME="$(ls -d "$ANDROID_HOME"/ndk/* 2>/dev/null | sort -V | tail -1 || true)"
fi
[[ -n "${ANDROID_NDK_HOME:-}" && -d "$ANDROID_NDK_HOME" ]] || {
  echo "NDK not found under $ANDROID_HOME/ndk" >&2
  ls -la "$ANDROID_HOME/ndk" 2>/dev/null || true
  echo "ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-<unset>}" >&2
  exit 1
}

echo "ANDROID_HOME=$ANDROID_HOME"
echo "ANDROID_NDK_HOME=$ANDROID_NDK_HOME"
command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git util-linux curl ca-certificates >/dev/null; }
command -v flock >/dev/null || { apt-get update -qq && apt-get install -y -qq util-linux >/dev/null; }

bash scripts/build-android-native.sh
bash scripts/android-native-abi.sh pack
bash scripts/android-native-abi.sh verify
EOS
)

echo "==> pull $IMAGE (may take a few minutes)"
"$ENGINE" pull "$IMAGE"

# Host-writable dirs for volume mount (image user is often non-root).
mkdir -p "$ROOT/.cache/native/abi" \
  "$ROOT/clients/android/app/src/main/jniLibs"

echo "==> build libwg-go.so inside container"
# SELinux/podman: :Z on volume when available; ignore if unsupported.
VOL_OPTS="rw"
USER_ARGS=()
if [[ "$ENGINE" == "podman" ]]; then
  VOL_OPTS="rw,Z"
  # Map container processes to the host UID so writes to /work succeed.
  USER_ARGS=(--userns=keep-id)
else
  USER_ARGS=(-u "$(id -u):$(id -g)")
fi

"$ENGINE" run --rm \
  "${USER_ARGS[@]}" \
  -e HOME=/tmp \
  -e FOCUSVPN_ANDROID_PACKAGE="$PKG" \
  -e FOCUSVPN_AWG_ANDROID_TAG="$AWG_TAG" \
  -v "$ROOT:/work:$VOL_OPTS" \
  -w /work \
  "$IMAGE" \
  bash -lc "$INNER_SCRIPT"

KEY="$(bash "$ROOT/scripts/android-native-abi.sh" key)"
TGZ="$ROOT/.cache/native/abi/${KEY}.tgz"
[[ -f "$TGZ" ]] || fail "expected tarball $TGZ"
ok "ABI tarball ready: $TGZ ($(wc -c <"$TGZ") bytes)"
echo "android-native-docker PASS"
echo "Restore later: make android-native-restore"
