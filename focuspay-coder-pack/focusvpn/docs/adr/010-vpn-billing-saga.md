---
type: adr
tags: [adr, billing, ecosystem, focuspay]
status: accepted
updated: 2026-10-07
---

# ADR-010: Покупка VPN — сага FocusPay → CP с идемпотентным grant

- **Статус:** Принято (07.10.2026)
- **Дата:** 07.10.2026
- **Основа:** [[007-ecosystem-billing-federation]] (общий баланс FocusPay). Заменяет поток
  `quote → hold → extend → confirm` из [[plans/E1-vpn-bot]].

## Контекст

В E1 бот сам вёл покупку: hold в FocusPay, `extend` в CP, confirm. Цена была в env бота
(`VPN_WEEK_RUB`), учёта покупок не было, сверки не было. Падение между шагами давало либо
списанные деньги без дней, либо дни без денег. Двойное нажатие продлевало дважды. Подписка без
`ends_at > now` всё равно давала доступ (неявный бесплатный доступ).

## Решение

**Кто чем владеет.** FocusPay — деньги, цены, тарифы, гейты, триал и учёт покупок
(`vpn_purchases`). CP — только дни подписки и журнал выдач (`billing_events`). Бот денег не
считает: зовёт `POST /api/internal/vpn/purchase` / `trial`.

**Сага покупки (FocusPay, `vpn_billing.py`):**

1. В одной транзакции: advisory lock на пользователя → гейт по числу депозитов → запись
   `vpn_purchases(status=held)` с уникальным `idem_key` → hold на общем балансе (`order_ref`).
2. `POST /v1/internal/billing/grant` в CP с `external_id = id покупки`.
3. Успех → `confirm` hold и `status=paid` (`paid_at` — момент признания выручки).
4. Окончательный отказ CP (4xx, кроме 401/403/408/429) → release hold, `status=released`.
   Сеть/5xx/таймаут → покупка остаётся `held`; `reconcile_loop` (каждые 60 с, строки старше
   120 с) переспрашивает CP (`GET …/grants/{id}`) и повторяет grant.

**Grant в CP** — одна транзакция под `pg_advisory_xact_lock('billing:'||user_id)`.
`billing_events.idempotency_key` (PK) = id покупки: повтор возвращает исходный результат и дни не
добавляет. Дни складываются: `ends_at = max(now, ends_at) + days`. Триал — один на пользователя
(уникальный индекс `kind='trial'`), поверх оплаченной подписки не меняет её статус и план.

**Доступ.** Нет живой подписки (`ends_at > now`) → `/servers`, `/connections` и GET конфига
отвечают 402. Планировщик помечает истёкшие подписки `expired`, затем `SyncVLESS` снимает
пользователя с нод.

**Тарифы и гейт** — в `app_settings.vpn_billing` FocusPay, правятся в админке `/x8/vpn`:
неделя / месяц / 3 месяца, триал (дни, вкл/выкл), `purchase_min_deposits` и
`trial.min_deposits` (по умолчанию 10 зачисленных депозитов). Оплата только с баланса FocusPay.

**Сверка.** `/api/admin/vpn/reconciliation` сравнивает `vpn_purchases` и выдачи CP за 30 дней:
`paid_without_grant`, `grant_without_payment`, `amount_or_days_mismatch`,
`granted_not_confirmed`, `pending`, `grant_unknown_to_focuspay`. Выручка VPN входит в PnL
(`finance_pnl.fetch_vpn_revenue`, только `kind=paid`, по `paid_at`).

## Последствия

**Плюсы:** двойное нажатие и повтор сети не списывают и не продлевают дважды; сбой посередине
доводится reconcile-циклом; цены меняются без деплоя; есть отчёт и сверка.

**Минусы:** hold может висеть до ответа CP (деньги заморожены, не потеряны); существующие
пользователи без живой подписки теряют доступ после деплоя CP (нужен триал или allowlist);
миграцию FocusPay `add_vpn_purchases.sql` применяют вручную.

**Отклонение от плана:** release только на окончательный 4xx, а не на любую ошибку CP — иначе
таймаут после успешного grant давал бы бесплатные дни.

## Альтернативы

- Бот ведёт сагу сам (как в E1) — отклонено: нет учёта и сверки, состояние теряется при рестарте.
- CP хранит цены и деньги — отклонено: деньги и гейты уже в FocusPay ([[007-ecosystem-billing-federation]]).
- Крипто-счёт на нехватку — убран: оплата только с баланса.

## Related

- [[plans/E4-billing]] · [[DECISIONS]] · [[MOC/Decisions]] · [[API]] §9.1 · [[ARCHITECTURE]]
