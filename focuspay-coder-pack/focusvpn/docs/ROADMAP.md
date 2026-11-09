---
type: hub
tags: [hub, roadmap]
status: active
updated: 2026-08-11
---

# FocusVPN — Roadmap

> PHASE 1 · план без кода. Основа: все документы PHASE 1.
> После context audit (10.08.2026): DoD Phase 2 и obfuscation MVP уточнены.

---

## 1. MVP vertical slice

Минимальный сквозной путь, который доказывает работу всей системы:

```
register → login → device registration → выбор 1 VPN node → configuration → VPN connection → disconnect
```

В Phase 2 «клиент» = **CLI / integration harness** (не UI Android/iOS). Полные клиенты — Phase 3.

| Шаг | Что нужно (из архитектуры) | Что можно отложить |
|---|---|---|
| register | auth module (POST /v1/auth/register, Argon2id, JWT EdDSA + refresh) | email-верификация, CAPTCHA |
| login | POST /v1/auth/login + refresh-ротация | 2FA (в т.ч. admin), усложнённый account lockout |
| device registration | devices module (POST /v1/devices, генерация device token) | ~~rotate-key~~ → **P4-M6 done** |
| выбор 1 VPN node | один HEALTHY-эндпоинт amneziawg (нода DE-01), vpn_nodes/vpn_endpoints | ~~NodeSelector~~ → **P4-M4 done** (DE/NL/US + failover helpers); latency Redis cache later |
| configuration | ConfigParts + Ed25519 + version; **AmneziaWG obfuscation Jc + H/S/I** (уникально на ноду) | REALITY/Xray конфиги, автоматическая ротация ключей |
| VPN connection | node-agent применяет peer через `awg`; CLI поднимает туннель / проверяет handshake; подпись конфига | multi-hop, MTU-тюнинг, metrics UI |
| disconnect | DELETE /v1/connections → снять peer, освободить IP | аналитика отключений, graceful draining |

**В MVP задействованы модули CP:** auth, users, devices, nodes (1 нода), endpoints (1),
allocations, configurations, health (heartbeat агента). Scheduler/admin/subscriptions — минимально
(заглушки: одна подписка активна, admin-эндпоинты для регистрации ноды).

---

## 2. Фазы

### Phase 1 — Architecture (завершена 10.08.2026)
- [x] OPEN_SOURCE.md (верифицировано)
- [x] ARCHITECTURE.md, API.md, DATABASE.md, SECURITY.md, CLIENT_ARCHITECTURE.md,
      DEPLOYMENT.md, ROADMAP.md, ADR (docs/adr/001–006)
- [x] Рабочий фреймворк: PROJECT.md, CURRENT_TASK.md, DECISIONS.md, TODO.md
- [x] Context audit: §14 risks, DoD CLI, DECISIONS Phase 2 defaults, CLAUDE.md, docs/research/
- [ ] Утверждение blueprint'а пользователем → старт **кода** Phase 2

### Phase 2 — Backend + Node Agent (MVP)
- [x] Инициализация git + `.gitignore` (секреты, ключи, env, `secrets/`)
- [x] Каркас monorepo: `backend/`, `clients/cli/`, `clients/shared/`, `scripts/` (`node-agent/`, `infra/compose/` — M2+)
- [~] Каркас backend (Go, modular monolith), REST API, middleware — **health + auth + request-id + rate limit готовы** (M1); остальные модули далее
- [ ] Модель БД + миграции (по DATABASE.md) — M2
- [~] Модули: **auth готов** (register/login/refresh/logout); users, devices, subscriptions (stub),
  nodes, endpoints, allocations, configurations, health, scheduler (stub), admin — M2+
- [x] Node Agent: mTLS, register, poll state, применение peer-таблиц через **`awg`**, telemetry — M4
- [x] Подпись конфигов (Ed25519), envelope encryption (dev: file KEK) — M3
- [x] 1 VPN node (DE-01, AmneziaWG + Jc/Jmin/Jmax) + локальный dev-стек (DEPLOYMENT.md §1) — M2/M4
- [x] CLI harness — register/login/refresh + tunnel-up/down/handshake — M5
- [x] Интеграционные тесты вертикального среза — `make smoke` + `make smoke-e2e` — M5
- [x] SECURITY.md §11 — пункты, помеченные **MVP** (не pre-prod) — M5

