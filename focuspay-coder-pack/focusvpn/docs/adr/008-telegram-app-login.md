---
type: adr
tags: [adr, auth, android, telegram]
status: accepted
updated: 2026-10-07
---

# ADR-008: Telegram login for Android (deep-link + pair code)

## Context

E1 создал Telegram-only users через internal upsert, но Android требовал email/password. Казино уже использует `cauth_` deep-link и Mini App initData; для VPN нужен отдельный бот и нативное приложение без Mini App.

## Decision

1. **Deep-link:** приложение вызывает `POST /v1/auth/telegram/start`, открывает `t.me/<bot>?start=vpnauth_<hex>`, бот вызывает `attach-login`, приложение поллит `GET /v1/auth/telegram/wait`.
2. **Pair code:** бот выдаёт 8-символьный код (`login-code`), приложение шлёт `POST /v1/auth/telegram/code`.
3. **Secrets:** только HMAC-хеши токенов/кодов в `app_login_requests` (TTL 5 мин, one-shot).
4. **Devices:** план `week` → `max_devices = 1`; UX отвязки в Account при `409 too_many_devices`.
5. **Balance gate:** FocusPay `/api/internal/vpn/*` — покупка с unified balance только если `casino_deposit_credits` ≥ `VPN_MIN_DEPOSITS` (default 10).

## Consequences

- JWT выдаётся через существующий `auth.IssueTokenBundle` (refresh rotation unchanged).
- FocusPay FROZEN: только новый `internal_vpn.py` + одна строка в `main.py`.
- Реальный handshake по-прежнему требует `awg-quick` + живая нода (см. [[TODO]] Risks).

## Связано

- [[006-auth-session]] · [[007-ecosystem-billing-federation]] · [[plans/E2-app-login]]
