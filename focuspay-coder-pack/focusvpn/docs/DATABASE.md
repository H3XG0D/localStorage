---
type: spec
tags: [database, spec]
status: active
updated: 2026-10-12
---

# FocusVPN — PostgreSQL модель

> Основа: `docs/ARCHITECTURE.md` §4, §5, §7, §8.
> Начиная с Phase 2 · M2 модель реализована версионированными миграциями (см. §0).

---

## 0. Миграции и локальная разработка (Phase 2 · M2)

- **Инструмент**: `golang-migrate` (MIT). SQL-файлы лежат в `backend/migrations/`
  (`NNNNNN_name.up.sql` / `.down.sql`) и **встроены** через `embed.FS`, поэтому применяются
  библиотечным раннером `backend/cmd/migrate` — внешний `migrate` CLI не требуется.
- **Свойства**: forward-only, версионированные, идемпотентные через инструмент, `down` где практично.
- **Реализованный охват (M2+M3)**: `users`, `plans`, `subscriptions`, `vpn_nodes`, `vpn_endpoints`,
  `devices`, `refresh_tokens`, **`vpn_allocations`**, **`vpn_configurations`** (`000002`).
  `audit_logs` / `telemetry_events` — later.
- **Store**: `pgx` напрямую, ручной параметризованный SQL (без ORM; `sqlc` отложен — см.
  DECISIONS.md). Все запросы параметризованы (защита от SQL-инъекций).

**Локальный dev-стек (Podman, без Docker):**
```
make dev-up            # podman compose: postgres:16 + redis:7 (см. infra/compose/)
make migrate           # применить миграции к dev-БД (DB_URL)
make seed              # детерминированный идемпотентный seed
make dev-logs          # логи стека
make dev-down          # остановить
make dev-reset         # снести volume'ы и поднять заново (чистая БД)
make migrate-down      # откатить миграции
```
Требование: активный rootless-сокет Podman (`systemctl --user enable --now podman.socket`),
т.к. compose-провайдер говорит по Docker API.

**Интеграционные тесты против реального PostgreSQL:**
```
make db-test-create    # создать disposable focusvpn_test
make test-integration  # go test ./... с FOCUSVPN_TEST_DATABASE_URL
```
Без `FOCUSVPN_TEST_DATABASE_URL` эти тесты пропускаются, так что обычный `go test ./...` зелёный офлайн.

**Поля, которые НИКОГДА не возвращаются API** (только внутри store-слоя):
`users.password_hash`, `refresh_tokens.token_hash`, `devices.device_token_hash`,
любые серверные приватные ключи/KEK/подписи. `GET /v1/me` и `/v1/devices` отдают только
user-safe DTO (см. `clients/shared/apitypes`).

---

## 1. Общие соглашения

- **PostgreSQL 16**. Один сервер БД, все таблицы в схеме `public` (на прод — отдельная схема `focusvpn`).
- **UUID PK** для всех сущностей (генерация на стороне приложения или `gen_random_uuid()`).
- **Timestamps**: `timestamptz`, значение по умолчанию `now()`.
- **Хэши/ключи**: `bytea` для бинарных ключей, `text` для base64-представлений где уместно.
- **Никаких приватных ключей клиентов в БД.**
- Пароли — только Argon2id-хэш; refresh/device токены — только хэш.
- Секреты конфигураций — зашифрованы (envelope encryption), см. SECURITY.md.

---

## 2. Таблицы

### 2.1 `users`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `email` | CITEXT | уникальный email (регистронезависимо) |
| `password_hash` | text | Argon2id хэш |
| `role` | text | `user` \| `admin` (RBAC) |
| `status` | text | `active` \| `suspended` \| `deleted` |
| `telegram_id` | bigint NULL | связка с FocusPay / VPN-ботом (E1, UNIQUE partial) |
| `last_login_at` | timestamptz | — |
| `created_at` / `updated_at` | timestamptz | — |

- **Индексы**: `UNIQUE(email)`; `idx_users_status(status)`; `UNIQUE(telegram_id) WHERE telegram_id IS NOT NULL`.
- **Триггер**: запрет обновления/удаления `email` через API (только через сервис auth).
- Миграция `000004_telegram_billing`: + `billing_events` (idempotency) + plan `week`.

### 2.2 `devices`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `user_id` | UUID | **FK → users.id** |
| `name` | text | имя устройства |
| `platform` | text | `android` \| `ios` \| `macos` \| `windows` \| `linux` \| `link` |
| `app_version` | text | версия приложения |
| `public_key` | bytea | публичный ключ (x25519, WG/AmneziaWG); **приватный ключ не хранится** |
| `device_token_hash` | text | хэш device token (BLAKE2b/SHA-256); токен выдаётся один раз |
| `status` | text | `active` \| `revoked` |
| `last_seen_at` | timestamptz | обновляется heartbeat'ом |
| `created_at` / `updated_at` / `revoked_at` | timestamptz | — |

