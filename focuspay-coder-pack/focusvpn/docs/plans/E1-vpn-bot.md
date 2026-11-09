---
type: plan
tags: [plan, ecosystem, billing, telegram]
status: active
updated: 2026-10-07
---

# E1 — FocusVPN Telegram bot + FocusPay wallet

**Status: implemented (MVP)** — ADR-007, FocusVPN internal billing, FocusPay vpn_wallet routes, `bots/focusvpn-tg`.

> **Заменено 07.10.2026:** поток покупки ниже (`quote/hold/confirm/release`, `extend`, крипто-счёт)
> заменён сагой FocusPay → `POST /v1/internal/billing/grant` — [[010-vpn-billing-saga]] · [[plans/E4-billing]].
> Старые маршруты FocusPay отвечают 410. Таблицы ниже — история.

Design / execution for ecosystem billing federation ([[007-ecosystem-billing-federation]]).

## Goal

Separate VPN Telegram bot: shared TG identity + shared ₽ balance with FocusPay; pay 300₽/week from cashback; shortfall → crypto invoice via FocusPay; extend FocusVPN subscription.

## Contracts

### FocusPay (`X-Internal-Token`)

| Method | Path | Body / notes |
|---|---|---|
| GET | `/api/internal/users/{telegram_id}` | `{exists, available_rub, username?}` ; auto-ensure user |
| POST | `/api/internal/vpn/quote` | `{telegram_id, product}` → price, available, shortfall |
| POST | `/api/internal/vpn/hold` | `{telegram_id, vpn_order_id, amount_rub}` |
| POST | `/api/internal/vpn/confirm` | `{vpn_order_id, note?}` hold→spend |
| POST | `/api/internal/vpn/release` | `{vpn_order_id}` |
| POST | `/api/internal/vpn/crypto-invoice` | `{telegram_id, vpn_order_id, amount_rub, asset}` |
| POST | `/api/internal/vpn/crypto-settle` | `{invoice_id}` → marks paid (ops/dev); caller then confirm+extend |

### FocusVPN (`X-Internal-Token`)

| Method | Path | Body / notes |
|---|---|---|
| POST | `/v1/internal/telegram/upsert` | `{telegram_id}` → `{user_id, telegram_id, created}` |
| POST | `/v1/internal/billing/extend` | `{telegram_id, days, idempotency_key}` → subscription |
| GET | `/v1/internal/billing/status?telegram_id=` | subscription status |

## Product defaults

- `vpn.week_rub = 300`, `days = 7`, plan code `week` (max_devices=3).
- Purchase flow: `quote → hold → extend → confirm`; on extend fail → `release`.

## Bot location

`bots/focusvpn-tg/` in FocusVPN monorepo (Python, python-telegram-bot).

## DoD

- ADR-007 + this plan + Integration note updated
- FocusVPN migration + internal APIs + tests
- FocusPay internal VPN wallet routes
- Bot: /start, balance, buy week, status
- Crypto shortfall invoice + settle path

## Связано

- [[007-ecosystem-billing-federation]] · [[CURRENT_TASK]] · [[DECISIONS]] · [[ROADMAP]]
