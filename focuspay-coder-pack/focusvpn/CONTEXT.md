# FocusVPN

Commercial VPN product: closed clients on five platforms, own Control Plane, own VPN nodes. Working directory may be named `focusvpn`; product name is **FocusVPN**.

## Language

**Control Plane (CP)**:
The single modular-monolith Go backend that owns users, devices, subscriptions, nodes, endpoints, allocations, and signed configuration parts.
_Avoid_: backend-as-microservices, API gateway (as the product name), server farm

**Node Agent**:
The Go process on each VPN node that long-polls the CP over mTLS and applies desired peer/interface state to local engines.
_Avoid_: sidecar, kubelet, ansible agent

**VPN Node**:
A host that terminates user tunnels; runs Node Agent plus engine tooling (`awg` / `wg` as separate processes).
_Avoid_: server (ambiguous), relay, exit node only

**Endpoint**:
A listen address + engine binding on a node (e.g. AmneziaWG on `:51820` with obfuscation params).
_Avoid_: server address, peer (peers are client-side), interface alone

**Device**:
A subscriber-owned client installation identified by its public key material and device record on the CP.
_Avoid_: client (the app), session, installation id alone

**ConfigPart**:
CP-signed public configuration fragment (server keys, IP, DNS, endpoint, obfuscation). Assembled on-device with the client private key.
_Avoid_: full config, profile dump, WireGuard conf as CP payload

**VPNEngine**:
Client-side abstraction that brings up a tunnel (AmneziaWG / WireGuard / Xray). Chosen on the device.
_Avoid_: protocol stack, tunnel manager (OS-level)

**AmneziaWG**:
Primary MVP tunnel engine (userspace `amneziawg-go`); node control via separate `awg` process. Obfuscation params Jc/Jmin/Jmax unique per node.
_Avoid_: AmneziaVPN client (GPL — not our client base), plain WireGuard

**Access JWT**:
Short-lived EdDSA (Ed25519) access token for user/API auth.
_Avoid_: HS256 JWT, opaque access token (unless explicitly refresh)

**Refresh token**:
Rotating long-lived credential with reuse detection; stored hashed server-side.
_Avoid_: session cookie, permanent API key

**Allocation**:
Assignment of a tunnel identity/IP (or VLESS UUID later) on an endpoint to a device.
_Avoid_: lease, IPAM record alone

**Subscription**:
Entitlement that gates plan limits (e.g. device count); at most one active per user in MVP.
_Avoid_: invoice, payment (billing is out of MVP scope)

**Subscription link**:
A stable HTTPS URL for Happ, INCY, v2rayNG and similar clients. Fetching it returns the current VLESS server list. It occupies one device seat (`platform` `link`). The Focus app does not use it.
_Avoid_: login code (that is how the Focus app signs in), a single pasted `vless://` line (the URL is the key; the lines are what the URL returns)

**Plan**:
Named entitlement tier (`free` / `pro` / `business`) defining limits.
_Avoid_: SKU, product (ambiguous with FocusVPN)

## Related brain

Canonical architecture and decisions live under `docs/` (Obsidian Project Brain). This file is glossary only — see `docs/agents/domain.md`.
