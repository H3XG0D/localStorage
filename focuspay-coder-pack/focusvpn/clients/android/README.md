# FocusVPN Android

Compose client. Login via Telegram, one Connect button. The tunnel is VLESS through
**libXray** `v26.9.30` (MIT; embeds Xray-core MPL-2.0, unmodified). The control plane
picks the least-loaded node and sends fallbacks; the app tries the next server if the
first one does not pass traffic.

Russian names and RIPE-RU addresses leave on the phone's own IP (`vpn/RuDirect.kt`,
`assets/ru-prefixes.txt`). Foreign traffic stays in the tunnel. Refresh the prefix
snapshot with `python3 scripts/refresh-ru-prefixes.py`.

## Layout

| Path | Role |
|---|---|
| `ui/` | Auth / Home / Locations / Account |
| `data/` | Control-plane client, encrypted session |
| `crypto/X25519Keys.kt` | Device keypair registered with the control plane |
| `vpn/XrayClientConfig.kt` | ConfigParts → Xray JSON |
| `vpn/RuDirect.kt` | RU domains and prefixes → direct outbound |
| `vpn/XrayTunnelEngine.kt` | libXray `runXray` + socket protect |
| `vpn/FocusVpnService.kt` | TUN + failover |
| `.libxray/libXray.aar` | gitignored; `scripts/fetch-libxray-android.sh` |

## Build

```bash
scripts/fetch-libxray-android.sh
cd clients/android && ./gradlew :app:testDebugUnitTest :app:assembleDebug
```

JDK 17, Android SDK. minSdk 26.
