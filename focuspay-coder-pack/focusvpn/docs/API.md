---
type: spec
tags: [api, spec]
status: active
updated: 2026-10-12
---

# FocusVPN — REST API спецификация

> PHASE 1 · спецификация, без кода. Основа: `docs/ARCHITECTURE.md` §4, §6, §8, §9.

---

## 1. Соглашения

- **Base URL**: `https://api.focusvpn.example` (dev: `http://localhost:8080`).
- **Формат**: JSON, `Content-Type: application/json`.
- **Версионирование**: в пути `/v1`.
- **Request ID**: каждый ответ содержит `X-Request-Id` (idempotency/дебаг).
- **Аутентификация**: три типа креденциалов:
  - **Access token** — JWT, короткоживущий (~15 мин), заголовок `Authorization: Bearer <jwt>`;
  - **Refresh token** — opaque, выданный на login/register/refresh, с ротацией;
  - **Device token** — opaque (32 байта), выдаётся один раз при регистрации устройства, заголовок
    `X-Device-Token: <token>`; нужен для device-scoped операций (`/v1/configurations/:id`, `/v1/heartbeat`).
- **Ошибки** — единый конверт:

```json
{ "error": { "code": "email_already_exists", "message": "…", "request_id": "…" } }
```

- **Коды ошибок** (общие): `invalid_token`, `expired_token`, `rate_limited`, `validation_error`,
  `not_found`, `forbidden`, `gone`, `subscription_expired`, `too_many_devices`, `node_unavailable`.

---

## 2. Auth

### POST /v1/auth/register
Аутентификация: нет (public). Rate limit: по IP.

Request:
```json
{ "email": "user@example.com", "password": "••••••••" }
```
Response `201 Created`:
```json
{
  "user": { "id": "uuid", "email": "user@example.com", "role": "user" },
  "tokens": { "access_token": "jwt", "refresh_token": "opaque", "expires_in": 900 }
}
```
Ошибки: `validation_error` (email/пароль), `email_already_exists` (409), `rate_limited` (429).

### POST /v1/auth/login
Аутентификация: нет (public). Rate limit: по IP + по аккаунту (brute-force защита).

Request: `{ "email": "…", "password": "…" }`
Response `200`: профиль + `tokens` (см. выше).
Ошибки: `invalid_credentials` (401), `rate_limited` (429, с задержкой), `account_locked` (423).

### POST /v1/auth/refresh
Аутентификация: refresh token в `Authorization: Bearer <refresh>`.

Request: `{}` (токен в заголовке).
Response `200`:
```json
{ "access_token": "jwt", "refresh_token": "new_opaque", "expires_in": 900 }
```
Поведение: refresh token **ротируется**; при обнаружении повторного использования (reuse detection)
— вся «семья» refresh токенов отзывается. Ошибки: `invalid_token` (401), `expired_token` (401).

### POST /v1/auth/logout
Аутентификация: access token + refresh token.

Request: `{ "refresh_token": "opaque" }`
Response `204 No Content`. Отзывает семейство refresh токенов.

---

## 3. Пользователь

### GET /v1/me
Аутентификация: access token.
Response `200`: `{ "user": {…}, "subscription": { status, plan, ends_at, max_devices, devices_used } }`.
`max_devices` — места тарифа плюс не истёкшие доп. устройства.
Если активной подписки нет → `"subscription": null`. Возвращаются только user-safe поля
(никаких хэшей паролей/токенов/ключей).
Ошибки: `invalid_token`, `expired_token`.

---

## 4. Devices

### GET /v1/devices
Аутентификация: access token.
Response `200`:
```json
{ "devices": [ { "id": "uuid", "name": "iPhone", "platform": "ios",
                 "app_version": "1.0.0", "status": "active",
                 "last_seen_at": "…", "created_at": "…" } ] }
```
Приватные ключи/полные device token никогда не возвращаются.

