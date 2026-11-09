---
type: research
tags: [research, opensource]
status: active
updated: 2026-08-10
---

# Open-source baseline (2026-08-10)

Source of truth: [`../OPEN_SOURCE.md`](../OPEN_SOURCE.md) (verified 10.08.2026 against upstream LICENSE files).

## Summary

FocusVPN embeds only MIT/Apache/MPL engines (amneziawg-go, wireguard-go, Xray/amnezia-libxray, wintun prebuilt). GPL tools (`awg`, `wg`, optional kernel module) run as separate processes on nodes. Forking AmneziaVPN client (GPL-3.0) and linking sing-box (GPL-3.0) are rejected.

## Relevance to FocusVPN

Any new dependency must be checked against OPEN_SOURCE.md strategy before Phase 2 implementation; add a research note here when the internet is used for a new component.

## Связано

- [[OPEN_SOURCE]] · [[MOC/Research]] · [[002-vpn-engine-strategy]]