- **Индексы**: `idx_devices_user(user_id)`; `UNIQUE(public_key) WHERE status='active'`
  (частичный — активные ключи уникальны); `UNIQUE(device_token_hash)`; `idx_devices_status(status)`.
- Лимит устройств проверяется на уровне приложения по плану подписки.
- Платформа `link` (миграция `000012`) — ключ ссылкой для Happ. Занимает место как телефон.
  Таблица `subscription_links`: `user_id`, `device_id`, `token_hash`, `token_enc` (сырой токен в конверте KEK,
  чтобы бот показал ту же ссылку), `revoked_at`. Один живой ключ на пользователя
  (`uq_sub_links_live_user`). См. [[013-happ-subscription-link]].

### 2.3 `plans`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `code` | text | `free` \| `pro` \| `business` \| `week` (уникальный) |
| `name` | text | отображаемое имя |
| `max_devices` | int | лимит устройств |
| `max_speed_mbps` | int \| null | лимит скорости |
| `max_traffic_gb` | bigint \| null | лимит трафика |
| `period_days` | int | длительность периода |
| `price_cents` | int | цена (задел под billing; провайдеры не проектируются) |
| `features` | jsonb | флаги (доступные протоколы, страны) |
| `created_at` / `updated_at` | timestamptz | — |

- **Индексы**: `UNIQUE(code)`.

### 2.4 `subscriptions`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `user_id` | UUID | **FK → users.id** |
| `plan_id` | UUID | **FK → plans.id** |
| `status` | text | `trialing` \| `active` \| `expired` \| `cancelled` |
| `starts_at` / `ends_at` | timestamptz | период |
| `auto_renew` | boolean | — |
| `provider` | text \| null | задел под billing-провайдера |
| `external_ref` | text \| null | ссылка на провайдера |
| `created_at` / `updated_at` | timestamptz | — |

- **Индексы**: `idx_subscriptions_user(user_id)`; `idx_subscriptions_status(status)`;
  `idx_subscriptions_ends(ends_at)` (для scheduler: кто истекает).
- Инвариант: у пользователя не более одной активной подписки (частичный unique или прикладная проверка).

### 2.5 `vpn_nodes`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `name` | text | `DE-01` (уникальный) |
| `country` | text | ISO-3166 alpha-2 (`DE`) |
| `region` | text | `eu-central` |
| `state` | text | `HEALTHY` \| `DEGRADED` \| `DRAINING` \| `OFFLINE` |
| `capacity` | int | макс. peers |
| `ip` | inet \| null | публичный адрес |
| `hostname` | text \| null | `de-01.focusvpn.example` |
| `os` / `kernel` / `agent_version` | text | инвентарь |
| `cert_serial` | text \| null | серийный номер mTLS-сертификата агента |
| `last_heartbeat_at` | timestamptz | — |
| `status_reason` | text \| null | почему нода не `HEALTHY` (миграция `000011`) |
| `health_fails` / `probe_fails` | int | подряд неудачные проверки агента и порта 443 |
| `created_at` / `updated_at` | timestamptz | — |

- **Индексы**: `UNIQUE(name)`; `idx_nodes_geo(country, region)`; `idx_nodes_state(state)`.

### 2.6 `vpn_endpoints`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `node_id` | UUID | **FK → vpn_nodes.id** |
| `protocol` | text | `amneziawg` \| `wireguard` \| `reality` |
| `port` | int | listen port |
| `state` | text | `HEALTHY` \| `DEGRADED` \| `DRAINING` \| `OFFLINE` |
| `public_key` | bytea \| null | публичный ключ сервера (WG/AmneziaWG); для `reality` — null |
| `obfuscation` | jsonb \| null | AmneziaWG: Jc (`junk_packet_count`/`junk_min_size`/`junk_max_size`) + S1–S4 (`init_packet_junk_size`…`transport_packet_junk_size`) + H1–H4 (`*_magic_header`) + optional I1–I5 (`special_junk_i*`); **обязательно** для `amneziawg`; **уникальный набор на ноду** |
| `reality` | jsonb \| null | Xray: `server_name`, `short_ids`, `port`-маскировка; **приватный ключ не хранится** |
| `subnet` | cidr | подсеть выдачи VPN-IP (напр., `10.200.0.0/24`) |
| `load` | float | 0..1 (последнее значение) |
| `peer_count` | int | текущее число peers |
| `last_probe_at` | timestamptz | — |
| `created_at` / `updated_at` | timestamptz | — |

- **Индексы**: `idx_endpoints_node(node_id)`; `UNIQUE(node_id, protocol, port)`;
  `idx_endpoints_state_proto(state, protocol)` (для NodeSelector).

