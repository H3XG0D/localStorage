---
type: research
tags: [research, amneziawg]
status: active
updated: 2026-08-10
---

# AmneziaWG version pins (2026-08-10)

Sources:

- https://github.com/amnezia-vpn/amneziawg-go (tags via GitHub API, 2026-08-10)
- https://docs.amnezia.org/documentation/amnezia-wg/
- https://amnezia.org/blog/amneziawg-2-0-available-for-self-hosted

## Summary

Upstream `amneziawg-go` publishes classic AWG 1.x/1.5-style tags (`v0.2.19` and earlier) and a newer `v3.0.*` line (`v3.0.20260805` as of 2026-08-05). Amnezia product docs describe AmneziaWG 2.0/3.0 with richer obfuscation (dynamic headers, padding, protocol mimicry / CPS). Those generations are not drop-in compatible with legacy configs.

## Relevance to FocusVPN

Phase 2 MVP pins **`amneziawg-go` `v0.2.19`** and ConfigParts fields Jc/Jmin/Jmax (`junk_packet_count`, `junk_min_size`, `junk_max_size`), unique per node. Migrating to `v3.0.*` requires an ADR, schema expansion, and coordinated client/node upgrade (ROADMAP Phase 4).

## Связано

- [[OPEN_SOURCE]] · [[002-vpn-engine-strategy]] · [[MOC/Research]] · [[ROADMAP]]