### POST /v1/devices
Аутентификация: access token.
Request:
```json
{ "name": "iPhone", "platform": "ios", "app_version": "1.0.0", "public_key": "base64-x25519" }
```
Response `201 Created`:
```json
{ "device": { "id": "uuid", "name": "iPhone", "status": "active" },
  "device_token": "opaque-32-bytes" }
```
`device_token` выдаётся **один раз** (дальше хранится только хэш).
Лимит устройств = `max_devices` плана живой подписки плюс число не истёкших доп. мест
(`billing_events.kind = device` и `ends_at > now`). Без живой подписки доп. места лимит не
увеличивают: они снова считаются после продления. Если подписки нет — план `free` (fallback).
Проверка лимита атомарна (advisory-lock на юзера).
Ошибки: `validation_error`, `too_many_devices` (409, лимит плана), `conflict` (409, публичный ключ
уже зарегистрирован активным устройством), `forbidden` (403, ключ неверной длины/кодировки — не 32 байта x25519).

### DELETE /v1/devices/:id
Аутентификация: access token (владелец). Permissions: только свои устройства (или admin).
Response `204 No Content`. Отзывает device, все allocations, снимает peers с нод.
Ошибки: `not_found` (404), `forbidden` (403).

### POST /v1/devices/:id/rotate-key
Аутентификация: access token (владелец) + device token в `X-Device-Token`.
Request: `{ "public_key": "new-base64-x25519" }`
Response `200`: `{ "device": { "id": "…" }, "config_version_bump": true }`
Обновляет публичный ключ на всех активных эндпоинтах устройства.
Ошибки: `invalid_token`, `not_found`, `forbidden`.

---

## 5. Servers / Endpoints

### GET /v1/servers
Аутентификация: access token.
Query: `?country=DE&protocol=amneziawg` (опционально).
Response `200`:
```json
{ "endpoints": [ { "id": "uuid", "node": "DE-01", "country": "DE", "region": "eu-central",
                   "protocol": "amneziawg", "score": 0.94,
                   "host": "de-01.focusvpn.example", "port": 51820 } ] }
```
`host` и `port` — публичный адрес ноды, чтобы клиент замерил пинг до подключения.
Старые клиенты эти поля игнорируют.
Ошибки: `subscription_expired` (402), `forbidden`.

---

## 6. Connections

### POST /v1/connections
Аутентификация: access token.
Request:
```json
{ "device_id": "uuid", "protocol": "amneziawg",
  "country": "DE",            // опционально
  "region": "eu-central",     // опционально
  "preferred_node": "DE-01" } // опционально; `selected_node` — UI-алиас
```
Поведение: NodeSelector (см. ARCHITECTURE.md §9) выбирает эндпоинт, выдаёт VPN-IP, публикует
состояние агенту, возвращает упорядоченный список кандидатов (top-3) для failover.
Response `201 Created`:
```json
{ "connection": { "id": "uuid", "status": "provisioning" },
  "candidates": [ { "endpoint": { "id": "uuid", "host": "de-01.focusvpn.example",
                    "port": 51820, "protocol": "amneziawg" },
                    "node": "DE-01", "score": 0.94 } ],
  "config_id": "uuid", "config_version": 1 }
```
Ошибки: `device_not_found`, `node_unavailable` (503, нет HEALTHY/DEGRADED-кандидатов),
`subscription_expired` (402), `too_many_devices` (409 — телефон не входит в самые старые места;
уже открытый туннель отзывается), `too_many_allocations` (409).

При сбое `VPNEngine.Start` клиент (AppCore) обходит `candidates` с exponential backoff и может
запросить свежий `POST /v1/connections` (ARCHITECTURE §10.3).

### DELETE /v1/connections/:id
Аутентификация: access token (владелец).
Response `204 No Content`. Закрывает сессию, освобождает IP, снимает peer (при желании).
Ошибки: `not_found`, `forbidden`.

---

## 7. Configurations

