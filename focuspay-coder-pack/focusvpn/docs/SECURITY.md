---
type: spec
tags: [security, spec]
status: active
updated: 2026-08-10
---

# FocusVPN — Модель безопасности

> PHASE 1 · без кода. Основа: `docs/ARCHITECTURE.md` §5, §8; `docs/DATABASE.md`.

---

## 1. Trust boundaries

```
            Интернет
                │  TLS 1.3
        ┌───────▼────────┐        mTLS (клиентский серт.)
        │   Control Plane │◄─────────────────────┐
        └───────┬────────┘                      VPN NODE
                │  TLS 1.3 (device token)        (Node Agent)
        ┌───────▼────────┐                        │
        │   VPN CLIENT   │ ◄── VPN tunnel ────────┘
        └────────────────┘    (шифрованные пакеты)
```

Границы доверия:
1. **Client ↔ Control Plane** — доверие через TLS + JWT/device token; CP **не** доверяет клиенту
   по умолчанию (валидация всех входных данных, rate limit, RBAC).
2. **Node Agent ↔ Control Plane** — взаимное доверие через mTLS; CP видит ноду по `node_id`
   сертификата; нода принимает команды только с подлинного CP.
3. **Клиент ↔ Node** — VPN-туннель (AmneziaWG/WG/REALITY); шифрование пакетов — движками.
4. **Внутри ноды** — Node Agent с правами администратора; VPN-процессы изолированы (см. §8).

Ключевые принципы:
- **Никогда не храним приватные ключи клиентов** (см. ARCHITECTURE.md §8).
- **Минимум данных** (privacy by design) — нет истории трафика/доменов.
- **Всё шифруется в полёте** (TLS/mTLS) и **в покое** (секреты).
- **Всё важное пишется в audit log.**

---

## 2. Threat model

| # | Угроза | Вектор | Митигация |
|---|---|---|---|
| T1 | Перебор пароля | `/v1/auth/login` | Rate limit по IP+аккаунту, экспоненциальная задержка, блокировка (423) |
| T2 | Регистрация ботов | `/v1/auth/register` | Rate limit по IP, CAPTCHA (опц.), верификация email |
| T3 | Кража access JWT | перехват/фишинг | Короткий TTL (15 мин), TLS, ротация refresh |
| T4 | Кража refresh token | утечка | Opaque + хэш в БД, **reuse detection → отзыв всей семьи** |
| T5 | Кража device token | утечка/экспорт | Хэш в БД, выдача один раз, отзыв устройства, привязка к конфигу |
| T6 | Компрометация приватного ключа клиента | malware/фишинг | Ключ только в secure storage; ротация через rotate-key; отзыв устройства |
| T7 | Подмена ноды / MITM агента | DNS/IP спуфинг | mTLS, проверка CN/SAN, пиннинг CA |
| T8 | Несанкционированный admin | компрометация аккаунта | RBAC role=admin, 2FA для админов, allowlist email/IP, аудит |
| T9 | Сканирование нод / DoS | открытые UDP/TCP порты | Фильтрация трафика по peer-таблицам, лимиты, failover, DDoS-защита на уровне сети (опц.) |
| T10 | Компрометация БД | утечка данных | Шифрование секретов at rest (envelope), минимум PII, хэши токенов |
| T11 | Компрометация ноды | получение доступа к ноде | Серверные приватные ключи только на ноде, ротация, изоляция процессов, сетевые ACL |
| T12 | Социальная инженерия support | сброс доступа | Процедуры верификации, аудит действий support |
| T13 | Реиграция запросов | повторная отправка запросов | Подписи конфигов (Ed25519) + version, короткие TTL токенов |
| T14 | Side-channel в клиенте (лог доменов) | логирование в клиенте | Запрет логирования доменов/URL в клиенте (policy + review) |

---

## 3. Аутентификация и токены

### 3.1 Пароли
- **Argon2id** (рекомендованные параметры: m=64 MiB, t=3, p=4); соль на пользователя.
- Политика пароля: длина ≥ 10, без жёстких требований к наборам символов (длинные passphrase).
- Нет хранения открытых паролей; нет передачи пароля нигде, кроме TLS.

### 3.2 Токены
| Токен | Формат | TTL | Хранение | Использование |
|---|---|---|---|---|
| Access | JWT (**EdDSA / Ed25519**) | 15 мин | у клиента в памяти/secure | `Authorization: Bearer` |
| Refresh | opaque 256 bit | 30 дней (скользящий) | **хэш** в `refresh_tokens` | `/v1/auth/refresh` |
| Device | opaque 256 bit | бессрочный до отзыва | **хэш** в `devices` | `X-Device-Token` |

