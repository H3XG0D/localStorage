---
type: adr
tags: [adr, ecosystem, billing]
status: accepted
updated: 2026-08-11
---

# ADR-007: Ecosystem billing federation (FocusPay wallet + FocusVPN)

- **Статус:** Принято
- **Дата:** 11.08.2026
- **Основа:** [[Ecosystem/Integration-users-balance]] · [[plans/E1-vpn-bot]] · [[DECISIONS]]

## Контекст

FocusPay (`tg_bot_btc`) уже держит Telegram identity и единый ₽-ledger (cashback/referral/partner). FocusVPN нужен отдельный VPN Telegram-бот: оплата недели с общего баланса, общие рефералы. Сливать Postgres обменника и VPN-домена в один инстанс нельзя (FROZEN-финансы + разные миграции).

## Решение

1. **Федерация, не shared physical DB.** FocusPay Postgres = SoT для TG user + ₽ ledger + referrals. FocusVPN Postgres = SoT для VPN users/devices/subscriptions/configs.
2. **Связка:** `users.telegram_id BIGINT UNIQUE` в FocusVPN; `focuspay_user_id` концептуально = тот же Telegram id.
3. **Отдельный FocusVPN Telegram bot** вызывает:
   - FocusPay internal API — quote/hold/confirm/release ₽ и crypto-invoice на shortfall;
   - FocusVPN internal API — upsert by telegram_id + extend subscription (idempotent).
4. **Auth между сервисами:** shared `X-Internal-Token` (+ IP allowlist в FocusPay); mTLS можно добавить позже.
5. **Туннель** только в нативных клиентах; бот — аккаунт/оплата/ссылки.

## Последствия

**Плюсы:** общий кошелёк и рефы без ломки FROZEN-ядра; идемпотентный billing; VPN-схема независима.

**Минусы:** два Postgres и два internal API; согласованность hold→extend→confirm на стороне бота.

## Альтернативы

- Одна физическая БД — отклонено (риск для финансов обменника).
- Только API без telegram_id в FocusVPN — отклонено (нужен стабильный VPN user).
- Оплата только картой Payfast за VPN — отложено (FROZEN Payfast).

## Related

- [[DECISIONS]] · [[MOC/Decisions]] · [[plans/E1-vpn-bot]] · [[ARCHITECTURE]]