#### Прогресс по milestones
- **M1 (готов, 10.08.2026):** monorepo skeleton, HTTP CP (health+auth), Argon2id, EdDSA JWT,
  refresh rotation + reuse detection, rate limits, `clients/shared/apitypes`, CLI harness,
  unit+httptest тесты, `scripts/smoke.sh` (register→login→refresh→reuse-detected). Store: in-memory (test-only).
- **M2 (готов, 10.08.2026):** PostgreSQL store (`pgx`, no ORM) + миграции (`golang-migrate`, embed) +
  `infra/compose` (podman: postgres:16, redis:7) + детерминированный seed (plans, DE-01,
  amneziawg endpoint Jc=4/Jmin=40/Jmax=70) + `GET /v1/me` + devices module + no-fallback wiring.
  Тесты: unit/httptest (memory) + gated интеграционные против реального PostgreSQL
  (register/login/refresh/reuse/logout/`me`/уникальность/лимит устройств/персистентность-после-рестарта).
- **M3 (готов, 11.08.2026):** [[plans/M3]] implemented — `000002` allocations/configurations,
  `GET /v1/servers`, connections + IPAM, ConfigParts + Ed25519 + `MVN1` envelope, device-token
  config fetch, A1 DEV seed pubkey + `FOCUSVPN_ALLOCATION_AUTO_ACTIVE`, CLI servers/connect/config.
- **M4 (готов, 11.08.2026):** node-agent — migration `000003` (node_tokens/certs/state), internal CA,
  `POST /v1/agent/register` + long-poll `GET /v1/agent/state` + `POST /v1/agent/telemetry`,
  allocation pending→active via telemetry confirm, desired-state notify bus,
  `node-agent/` binary (mTLS, poller, awg applier, telemetry ticker), `make seed-agent-token`.
- **M5 (готов, 11.08.2026):** CLI `keygen`/`tunnel-up`/`tunnel-down`/`handshake`; awg `.conf` from
  ConfigParts (Jc/Jmin/Jmax); `make smoke-e2e`; SECURITY §11.1 MVP checklist.
  **Phase 2 vertical-slice DoD — выполнен** (реальный handshake на живой ноде — opt-in
  `FOCUSVPN_E2E_REAL_TUNNEL=1`).

### Phase 3 — Клиенты
- [x] **P3-M1:** AppCore (Go) + Linux product CLI + GTK stub + NOTICE — 11.08.2026 [[plans/P3]]
- [x] **P3-M2:** FocusPay-styled desktop GUI (Wails) + `make smoke-desktop` — 11.08.2026 [[plans/P3]]
- [x] **P3-M3:** Android scaffold (Compose + CP + VpnService stub) + `make android-check` — 11.08.2026 [[plans/P3]]
- [x] **P3-M3b:** Android config bridge (X25519 + TunnelConfig + VpnService Builder) — 11.08.2026 [[plans/P3]]
- [x] **P3-M3c:** Android AmneziaWG packet IO (UAPI + JNI `libwg-go.so`) — 11.08.2026 [[plans/P3]]
- [x] **P3-M4:** Apple scaffold (SwiftUI + NE Packet Tunnel stub) + `make apple-check` — 11.08.2026 [[plans/P3]]
- [x] **P3-M4b:** Apple config bridge (CryptoKit X25519 + TunnelConfig + NE settings) — 11.08.2026 [[plans/P3]]
- [x] **P3-M4c:** Apple AmneziaWG packet IO (UAPI + utun + WireGuardKitGo bridge) — 11.08.2026 [[plans/P3]]
- [x] **P3-M5:** Windows scaffold (FocusPay UI shell + wintun stub) + `make windows-check` — 11.08.2026 [[plans/P3]]
- [x] **P3-M5b:** Windows amneziawg-go bridge (`WintunEngine` → GoEngine) — 11.08.2026 [[plans/P3]]
- [x] **P3-M6:** Native go lib pipeline (android-native + apple wizard @ v0.2.19 wrappers) — 11.08.2026 [[plans/P3]]
- [x] Linux: Go-движок + CLI (M1) + desktop GUI path (M2); GTK stub остаётся справочным
- [~] AppCore / `clients/shared` контракты — **AppCore M1–M5 scaffolds done**; heartbeat/telemetry later
- [x] NOTICE.md + THIRD_PARTY_LICENSES.md (bootstrap); CI license gate — later

