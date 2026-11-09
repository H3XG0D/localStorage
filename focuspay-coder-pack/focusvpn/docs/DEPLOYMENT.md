---
type: spec
tags: [deployment, spec]
status: active
updated: 2026-08-10
---

# FocusVPN — Деплоймент

> PHASE 1 · без кода. Основа: `docs/ARCHITECTURE.md` §4–§5; `docs/SECURITY.md`.

---

## 1. Локальный dev-окружение

Docker Compose (`infra/compose/docker-compose.yml`) поднимает **весь минимальный стек**:

```
Services:
  postgres       postgres:16            → :5432
  redis          redis:7-alpine         → :6379
  backend        backend (Go)           → :8080
  node-agent     node-agent (Go) + движки → — (регистрируется как нода)
```

Бутстрап локально (один скрипт `scripts/bootstrap-dev.sh`):
1. `docker compose up -d postgres redis`.
2. Применить миграции (PHASE 2) → seed: планы (`free/pro/business`), admin-пользователь.
3. `docker compose up -d backend`.
4. Зарегистрировать тестовую ноду через admin API (получить `node_token`), запустить
   `node-agent` с этим токеном → агент пройдёт register (mTLS) и начнёт poll состояния.
5. Локальный клиент (Phase 2: **CLI harness** `clients/cli`; Phase 3+: UI) подключается к
   `api.focusvpn.local` / `:8080`.

Dev-особенности:
- TLS для клиентов — опционально (за само-подписанным cert для локальных тестов), но проверка
  подписи конфига работает всегда.
- mTLS между CP и агентом — тестовый CA генерируется скриптом, доверенный на обеих сторонах
  (файлы в `secrets/`, не в git).
- Agent long-poll: 30 s / re-poll ≤5 s (ADR-004).
- Локально одна нода = один контейнер с `awg` (+ опц. `wg`, `xray`); движки ставить в образ на PHASE 2.

---

## 2. Прод-топология (без Kubernetes)

На PHASE 1 прод — **управляемые VM / bare-metal**, без оркестратора:

```
                    ┌──────────────────────────────┐
                    │  Backend VM (control plane)  │
                    │  systemd: focusvpn-backend      │
                    │  systemd: focusvpn-migrate      │
                    │  + managed Postgres + Redis  │
                    └──────────────┬───────────────┘
                                   │ mTLS (порт для агентов)
     ┌─────────────────────────────┼─────────────────────────┐
     │                             │                         │
┌────▼─────┐                ┌──────▼─────┐           ┌───────▼──────┐
│ VPN Node │                │ VPN Node   │           │ VPN Node     │
│ DE-01    │                │ NL-01      │           │ US-01        │
│ agent+3  │                │ agent+3    │           │ agent+3      │
│ engines  │                │ engines    │           │ engines      │
└──────────┘                └────────────┘           └──────────────┘
```

### Backend (control plane)
- 1–3 реплики Go-процесса за L7-балансировщиком (nginx/caddy/alb) + TLS-терминация.
- Managed **PostgreSQL 16** (backups, PITR), managed **Redis 7** (или 1 выделенная VM).
- Миграции: run-once job (`focusvpn-migrate`) перед деплоем новой версии; версия миграций в коде.
- Секреты: Secret Manager (Vault / AWS Secrets Manager) — KEK, JWT-ключ, config_signing_key,
  mTLS CA. Ничего в env-файлах репозитория.

### VPN Node
- Подготовка: скрипт `scripts/provision-node.sh` (вручную или Ansible позже):
  1. установка системных пакетов: `wireguard-tools`, `amneziawg-tools`, модуль
     `amneziawg-linux-kernel-module` (опц.), `xray` (бандл/бинарник);
  2. установка `node-agent` как systemd-сервиса;
  3. конфиг агента: `control_plane` URL, `node_token` (одноразовый), путь к CA.
- Регистрация: агент при первом старте вызывает `POST /v1/agent/register` с node_token + CSR →
  получает mTLS-сертификат и `node_id`; токен одноразовый (сжигается).
- Сетевые правила: наружу только `UDP 51820 (awg)`, `UDP 51821 (wg)`, `TCP 443 (reality)`,
  `TCP <admin-port> (mTLS к CP)`. Остальное — deny by default. (Подробности SECURITY.md §8.)

### Фаервол/инфраструктура
- Клиентские эндпоинты: Cloudflare/TCP/UDP-проксирование для REALITY по необходимости.
- DDoS-защита на уровне сети (anti-DDoS у хостинга) — опционально, для AmneziaWG портов.

---

## 2.5. Node Agent — запуск (M4)

### Требования к среде
- `awg` и `awg-quick` установлены (AmneziaWG tools, GPL; запускаются subprocess)
- `CAP_NET_ADMIN` или `root` (для управления сетевыми интерфейсами)
- Сетевой доступ к CP agent listener (`:8443`, mTLS)

### Первый запуск (регистрация)

