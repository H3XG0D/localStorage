# NOTICE

FocusVPN includes third-party open-source software. See `THIRD_PARTY_LICENSES.md` for
license texts and attribution.

## Important license notes

- **amneziawg-tools** (`awg`, `awg-quick`) are **GPL-2.0**. FocusVPN invokes them only as
  **separate processes** (node-agent and Linux client). They are **not** linked into
  FocusVPN product binaries.
- **amneziawg-go** (MIT, pin `v0.2.19`) is **linked** into AppCore (`engine.GoEngine`) for
  Linux/desktop product clients and the **Windows** client (`WintunEngine` → GoEngine over
  prebuilt `wintun.dll`). Node peer apply still uses `awg` as a separate process.
  Android loads the same engine via **JNI** (`libwg-go.so` / `AmneziaTunnelEngine`); Apple
  uses WireGuardKitGo (`wgTurnOn`) when linked (P3-M4c).
- **wireguard-go** (`golang.zx2c4.com/wireguard`, MIT) is **linked** into AppCore
  (`engine.WGEngine`); select with `FOCUSVPN_ENGINE=wireguard`.
- **Xray-core** (MPL-2.0): **not linked** into AppCore. `engine.XrayEngine` writes client JSON
  and runs `xray` / `XRAY_BIN` as a **separate process** (`FOCUSVPN_ENGINE=xray`). Do not
  modify Xray sources in-tree (ADR-002).
- **libXray** (MIT, pin `v26.9.30`) **is linked** into the Android app (`libXray.aar`).
  It embeds unmodified Xray-core (MPL-2.0). Source: https://github.com/XTLS/libXray/tree/v26.9.30
  and https://github.com/XTLS/Xray-core. Fetch with `scripts/fetch-libxray-android.sh`.
  The node-agent still talks to Xray only as a separate process.
- **amneziawg-android** (Apache-2.0): Android AmneziaWG base. P3-M3c ships UAPI + JNI surface;
  native `libwg-go.so` is built from **amneziawg-android `v2.0.2`** via `make android-native`
  (pin amneziawg-go `v0.2.19` — do not use android `master`/`v3.*`). Do not ship GPL
  `libwg.so` / `libwg-quick.so`.
- **Bouncy Castle** (`bcprov-jdk18on`, Bouncy Castle Licence): used on Android for X25519
  key generation only (`X25519Keys`).
- **wireguard-apple** (MIT) is the architectural base for iOS/macOS (`clients/apple/`,
  Network Extension). **amneziawg-apple** (MIT) `v2.0.3` is the WireGuardKitGo path
  (`./scripts/wizard-apple-native.sh` + `FOCUSVPN_AWG_GO`); tip/`v3.*` uses `amneziawg-go/v3` — refused.
- **wintun.dll** (WireGuard LLC Prebuilt Binaries License): ship side-by-side with the
  Windows EXE; load via `LoadLibraryEx` probe + amneziawg-go `CreateTUN` (runtime). Do **not**
  statically link GPL wintun sources. P3-M5b: `WintunEngine` bridges AmneziaWG via
  **amneziawg-go** (same pin). **amneziawg-windows** (MIT) remains an optional alternate
  service-style embedding path (see OPEN_SOURCE); product path is go + prebuilt wintun.
- Do **not** add GPL/AGPL libraries to product binaries without an ADR and legal review.
  **OpenVPNAdapter (AGPL-3.0) is forbidden** on Apple targets.

Copyright (c) FocusVPN contributors. All rights reserved for first-party code unless
otherwise noted.