- JWT подписывается **только EdDSA (Ed25519)** — не HS256 (решение: `docs/DECISIONS.md`).
- JWT содержит: `sub` (user_id), `role`, `iat`, `exp`, `jti`. Пароль/секреты — никогда.
- Refresh rotation: каждый `refresh` выдаёт новый refresh и инвалидирует старый (`replaced_by`).
  Повторное использование отозванного → отзыв всего семейства (`family_id`).
- Подпись refresh-хэша: BLAKE2b/SHA-256 с ключом (HMAC), чтобы нельзя было валидировать оффлайн.

### 3.3 Device token
- Выдаётся один раз при `POST /v1/devices`, дальше хранится только хэш.
- Привязка к `device_id`; при отзыве устройства — хэш удаляется, конфиги инвалидируются.

---

## 4. Шифрование

### 4.1 В полёте (transport)
- Всё клиентское API — **TLS 1.3** (min 1.2), HTTP/2; HSTS; современные cipher-наборы.
- CP ↔ Agent — **mTLS** (клиентский сертификат от внутреннего CA, короткий срок 90 дней,
  автопродление, CRL).
- VPN-трафик шифруется движками (Curve25519/XChaCha20-Poly1305 или BoringSSL-наборы REALITY).

### 4.2 В покое (at rest)
- Пароли — Argon2id хэш.
- Refresh/device токены — HMAC-хэш.
- `vpn_configurations.content_encrypted` — **envelope encryption**:
  DEK (data encryption key) шифрует контент (AES-256-GCM); DEK шифруется KEK.
  DEK в БД — только зашифрованный блоб.
- **KEK / signing keys — окружения:**
  - **Dev / CI (Phase 2):** file-backed KEK и `config_signing_key` в каталоге `secrets/`
    (права 0600, в `.gitignore`, не коммитить). Допустим путь через env
    `FOCUSVPN_KEK_PATH` / `FOCUSVPN_CONFIG_SIGNING_KEY_PATH`.
  - **Prod:** KEK и signing key только в Secret Manager / HSM (Vault Transit, AWS KMS и т.п.).
    Переход на KMS — до открытия прод-админки (не блокирует MVP CLI).
- Серверные приватные ключи — только на нодах (файл с правами 0600, вне репозитория).

### 4.3 Подписи конфигов
- CP подписывает «части конфигурации» ключом **Ed25519** (`config_signing_key`).
- Клиент проверяет подпись и `config_version` перед установкой туннеля (защита от подмены
  при MITM/кэше).

---

## 5. RBAC и admin

- Роли: `user`, `admin`. Роль из JWT; смена роли требует отдельного флоу и аудита.
- Admin API — отдельная зона `/v1/admin/*`:
  - роль `admin` в access token;
  - allowlist админских email и/или IP;
  - каждое действие — в `audit_logs`;
  - **2FA (TOTP)** — **обязательна до открытия прод-админки**; в Phase 2 MVP (локальный
    admin seed) 2FA не является gate (см. §11 и `docs/TODO.md`).
- Никогда не используем admin-эндпоинты с user-токенами и наоборот.

---

## 6. Rate limiting и brute force

- **Redis** (sliding window). Дефолты MVP (см. `docs/DECISIONS.md`):
  - регистрация: **5** запросов/час с IP;
  - логин: **10**/мин с IP и **5**/мин с аккаунта; при превышении — экспоненциальная задержка,
    затем `account_locked` (423) с автоматической разблокировкой по таймеру;
  - общие API: **120**/мин на access token.
- Ответ `429` с `Retry-After`.
- Нагрузка на парольную проверку — через Argon2id, поэтому лимиты низкие.

---

## 7. Управление ключами и ротация

| Ключ | Где живёт | Ротация |
|---|---|---|
| Серверный ключ WG/AmneziaWG | нода | каждые 90 дней (окно перекрытия 24 ч) |
| REALITY-ключ Xray | нода | каждые 90 дней (перекрытие) |
| Клиентский ключ | устройство | по требованию / подозрению |
| mTLS-сертификат агента | нода | каждые 90 дней (автопродление) |
| `config_signing_key` (Ed25519) | CP: `secrets/` (dev) / KMS (prod) | 1 год, отзыв по компрометации |
| KEK (envelope) | CP: file (dev) / KMS (prod) | по политике KMS / ротация файла в dev |
| JWT Ed25519 signing key | CP: `secrets/` (dev) / KMS (prod) | при компрометации |
| CA ключ внутреннего CA | dev CA в `secrets/`; prod HSM | резервная копия в офлайне |

