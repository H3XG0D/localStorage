# THIRD_PARTY_LICENSES

Phase 2 / Phase 3 M1 dependency summary. Full license texts live in upstream repos;
this file is the attribution gate for CI and store submissions (CLIENT_ARCHITECTURE §8).

## Direct / product-relevant

| Component | License | How used in FocusVPN |
|---|---|---|
| golang-jwt/jwt/v5 | MIT | Access JWT (EdDSA) |
| golang.org/x/crypto | BSD-3-Clause | Argon2id, curve25519 |
| jackc/pgx/v5 | MIT | PostgreSQL driver |
| golang-migrate/migrate | MIT | SQL migrations |
| clients/shared (first-party) | Proprietary | API DTOs, configcrypto, tunnel conf |
| amneziawg-go **v0.2.19** | MIT | **Linked** in AppCore `engine.GoEngine` (Linux/desktop default) |
| wireguard-go (`golang.zx2c4.com/wireguard`) | MIT | **Linked** in AppCore `engine.WGEngine` (`FOCUSVPN_ENGINE=wireguard`) |
| Xray-core / amnezia-xray-core | MPL-2.0 | **Subprocess only** — JSON from `clients/shared/xray`; never linked / never forked |
| amneziawg-tools (awg/awg-quick) | GPL-2.0 | **Subprocess only** on nodes / opt-in `FOCUSVPN_ENGINE=awg` |
| Bouncy Castle `bcprov-jdk18on` | Bouncy Castle Licence | Android X25519 keygen only (`X25519Keys`) |
| amneziawg-android | Apache-2.0 | Planned VpnService dataplane (JNI follow-up after P3-M3b) |

## Not included (explicitly rejected for product binary)

| Component | License | Reason |
|---|---|---|
| amnezia-client | GPL-3.0 | No fork / no link (ADR-003) |
| sing-box | GPL-3.0 | Not linked |

Update this file when adding Go modules or embedding engines. CI license gate (Phase 3+)
must fail PRs that introduce GPL/AGPL into linked binaries.