### 2.7 `vpn_allocations`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `user_id` | UUID | **FK → users.id** (денормализация для быстрых запросов) |
| `device_id` | UUID | **FK → devices.id** |
| `endpoint_id` | UUID | **FK → vpn_endpoints.id** |
| `ip` | inet | выделенный VPN-IP |
| `peer_public_key` | bytea | снимок публичного ключа устройства на момент выдачи |
| `status` | text | `pending` \| `active` \| `revoked` \| `failed` |
| `created_at` / `updated_at` / `revoked_at` | timestamptz | — |

- **Индексы**: `idx_allocations_user(user_id)`; `idx_allocations_device(device_id)`;
  `UNIQUE(endpoint_id, ip) WHERE status IN ('pending','active')` (одна VIP-адресация);
  `UNIQUE(device_id, endpoint_id) WHERE status='active'` (не более одной активной аллокации
  устройства на эндпоинт).

### 2.8 `vpn_configurations`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `allocation_id` | UUID | **FK → vpn_allocations.id** |
| `device_id` | UUID | **FK → devices.id** |
| `version` | int | версия конфигурации (монотонно растёт) |
| `content_encrypted` | bytea | зашифрованные «части» конфига (без приватного ключа клиента) |
| `content_hash` | bytea | хэш открытого содержимого |
| `signature` | bytea | Ed25519-подпись CP (проверка клиентом) |
| `status` | text | `active` \| `revoked` |
| `rotated_at` | timestamptz | когда ключи/конфиг ротированы |
| `created_at` / `updated_at` | timestamptz | — |

- **Индексы**: `UNIQUE(allocation_id, version)`; `idx_configs_device(device_id)`;
  `idx_configs_status(status)`.
- При revocation: `status='revoked'`, активная версия инкрементится; fetch → 410.

---

## 3. Служебные таблицы

### 3.1 `refresh_tokens`

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | **PK** |
| `user_id` | UUID | **FK → users.id** |
| `family_id` | UUID | идентификатор семейства (для reuse detection) |
| `token_hash` | text | хэш refresh-токена |
| `device_id` | UUID \| null | FK → devices (опционально привязка к устройству) |
| `expires_at` | timestamptz | — |
| `revoked_at` | timestamptz \| null | — |
| `replaced_by` | UUID \| null | при ротации указывает на следующий токен |

- **Индексы**: `UNIQUE(token_hash)`; `idx_rt_user(user_id)`; `idx_rt_expires(expires_at)`.
- Политика: ротация = старый помечается `revoked` + `replaced_by` = новый; повторное использование
  отозванного → отзыв всего семейства.

### 3.2 `audit_logs` (append-only)

| Поле | Тип | Описание |
|---|---|---|
| `id` | bigserial | **PK** |
| `actor_type` | text | `user` \| `admin` \| `system` |
| `actor_id` | UUID \| null | — |
| `action` | text | `device.revoke`, `node.state.change`, `auth.login.fail`, … |
| `resource_type` / `resource_id` | text / UUID \| null | — |
| `ip` | inet \| null | — |
| `user_agent` | text \| null | — |
| `created_at` | timestamptz | — |

- **Индексы**: `idx_audit_actor(actor_id, created_at)`; `idx_audit_resource(resource_type, resource_id)`.

### 3.3 `telemetry_events` (короткий TTL)

| Поле | Тип | Описание |
|---|---|---|
| `id` | bigserial | **PK** |
| `device_id` | UUID | FK → devices |
| `endpoint_id` | UUID \| null | FK → vpn_endpoints |
| `app_version` / `platform` | text | — |
| `state` | text | connection state |
| `latency_ms` / `packet_loss` | float | — |
| `rx_bytes` / `tx_bytes` | bigint | — |
| `error_code` | text \| null | — |
| `created_at` | timestamptz | — |

- **Индексы**: `idx_te_created(created_at)` (для batch-очистки), `idx_te_endpoint(endpoint_id)`.
- **Ретенция**: сырые события — 24 ч (delete), агрегаты — в Prometheus/витрины до 30 дней.
  Очистка — scheduler.

---

## 4. Схема зависимостей

```
users 1──* devices 1──* vpn_allocations *──1 vpn_endpoints *──1 vpn_nodes
users 1──* subscriptions *──1 plans
vpn_allocations 1──1 vpn_configurations (версии 1──*)
users 1──* refresh_tokens
audit_logs, telemetry_events — независимые
```

---

## 5. Что НЕ хранится в БД

- Приватные ключи клиентов и приватные ключи серверов (серверные живут на нодах).
- Домены/хосты/URL посещённые пользователями, содержимое трафика, DNS-запросы.
- Refresh/device токены в открытом виде (только хэши).
- Секреты движков вне шифрованных полей.

## 6. Примечание о миграциях

Миграции — версионированные SQL (например, `migrate`/`tern`/`golang-migrate`) в `backend/migrations/`,
создаются на PHASE 2. Модель выше — источник истины для их написания.

## Связано

- [[ARCHITECTURE]] · [[API]] · [[SECURITY]] · [[CURRENT_TASK]] · [[DEPLOYMENT]] · [[MOC/Architecture]]