Любая компрометация ключа → экстренная ротация по runbook'у + аудит.

---

## 8. Безопасность ноды

- Node Agent запускается как отдельный сервис; минимальный setcap (`CAP_NET_ADMIN`) — без root
  у обычных процессов.
- VPN-движки: `awg`/`wg` — как отдельные процессы; Xray — отдельный процесс в контейнере/chroot
  (по возможности) с минимальными правами.
- Серверные приватные ключи: файлы 0600, владелец `agent`.
- Сетевые правила: только нужные порты наружу (UDP WG/AmneziaWG, TCP REALITY), остальное закрыто;
  fail2ban/аналоги для TCP-портов — опционально.
- Logging ноды: без содержимого трафика и доменов; только метаданные (rx/tx, ошибки).

---

## 9. Безопасность клиента

- Приватные ключи — в iOS **Keychain** (kSecAttrAccessibleAfterFirstUnlock), Android **Keystore**
  (non-exportable), Windows **DPAPI**, Linux **libsecret** (опционально).
- Кэш конфигов на диске — зашифрован/связан с ключом устройства; TTL.
- Запрет на логирование доменов/URL/содержимого трафика в клиенте (policy + code review).
- VPNEngine загружает только движки из bundled-версий (без динамической загрузки из интернета).
- Проверка подписи конфига перед подключением.

---

## 10. Аудит и инциденты

- `audit_logs`: вход/выход, регистрация/отзыв устройств, admin-действия, ошибки логина,
  ротации ключей, смена состояний нод.
- Хранение audit — append-only (RLS/триггеры запрещают UPDATE/DELETE).
- Инцидент-флоу: detection → escalation → containment (отзыв токенов/ключей, DRAINING нод) →
  постмортем → ротация всех затронутых секретов.
- SLA обновления: CVE-мониторинг по движкам (amneziawg-go, xray, wireguard) — еженедельно.

---

## 11. Чеклист

### 11.1 Phase 2 MVP (gate вертикального среза)

- [x] TLS 1.3 на публичных эндпоинтах (в dev допустим self-signed); HSTS — в prod
  - Agent listener: TLS 1.3 + mTLS (M4). User API в Phase 2 MVP — HTTP на localhost (dev);
    публичный TLS/HSTS — pre-prod (§11.2).
- [x] mTLS между CP и агентами (dev CA из `secrets/` / ephemeral) — M4
- [x] Argon2id параметры в конфиге (m=64MiB, t=3, p=4) — M1
- [x] Access JWT **EdDSA**; refresh rotation + reuse detection (покрыто тестами) — M1
- [~] Rate limiting — in-memory sliding window с дефолтами §6 (M1); Redis backend — pre-prod
- [x] Envelope encryption конфигураций с **file-backed KEK** (dev) — M3 (`MVN1`)
- [~] RBAC (`user` / `admin`) — роли в JWT/users; audit log для admin — pre-prod
- [x] Секреты не в git (`.gitignore` + `secrets/`)

**Phase 2 MVP gate (vertical slice):** выполнен через CLI harness —
`make smoke` (auth) + `make smoke-e2e` (device → ConfigParts → awg `.conf` с Jc/Jmin/Jmax → disconnect).
Реальный handshake на живой ноде: `FOCUSVPN_E2E_REAL_TUNNEL=1` + `awg` + node-agent.

### 11.2 Pre-prod / сторы (не gate Phase 2)

- [ ] HSTS и полноценный публичный TLS
- [ ] CRL / отзыв mTLS-сертификатов агентов
- [ ] Admin **2FA (TOTP)** до открытия прод-админки
- [ ] KEK / signing keys только в Secret Manager / HSM
- [ ] `THIRD_PARTY_LICENSES.md` + `NOTICE.md` перед релизом в сторы
- [ ] Salt/KEK rotation policy задокументирована и проверена

## Связано

- [[MOC/Security]] · [[ARCHITECTURE]] · [[API]] · [[DATABASE]] · [[005-configuration-security]] · [[006-auth-session]] · [[TODO]]