### GET /v1/configurations/:id
Аутентификация: device token (`X-Device-Token`), устройство должно владеть конфигурацией.
Response `200`:
```json
{ "config_version": 1,
  "signature": "ed25519-base64",
  "parts": {
    "interface": { "address": "10.200.0.10/32", "dns": ["10.200.0.1"], "mtu": 1420 },
    "peer": { "server_public_key": "base64", "endpoint": "de-01.focusvpn.example:51820",
              "allowed_ips": ["0.0.0.0/0", "::/0"] },
    "protocol": { "name": "amneziawg", "obfuscation": {
                  "junk_packet_count": 4, "junk_min_size": 40, "junk_max_size": 70,
                  "init_packet_junk_size": 15, "response_packet_junk_size": 20,
                  "cookie_reply_junk_size": 10, "transport_packet_junk_size": 5,
                  "init_packet_magic_header": "100-110",
                  "response_packet_magic_header": "200-210",
                  "underload_packet_magic_header": "300-310",
                  "transport_packet_magic_header": "400-410",
                  "special_junk_i1": "<b 0xde01>" } },
    "xray": null
  } }
```
**Приватный ключ клиента не передаётся никогда.** Клиент вставляет его локально.
`obfuscation` для AmneziaWG **обязателен**: Jc/Jmin/Jmax + S1–S4 + H1–H4 (I1–I5 optional CPS);
значения **уникальны на ноду** (не шарить один fingerprint на весь флот). Pin `amneziawg-go` v0.2.19.
REALITY/`xray` — Phase 4.
Ошибки: `invalid_token`, `not_found` (404), `gone` (410 — конфиг отозван, версия устарела),
`subscription_expired` (402).

---

## 8. Heartbeat / telemetry

### POST /v1/heartbeat
Аутентификация: device token.
Request (минимальная телеметрия, см. ARCHITECTURE.md §11):
```json
{ "device_id": "uuid", "connection_id": "uuid",
  "app_version": "1.0.0", "platform": "ios",
  "state": "connected", "endpoint_id": "uuid",
  "latency_ms": 42, "packet_loss": 0.01,
  "rx_bytes": 1024, "tx_bytes": 2048,
  "error_code": null }
```
Response `204 No Content`.
Поведение: обновляет `last_seen_at` устройства; сырые события TTL 24 ч, агрегаты 30 дней.
Ошибки: `invalid_token`, `gone` (устройство отозвано — клиент должен остановиться).

---

## 9. Subscription

### GET /v1/subscription
Аутентификация: access token.
Response `200`:
```json
{ "status": "active", "plan": "pro", "max_devices": 5, "devices_used": 2,
  "starts_at": "…", "ends_at": "…", "auto_renew": true }
```
Ошибки: `invalid_token`. (Публичный billing UI — позже; внутренний grant — §9.1 / E4.)

Без живой подписки (`ends_at > now`) `GET /v1/servers`, `POST /v1/connections` и GET конфига
отвечают `402 subscription_expired`.

### 9.1 Internal billing (FocusPay) — E4

Аутентификация: заголовок `X-Internal-Token` (= `FOCUSVPN_INTERNAL_TOKEN`). Не для клиентов.
Дни выдаёт только FocusPay (сага покупки, [[010-vpn-billing-saga]]). Бот VPN (`bots/focusvpn-tg`)
ходит в CP за устройствами, кодом входа в FocusVPN и ключом ссылкой для Happ; FocusPay — за списком истекающих подписок.

