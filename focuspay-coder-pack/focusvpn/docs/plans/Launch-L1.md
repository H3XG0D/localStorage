---
type: plan
tags: [plan, launch, ops]
status: active
updated: 2026-08-12
---

# Launch-L1 — Sideload Android / Windows / Linux

> Horizon confirmed: **sideload 3 platforms + biz host + 1 traffic dedic**. Out of scope: GitHub CI green, Mac/iOS, Tor, Play/App Store.

## Goal

Closed testers can install FocusVPN on Android, Windows, or Linux and connect to a real Control Plane + one AmneziaWG node.

## Topology (accepted — see [[plans/Infra-TwoHost]])

```
User  --HTTPS-->  focuspay 153.80.249.77 (FocusPay live + FocusVPN CP + own Postgres)
                      |
                 mTLS :8443
                      v
              FR dedic PAR-SM5038 (awg + node-agent)   ← order; 300 Mbit unmetered
```

Biz host (**16c / 32GB**) already running FocusPay. Buy **only** the FR traffic node. FocusVPN Postgres isolated from `exchange_bot` (ADR-007).

## Deliverables

| ID | Item | Status |
|---|---|---|
| L1-docs | This plan + DEPLOYMENT Launch-L1 section | **done** |
| L1-wizard | `scripts/wizard-launch-l1.sh` (VPS / domain / secrets) | **done** |
| L1-provision | `scripts/provision-cp.sh` + `scripts/provision-node.sh` + `infra/launch/` | **done** |
| L1-release | `make release-{android,linux,windows}` with `FOCUSVPN_API_BASE` | **done** |
| L1-landing | Static download page under `websites/landing/` | **done** |
| L1-topology | [[plans/Infra-TwoHost]] + DECISIONS | **done** |
| L1-human | Order FR dedic, DNS, wizard, provision CP on biz + node on FR, distribute builds | **human** |

## Non-goals

- Tor / onion CP
- App Store / Google Play / Mac
- Multi-region fleet (failover code exists; ops later)
- Full Phase 5 billing UI (E1 TG bot may cover early pay)

## Human checklist

1. **Biz already up:** `ssh focuspay` (153.80.249.77) — FocusPay live; do not wipe
2. Order **FR traffic dedic** (PAR-SM5038) — checklist in [[plans/Infra-TwoHost]]
3. Point DNS `api.<domain>` → **153.80.249.77**
4. Run `./scripts/wizard-launch-l1.sh` → `.env.launch` (gitignored)
5. On biz: separate FocusVPN Postgres + `sudo bash scripts/provision-cp.sh`
6. On FR: awg tools + `sudo bash scripts/provision-node.sh`
7. `FOCUSVPN_API_BASE=https://api.<domain> make release-all`
8. Host artifacts on landing or send via Telegram

## Verify

```
make launch-check
curl -fsS https://api.<domain>/v1/health
# Client: login → connect (not dry-run) against prod API → FR endpoint
```

## Связано

- [[plans/Infra-TwoHost]] · [[DEPLOYMENT]] · [[CURRENT_TASK]] · [[ROADMAP]] · [[plans/P4]] · [[SECURITY]]