```bash
# 1. Сгенерировать одноразовый token (на машине с доступом к БД):
make seed-agent-token DB_URL=postgres://...
# Выводит: AGENT_NODE_TOKEN=<hex>

# 2. Запустить агент с токеном:
AGENT_NODE_ID=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa \
AGENT_CP_URL=https://cp.focusvpn.internal:8443 \
AGENT_NODE_TOKEN=<hex> \
go run ./node-agent/cmd/agent

# Агент:
# - Генерирует ECDSA P-256 ключ + CSR
# - POST /v1/agent/register → получает cert + CA cert
# - Сохраняет secrets/agent.{crt,key}, secrets/ca.crt
# - Входит в основной цикл: long-poll → awg apply → telemetry
```

### Последующие запуски

```bash
# Токен больше не нужен — cert на диске
AGENT_NODE_ID=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa \
AGENT_CP_URL=https://cp.focusvpn.internal:8443 \
go run ./node-agent/cmd/agent
```

### Переменные окружения агента

| Переменная | По умолчанию | Описание |
|---|---|---|
| `AGENT_NODE_ID` | обязательно | UUID ноды в CP |
| `AGENT_CP_URL` | обязательно | URL agent listener |
| `AGENT_NODE_TOKEN` | — | Одноразовый token (только первый старт) |
| `AGENT_CERT_FILE` | `secrets/agent.crt` | mTLS сертификат |
| `AGENT_KEY_FILE` | `secrets/agent.key` | mTLS ключ |
| `AGENT_CA_FILE` | `secrets/ca.crt` | CA сертификат CP |
| `AGENT_INTERFACE` | `awg0` | Имя AmneziaWG интерфейса |
| `AGENT_POLL_INTERVAL` | `5s` | Задержка после получения state |
| `AGENT_TELEMETRY_INTERVAL` | `15s` | Интервал heartbeat |

### CP переменные (M4)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `FOCUSVPN_AGENT_ADDR` | `:8443` | Agent mTLS listener |
| `FOCUSVPN_AGENT_CA_CERT` | `secrets/ca.crt` | CA cert для mTLS |
| `FOCUSVPN_AGENT_CA_KEY` | `secrets/ca.key` | CA key для mTLS |
| `FOCUSVPN_ALLOCATION_AUTO_ACTIVE` | `false` | DEV stub A1; в prod = false |

---

## 2.6. Launch-L1 — sideload (Android / Windows / Linux)

Minimal production for closed testers (no stores, no Tor, no Mac). Canonical topology: [[plans/Infra-TwoHost]].

1. **Biz host** (already live): `focuspay` **153.80.249.77** — FocusPay + FocusVPN CP (own Postgres) + bots/landing.
2. **Traffic node** (order): FR dedic PAR-SM5038 — awg + node-agent only; UDP 51820; mTLS out to CP :8443.
3. Human wizard: `./scripts/wizard-launch-l1.sh` → `.env.launch` (gitignored).
4. Provision: `scripts/provision-cp.sh` on biz, `scripts/provision-node.sh` on FR + `infra/launch/`.
5. Client releases: `FOCUSVPN_API_BASE=https://api.<domain> make release-all` → `dist/`.
6. Optional static site: `websites/landing/`.

Plan: [[plans/Launch-L1]] · [[plans/Infra-TwoHost]]. Check: `make launch-check`.

---

## 3. CI/CD (эскиз)

```
GitHub Actions (monorepo):
  backend:  lint → test → build → push image → migrate → deploy backend
  agent:    lint → test → build → push agent image/package
  docs:     проверка ссылок, генерация (при желании)
  licenses: check THIRD_PARTY_LICENSES + NOTICE в PR, затрагивающих движки
```

- Гейт для клиентских релизов: обновление пин-версий движков + лицензионная проверка
  (см. CLIENT_ARCHITECTURE.md §8).
- Deploy ноды: SSH/Ansible → `systemctl restart focusvpn-agent` + применение нового состояния.

---

## 4. Стратегия обновления и откат

- Backend: rolling deploy (несколько реплик) → health-check → switch.
- Миграции: forward-only в рамках релиза; перед откатом — проверка совместимости старого кода
  (миграции не удаляют данные без reverse-migration plan).
- Node Agent: обновление пакета + restart; на время restart активные VPN-туннели, обслуживаемые
  процессами движков, продолжают работать, если не тронуты интерфейсы (агент — только контроллер).
- Откат конфигурации ноды: агент хранит предыдущую версию состояния, `stale_version` (409)
  заставляет пересинхронизироваться с CP.

---

## 5. Вопросы масштабирования (задел, НЕ на PHASE 1)

- Kubernetes — отдельный ADR, когда понадобится горизонтальное управление нодами/провайдерами.
- Terraform/Ansible для автономного провижининга нод — позже.
- Обфускация/multi-hop — через конфиг без изменения кода ядер.

## Связано

- [[ARCHITECTURE]] · [[SECURITY]] · [[DATABASE]] · [[MOC/Architecture]] · [[CURRENT_TASK]]