### Phase 4 — Движки и расширение
- [x] **P4-M1:** Embed amneziawg-go `v0.2.19` in AppCore + `make license-check` — 11.08.2026 [[plans/P4]]
- [x] **P4-M2:** WireGuard second engine (wireguard-go) — 11.08.2026 [[plans/P4]]
- [x] **P4-M3:** Xray/VLESS+REALITY (JSON + subprocess) + `make smoke-xray` — 11.08.2026 [[plans/P4]]
- [x] **P4-M4:** NodeSelector (country/region/load/score) + multi-node seed + client failover helpers — 11.08.2026 [[plans/P4]]
- [x] **P4-M4b:** AppCore failover E2E (candidate walk + backoff + CP refresh) — 11.08.2026 [[plans/P4]]
- [x] **P4-M5:** Scheduler config TTL re-issue (version bump + re-sign) — 11.08.2026 [[plans/P4]]
- [x] **P4-M6:** `POST /v1/devices/:id/rotate-key` — 11.08.2026 [[plans/P4]]
- [x] **P4-M7:** AWG 2.0/3.0 eval — stay on `v0.2.19` ([[2026-08-11-awg-2-3-eval]]) — 11.08.2026 [[plans/P4]]
- [x] **P4-M8:** H/S/I (+ optional I1–I5) on same pin — schema, seeds, Android/Apple — 11.08.2026 [[plans/P4]]
- [x] **P4-M9:** CI ABI cache (`android-native` workflow + pack/restore) — 11.08.2026 [[plans/P4]]
- [x] **P4-M10:** Container ABI build (`android-native-docker`) + GitHub CI wizard — 11.08.2026 [[plans/P4]]
- [x] **Launch-L1:** sideload path (provision scripts + landing); topology [[plans/Infra-TwoHost]] — 12.08.2026 [[plans/Launch-L1]]
- [ ] Human: rent VPS + DNS + run wizard / provision (ops)
- [ ] First CI green on remote / Apple WireGuardKitGo on Mac — explicit start
- [ ] Migrate to `amneziawg-go/v3` — only with ADR if DPI forces

### Phase 5 — Монетизация и масштаб
- [ ] Billing-провайдеры (Stripe/аналог), subscription полноценный
- [ ] Multi-юрисдикция, обфускация-профили
- [ ] Kubernetes/автономный деплой нод (если понадобится — отдельный ADR)
- [ ] Аналитика, панель админа; admin 2FA до прод-админки

---

## 3. Определение «готово» для каждой фазы

- **Phase 2**: vertical slice проходит end-to-end через **CLI harness** (или automated integration
  test) на одной AmneziaWG-ноде: register → device → config (с obfuscation) → peer applied →
  tunnel/handshake OK → disconnect. Модули CP/agent покрыты тестами. Выполнен checklist
  SECURITY.md §11 (**MVP**). Полноценные UI-клиенты **не** входят в Phase 2.
- **Phase 3**: клиенты Android + iOS/macOS + Windows + Linux собираются и подключаются к MVP-стеку;
  лицензии проверены (NOTICE / THIRD_PARTY_LICENSES).
- **Phase 4**: 3 движка, несколько нод, failover без прерывания сессии.

---

## 4. Критический путь и риски фазы 2

Критический путь: **backend (auth+devices) → configurations → node-agent (`awg`) → CLI connect**.

Риски: [ARCHITECTURE.md §14](ARCHITECTURE.md), [TODO.md](TODO.md) (раздел Risks),
резюме Phase 1 — [ARCHITECTURE.md §15](ARCHITECTURE.md).

## Связано

- [[Home]] · [[CURRENT_TASK]] · [[TODO]] · [[ARCHITECTURE]] · [[MOC/Execution]]
