# Permission matrix — FocusPay Ops / Admin

Роли верхнего уровня: **ADMIN** (web admin) и **OPERATOR** (кабинет `/ops`).
У оператора дополнительно профильные роли `client` / `finance` (`operator_roles`).
Атомарные права — в `site/exchange-backend/permissions.py`.
Явные grant/revoke — таблица `operator_permission_grants`.

## Матрица по умолчанию

| Permission | OPERATOR `client` | OPERATOR `finance` | ADMIN |
|---|:---:|:---:|:---:|
| `templates.view` | ✅ | ✅ | ✅ |
| `templates.create` | ✅ | ❌ | ✅ |
| `templates.edit_own` | ✅ | ❌ | ✅ |
| `templates.edit_any` | ❌ | ❌ | ✅ |
| `templates.delete_own` | ✅ | ❌ | ✅ |
| `templates.delete_any` | ❌ | ❌ | ✅ |
| `templates.edit_system` | ❌ | ❌ | ✅ |
| `templates.manage_priority` | ✅ (свои / по ACL) | ❌ | ✅ |
| `external_deals.view` | ✅ | ✅ | ✅ |
| `external_deals.create` | ✅ | ❌ | ✅ |
| `external_deals.preview` | ✅ | ✅ | ✅ |
| `external_deals.confirm` | ✅ (свои / смена) | ❌ | ✅ |
| `external_deals.cancel` | ✅ (свои / смена) | ❌ | ✅ |
| `external_deals.confirm_any` | ❌* | ❌* | ✅ |
| `external_deals.cancel_any` | ❌* | ❌* | ✅ |
| `finance.payout` | ❌ | ✅ | ✅ |
| `finance.analytics` | ❌* | ❌* | ✅** |
| `casino.payout` | ❌* | ❌* | ✅ |
| `antispam.phrases` | ✅ | ✅ | ✅ |
| `orders.history` | ❌† | ❌† | ✅ |
| `payout.requisites` | ✅ | ✅ | ✅ |
| `payout.requisites.confirm` | ❌ | ❌‡ | ✅ |

\* только через `operator_permission_grants`  
\*\* ADMIN + привязка Telegram в `ADMIN_TELEGRAM_IDS` / `can_view_finance` (см. `finance_access.py`)  
† автоматически, если в `operator_role_profiles` грейд `senior` в любой роли; grants могут снять  
‡ автоматически только для **finance + грейд senior**; иначе явный grant. Не входит в default `finance`.

`casino.payout` не входит в default `finance`. Очередь `/ops/casino-payouts`, вкладка «Казино» в `/ops/client/:id`, `GET/POST /api/operator/casino/payouts*` и `GET /api/operator/users/{id}/casino*`.

`orders.history` — архив всех заявок в `/ops/history` (`GET /api/operator/orders/history`). Не даёт вход в `/x8` и не открывает смену статуса / выплату / «чистую».

`payout.requisites` — страница `/ops/payout-requisites` и постановка карты (client и finance). `payout.requisites.confirm` — кнопка «Включить», `POST /orders/{id}/payin_received` («Рубли получены» / подтверждение на карточке) и `POST /orders/{id}/payin_reject` (отклонить чек, без бана).

## Политика живых заявок (`/ops/orders`)

- `GET /api/operator/orders`: `orders` — все нетерминальные заявки (`не PAID/CANCELED/EXPIRED/FAILED`), не только «мои». `incoming` — без оператора (бейдж). Архив — `/ops/history` (`orders.history`).
- Видео (`POST /orders/{id}/video`) и проверка аккаунта (`POST /users/{id}/account-review`): оператор с **активной сменой**; владелец заявки **или** коллега на открытой смене. Claim не обязателен. Выплата по TX hash по-прежнему `finance.payout`.
- Отправка чека в Payfast (`POST /orders/{id}/send-receipt`): та же схема доступа, что у видео. Только BUY `AWAITING_CHECK` с PDF (не реквизитчик, не видео).
- Баланс клиента (`POST /users/{id}/balance`): `finance.payout` **или** грейд `senior` в любой роли (как у `orders.history`). Причина ≥ 3 символов, запись в `user_cashback_ledger` (`accrual` / `spend`). Без `finance.analytics` и прибыли в ответе.

## Политика шаблонов

- Scope: global (`operator_id IS NULL`) или personal.
- Автор: `created_by_operator_id`.
- `is_system=true` — только `templates.edit_system`.
- Optimistic lock: поле `version` (409 при конфликте).
- Аудит: `operator_chat_template_audit`.
- Уникальность `sort_order` среди активных global; обмен — `POST /api/operator/chat/templates/reorder`.

## Политика external deals

