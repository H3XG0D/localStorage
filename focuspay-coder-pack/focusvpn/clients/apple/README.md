# FocusVPN Apple (P3-M4c + WireGuardKitGo)

FocusPay-styled SwiftUI client for **iOS + macOS**. Control Plane HTTP +
`NEPacketTunnelProvider` + AmneziaWG userspace via **amneziawg-apple** WireGuardKitGo
(`wgTurnOn`, amneziawg-go pin `v0.2.19`). Without the go bridge, NE settings still apply.

## Layout

| Path | Role |
|---|---|
| `Sources/App/` | SwiftUI Auth / Home / Locations / Account |
| `Sources/Shared/` | CP client, Keychain, Theme, TunnelConfig, AwgConfig, X25519Keys |
| `Sources/Tunnel/` | PacketTunnelProvider + AmneziaTunnelEngine + AmneziaGoBridge |
| `project.yml` | XcodeGen → App + Packet Tunnel (iOS + macOS) |
| `Package.swift` | ConfigParts + TunnelConfig + AwgConfig unit tests (SwiftPM) |

## Requirements

- macOS + Xcode 15+ / XcodeGen (`brew install xcodegen`)
- Apple Developer team with Network Extension entitlement
- min iOS 16 / macOS 13
- For handshake: link **amneziawg-apple `v2.0.3`** WireGuardKitGo (not master/v3) and set
  Active Compilation Condition **`FOCUSVPN_AWG_GO`** on tunnel targets

## Build

```bash
make apple-check
make native-libs-check

# Interactive Mac-only linking steps:
./scripts/wizard-apple-native.sh

cd clients/apple
xcodegen generate
open FocusVPN.xcodeproj
```

## Non-negotiables

- Private keys in Keychain + NE `providerConfiguration`
- No GPL/AGPL (no OpenVPNAdapter)
- Pin classic `amneziawg-go` **v0.2.19**
- See root `NOTICE.md`
