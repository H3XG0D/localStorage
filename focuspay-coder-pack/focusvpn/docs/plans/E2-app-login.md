---
type: plan
tags: [plan, android, telegram, billing]
status: active
updated: 2026-10-07
---

# E2 — Android Telegram login + 1 device + balance gate

**Status: implemented (MVP)** — `backend/internal/applogin`, Android dark UI, FocusPay `internal_vpn`, bot `vpnauth_` + pair code.

## Goal

Android-клиент: вход через Telegram (deep-link + код), тёмный UI, **1 устройство** на план `week`, покупка недели с баланса FocusPay только при **≥10 casino-пополнений** (настраиваемо).

## CP API

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/auth/telegram/start` | `{deep_link, wait_token}` |
| GET | `/v1/auth/telegram/wait?wait_token=` | `202 pending` → `200` tokens |
| POST | `/v1/auth/telegram/code` | `{code}` → tokens |
| POST | `/v1/internal/telegram/attach-login` | bot: `vpnauth_*` |
| POST | `/v1/internal/telegram/login-code` | bot: short code |

Migration: `000005_app_login` + `week.max_devices = 1`.

## FocusPay

Isolated router `internal_vpn.py` in FocusPay monorepo (`site/exchange-backend/routers/`) under `/api/internal/vpn/*`. Gate: `casino_deposit_credits` count, env `VPN_MIN_DEPOSITS`, `VPN_DEPOSIT_GATE_ALLOWLIST`.

## Verify

```bash
bash scripts/smoke-applogin.sh
make smoke-e1-full
make android-check
FOCUSVPN_E2E_REAL_TUNNEL=1 make smoke-e2e   # needs awg-quick + live node
```

## Связано

- [[008-telegram-app-login]] · [[007-ecosystem-billing-federation]] · [[E1-vpn-bot]] · [[CURRENT_TASK]]