- Экран оператора: `/ops/external` (`external_deals.view`). Confirm / cancel / video / extend — те же `external_deals.confirm` / `cancel`, активная смена.
- **HMAC / кабинет** создают сделки с `operator_id IS NULL`. На смене их обрабатывает любой **client**-ops с базовым `external_deals.confirm` / `cancel` (не нужен `*_any`). Без активной смены create HMAC отвечает 503.
- `external_deals.confirm_any` / `cancel_any` — только для чужих **уже назначенных** сделок (другой `operator_id`), либо явный grant админом. В default `client`/`finance` их нет. Не выдавать `*_any` всем подряд: это обход object-ACL.
- Finance-ops по умолчанию **смотрит** очередь (`view`/`preview`), но не confirm/cancel HMAC — зачисление делает client на смене (или admin / явный grant).
- Нужна **активная смена** (`ended_at IS NULL`, берётся последняя по `started_at`) для мутаций; просмотр списка — по `view`.
- Confirm/cancel чужой назначенной: владелец **или** коллега на открытой смене **или** `*_any`.
- Финансовые поля (`reward_usdt`, `operator_earnings_rub`, …) strip без `finance.analytics`.
- Формулы расчёта / Payfast / HMAC **не** меняются этой матрицей.

## API

| Метод | Путь | Permission |
|---|---|---|
| GET/POST/PATCH/DELETE | `/api/operator/chat/templates` | `templates.*` |
| POST | `/api/operator/chat/templates/reorder` | `templates.manage_priority` + object ACL |
| GET/POST | `/api/operator/external/...` | `external_deals.*` |
| GET | `/api/admin/stats/pnl`, finance-overview | `finance.analytics` / finance viewer |
| GET | `/api/auth/operator/me`, `/admin/me` | возвращает `permissions`, `rbac_role` |
| GET | `/api/operator/orders/history`, `/history/{id}` | `orders.history` |
| GET/POST | `/api/operator/payout-requisites` | `payout.requisites` |
| POST | `/api/operator/payout-requisites/from-sell/{id}` | `payout.requisites` |
| POST | `/api/operator/payout-requisites/{id}/confirm` | `payout.requisites` + `payout.requisites.confirm` |
| POST | `/api/operator/orders/{id}/payin_received` | `payout.requisites.confirm` |
| POST | `/api/operator/orders/{id}/payin_reject` | `payout.requisites.confirm` |
| POST | `/api/operator/orders/{id}/video` | активная смена; владелец или коллега на смене |
| POST | `/api/operator/orders/{id}/send-receipt` | активная смена; владелец или коллега на смене |
| POST | `/api/operator/users/{id}/account-review` | активная смена |
| POST | `/api/operator/users/{id}/balance` | `finance.payout` или senior + активная смена |
| GET | `/api/operator/casino/payouts` | `casino.payout` |
| POST | `/api/operator/casino/payouts/{id}/claim\|payout\|paid\|reject` | `casino.payout` |
| GET | `/api/operator/users/{id}/casino`, `/casino/history` | `casino.payout` |
| GET | `/api/admin/casino/players/{id}/profile`, `/history` | admin |
| GET/POST/DELETE | `/api/operator/ai/consent`, `/ai/privacy` | согласие Ops AI (версия) |
| GET/DELETE | `/api/admin/ai/audit*` | `ai.audit.view` / `ai.audit.delete` |
| GET/POST/DELETE | `/api/operator/antispam/phrases` | `antispam.phrases` |

Дополнительно: `ai.audit.view`, `ai.audit.delete`, `news.broadcast` — только ADMIN (или явный grant). См. `docs/PRIVACY_AI_NEWS.md`.

## Sticker AI (изолировано от Ops AI)

Права `sticker.*` **не** входят в default `client` / `finance`. Только ADMIN или явный `operator_permission_grants`.
См. `docs/sticker-ai-architecture.md`. Роутер **смонтирован** read-only + mutations за флагом `STICKER_AI_MUTATIONS_ENABLED` (по умолчанию false).

| Permission | OPERATOR default | ADMIN |
|---|:---:|:---:|
| `sticker.create` | ❌* | ✅ |
| `sticker.view_own` | ❌* | ✅ |
| `sticker.view_any` | ❌* | ✅ |
| `sticker.edit_own` | ❌* | ✅ |
| `sticker.submit_review` | ❌* | ✅ |
| `sticker.moderate` | ❌* | ✅ |
| `sticker.publish` | ❌* | ✅ |
| `sticker.audit.view` | ❌* | ✅ |

\* только через `operator_permission_grants`

API (mounted, feature-flagged):

| Метод | Путь | Когда |
|---|---|---|
| GET | `/api/admin/sticker-ai/health` | всегда для admin; `enabled` / `mutations` / `observation_reasons` (без секретов) |
| GET | `/api/admin/sticker-ai/tasks` | только если enabled + `sticker.view_*` |
| GET | `/api/admin/sticker-ai/tasks/{id}` | только если enabled + object ACL |
| GET | `/api/admin/sticker-ai/audit` | enabled + `sticker.audit.view` |
| POST | `/api/admin/sticker-ai/tasks` | mutations + `sticker.create` |
| POST | `.../generate` | mutations + `sticker.edit_own` |
| POST | `.../edit` | mutations + `sticker.edit_own` |
| POST | `.../submit-review` | mutations + `sticker.submit_review` |
| POST | `.../approve` / `.../reject` | mutations + `sticker.moderate` |
| POST | `.../publish` | mutations + `sticker.publish` (без approve → 409) |

UI: `/x8/sticker-ai`. Мутации по умолчанию **закрыты** (`STICKER_AI_MUTATIONS_ENABLED=false`).

UI скрывает кнопки по `permissions`, но источник истины — сервер.