| Method | Path | Назначение |
|---|---|---|
| POST | `/v1/internal/telegram/upsert` | `{telegram_id}` → создать/найти user |
| POST | `/v1/internal/billing/grant` | `{external_id, telegram_id, kind: paid\|trial\|device, plan_code, days 1..365, amount_rub: "990.00"}` → выдача |
| GET | `/v1/internal/billing/grants/{external_id}` | выдача по id покупки FocusPay (404, если нет) |
| GET | `/v1/internal/billing/grants?since=RFC3339&limit=` | выдачи для сверки |
| GET | `/v1/internal/billing/status?telegram_id=` | статус подписки и мест: `max_devices`, `base_devices`, `extra_slots[{plan_code, ends_at}]` |
| GET | `/v1/internal/billing/ending?from=&to=&limit=` | подписки (`trialing`/`active`/`expired`) с `ends_at` в `[from, to)`, RFC3339; по умолчанию now−24ч … now+24ч → `{subscriptions:[{telegram_id, plan_code, status, ends_at}]}` |
| GET | `/v1/internal/telegram/devices?telegram_id=` | активные устройства → `{devices:[{id, name, platform, created_at, connected}]}`; `connected` = есть живая аллокация; неизвестный юзер → пустой список |
| POST | `/v1/internal/telegram/devices/revoke` | `{telegram_id, device_id}` → 204; отзывает устройство, аллокации и снимает юзера с нод; чужое/нет → 404 |
| POST | `/v1/internal/telegram/sub-link` | `{telegram_id, rotate?: bool}` → `{url, ends_at, device_id}`. Ключ ссылкой для Happ и похожих клиентов. Та же ссылка, пока ключ жив. `rotate: true` гасит старую ссылку и UUID. `402 no_subscription`, `409 too_many_devices` |
| GET | `/v1/sub/{token}` | публично, без JWT. Тело — base64 списка `vless://`, только WebSocket. Заголовки `profile-title`, `subscription-userinfo`, `profile-update-interval`, `support-url`, `Cache-Control: private, no-store`. Нет подписки — `402`. Неизвестный или отозванный токен — `404` |

`grant` идемпотентен по `external_id`: повтор возвращает исходный результат с `idempotent: true`
и дни не добавляет. Для `paid` и `trial` дни складываются от `max(now, ends_at)`. `kind: device`
не двигает подписку: нужна живая подписка, иначе `400`; `ends_at` в ответе — конец места
(`now + days`). Ответы: `400` невалидный запрос или нет живой подписки, `409 trial_used`
(второй триал). `extend` удалён.

FocusPay для бота VPN (`/api/internal/vpn/*`, тот же заголовок): `GET /status/{tg}` →
`{available_rub, exchanges:{have,need}, purchase_open, trusted, trial:{enabled,days,min_exchanges,used},
trial_available, plans:[…], device_addons:[{code,title,days,price_rub,per_day_rub,discount_pct}],
app_url, subscription:{active,plan,status,ends_at,days_left},
devices_limit:{max_devices, base_devices, extra_slots:[{plan_code, ends_at}]}}`;
отказ гейта — `403 {code: exchange_gate, need, have}`.
`POST /device {telegram_id, plan_code, idem_key}` покупает одно место (сага как у `/purchase`,
`vpn_purchases.kind = device`). Нет живой подписки — `400 {code: subscription_required}`, деньги
не держатся. Пустой `device_addons` в настройках значит, что сроки не продаются.
`GET /expiring` → `{reminders:[{telegram_id, kind: soon|ended, plan_code, status, ends_at}]}`
(soon — до конца ≤ 6 ч, ended — закончилась ≤ 24 ч назад, уже отправленные исключены);
`POST /notified {telegram_id, kind, ends_at}` → `{recorded}` — отметка до отправки, `false` = уже слали.

См. [[plans/E4-billing]] · [[plans/E1-vpn-bot]] · [[007-ecosystem-billing-federation]].

---

## 10. Admin API

Аутентификация: access token с ролью `admin` (RBAC). **2FA** — обязательна до прод-админки
(не gate Phase 2 MVP; см. SECURITY.md §5, §11). Действия пишутся в audit log.

### GET /v1/admin/nodes
Response `200`: `{ "nodes": [ { "id": "uuid", "name": "DE-01", "country": "DE",
"state": "HEALTHY", "endpoints": [ { "id": "…", "protocol": "amneziawg", "port": 51820,
"state": "HEALTHY", "load": 0.31 } ] } ] }`

### POST /v1/admin/nodes
Request: `{ "name": "DE-02", "country": "DE", "region": "eu-central", "capacity": 2000 }`
Response `201`: нода + `node_token` (одноразовый, для бутстрапа Node Agent).
Ошибки: `name_conflict` (409), `validation_error`.

