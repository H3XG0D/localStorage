# jniLibs — AmneziaWG userspace (`libwg-go.so`)

Place **only** `libwg-go.so` (MIT, amneziawg-go **v0.2.19**) under:

```
jniLibs/arm64-v8a/libwg-go.so
jniLibs/armeabi-v7a/libwg-go.so
jniLibs/x86_64/libwg-go.so   # emulator
```

## Build

```bash
# Requires ANDROID_HOME + NDK ~26.1 + JDK 17
make android-native
# Or without host SDK (podman/docker):
make android-native-docker
make android-native-pack    # → .cache/native/abi/libwg-go-v2.0.2-com.focusvpn.app-v0.2.19.tgz
make android-native-verify
```

Source pin: **amneziawg-android `v2.0.2`** (not `master` / `v3.*` — those pull `amneziawg-go/v3`).
Package name baked into the binary: `com.focusvpn.app` (matches `applicationId`).

## CI cache (P4-M9)

Workflow [`.github/workflows/android-native.yml`](../../../../../../.github/workflows/android-native.yml):
- Builds on Ubuntu with NDK 26.1 when the ABI cache misses
- Caches / uploads `.cache/native/abi/<key>.tgz` (artifact name = cache key)
- Restore locally without NDK:

```bash
# After downloading the workflow artifact tarball:
FOCUSVPN_NATIVE_ABI_TGZ=/path/to/libwg-go-v2.0.2-com.focusvpn.app-v0.2.19.tgz \
  make android-native-restore
```

Cache key: `libwg-go-v2.0.2-com.focusvpn.app-v0.2.19` (`make` / `scripts/android-native-abi.sh key`).

## Do not ship

- `libwg.so` / `libwg-quick.so` — built from **amneziawg-tools (GPL-2.0)**; FocusVPN must not put them in the APK.

## Without NDK

`AmneziaTunnelEngine` still starts the TUN; handshake is skipped until these `.so` files exist
(or until you restore a CI ABI tarball).