### PATCH /v1/admin/nodes/:id
Request (частично): `{ "state": "DRAINING", "capacity": 2500 }`
Response `200`: обновлённая нода.

### DELETE /v1/admin/nodes/:id
Response `204`. Помечает ноду OFFLINE, отзывает агента (mTLS-сертификат), перенаправляет
клиентов failover'ом.

### (дополнительно) GET/PATCH /v1/admin/endpoints
Аналогично для эндпоинтов; `PATCH` позволяет менять `state`, `port`, параметры обфускации.

---

## 11. Agent API (внутренний, между Node Agent и Control Plane)

Не публичный. Только mTLS (клиентский сертификат агента). Base: `https://api.focusvpn.example/v1/agent`.

### POST /v1/agent/register
Request (внутренний, одноразовый node_token из `POST /v1/admin/nodes`):
`{ "node_token": "…", "hostname": "de-01", "endpoints": [ { "protocol": "amneziawg",
"port": 51820 } ], "csr": "base64-csr" }`
Response `201`: `{ "node_id": "uuid", "certificate": "base64", "ca": "base64" }`

### GET /v1/agent/state?since=:version
Response `200`:
```json
{ "version": 42,
  "state": { "peers": [ { "device_public_key": "base64", "ip": "10.200.0.10" } ],
             "xray": { "users": [ { "uuid": "…", "flow": "xtls-rprx-vision" } ],
                       "reality": { "server_name": "…", "short_ids": ["…"] } },
             "interfaces": { "amneziawg": { "listen_port": 51820,
                   "mtu": 1420, "obfuscation": { "junk_packet_count": 4,
                   "junk_min_size": 40, "junk_max_size": 70,
                   "init_packet_junk_size": 15, "response_packet_junk_size": 20,
                   "cookie_reply_junk_size": 10, "transport_packet_junk_size": 5,
                   "init_packet_magic_header": "100-110",
                   "response_packet_magic_header": "200-210",
                   "underload_packet_magic_header": "300-310",
                   "transport_packet_magic_header": "400-410" } } } } }
```

### POST /v1/agent/telemetry
Request: `{ "node_id": "uuid", "peer_count": 1, "online_users": 1, "rx_bytes": …, "tx_bytes": …,
"health": { "ok": false, "reason": "Xray не отвечает: …" },
"shares": [ { "allocation_id": "uuid", "ip_count": 5 } ] }`
`health` — локальная проверка ноды. Два `ok: false` подряд переводят её в `OFFLINE` и пишут `status_reason`.
`shares` — UUID, у которого больше трёх публичных адресов; CP ставит паузу на 15 минут.
Response `204`.

`GET /v1/internal/reports/summary` отдаёт у каждой ноды `status_reason` и массив `pauses`
(`reason`, `until`, `node_name`). Карточка `/x8/vpn` показывает эту строку.

Ошибки агентского API: `invalid_node`, `stale_version` (409 — конфликт состояния, нужен re-sync).

---

## 12. HTTP-статусы и rate limit

| Статус | Значение |
|---|---|
| 200/201/204 | успех |
| 400 | неверный запрос |
| 401 | нет/плохой токен |
| 402 | подписка истекла |
| 403 | нет прав (RBAC / чужой ресурс) |
| 404 | ресурс не найден |
| 409 | конфликт (email занят, слишком много устройств, конфликт версии состояния) |
| 410 | ресурс отозван (конфиг/устройство) |
| 422 | ошибка валидации |
| 423 | аккаунт заблокирован (brute force) |
| 429 | rate limit |
| 500/503 | внутренняя ошибка / недоступен узел |

Rate limiting (Redis), дефолты MVP (`docs/DECISIONS.md`):
- регистрация — **5**/час с IP;
- логин — **10**/мин с IP и **5**/мин с аккаунта;
- общие API — **120**/мин по access token.

Подробности — в `docs/SECURITY.md` §6.

## Связано

- [[ARCHITECTURE]] · [[SECURITY]] · [[DATABASE]] · [[006-auth-session]] · [[MOC/Architecture]]
