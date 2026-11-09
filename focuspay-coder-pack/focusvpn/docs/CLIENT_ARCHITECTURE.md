---
type: spec
tags: [clients, spec]
status: active
updated: 2026-08-10
---

# FocusVPN — Архитектура клиентов

> PHASE 1 · без кода. Основа: `docs/OPEN_SOURCE.md` (лицензии), `docs/ARCHITECTURE.md` §7–§8.

---

## 1. Стратегия (итог OPEN_SOURCE.md)

- **Тонкие собственные клиенты**, НЕ форк AmneziaVPN client (GPL-3.0 — отклонён).
- Пермиссивные базы: **wireguard-android** (Apache-2.0) для Android, **wireguard-apple** (MIT)
  для **iOS и macOS** (`clients/apple/`) — берём архитектуру/код как основу, переписывая под бренд.
- **Windows / Linux** — собственные клиенты: движок на Go + тонкий UI (Windows: wintun;
  Linux: `/dev/net/tun` + GTK/CLI). macOS **не** дублируется как Go-desktop — только apple NE.
- Движки встраиваем: **amneziawg-go** MIT pin **`v0.2.19`**, **wireguard-go** (MIT),
  **amnezia-libxray** (MIT, мобильные) / Xray-core (MPL-2.0, JSON). GPL не линкуем.

```
┌────────────────────────────── Клиент (все платформы) ──────────────────────────────┐
│  UI / UX (Kotlin, Swift, Go…)                                                      │
│  AppCore: состояние, авторизация, device-менеджер, конфиг-кэш, подпись-проверка     │
│  VPNEngine (интерфейс-абстракция)                                                   │
│     ├── AmneziaWGEngine  → amneziawg-go (+ JNI/Swift bridge)                        │
│     ├── WireGuardEngine  → wireguard-go                                             │
│     └── XrayEngine       → amnezia-libxray / xray-core (JSON)                       │
│  TUN-уровень: VpnService (Android) / NEPacketTunnelProvider (Apple)                 │
│               / wintun (Windows) / /dev/net/tun (Linux)                             │
│  Secure Storage: Keychain / Keystore / DPAPI / libsecret                            │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Абстракция VPNEngine (контракт)

Единый интерфейс для всех трёх движков и всех платформ. Контракт (в `clients/shared/`):

```go
// псевдокод контракта (реализация UI-движков — PHASE 3;
// PHASE 2: JSON-схемы в clients/shared/ + CLI harness в clients/cli/)
type VPNEngine interface {
    // lifecycle
    Prepare(ctx) error                 // проверка разрешений (VpnService/NE), подготовка TUN
    Start(ctx, config *AssembledConfig) error   // поднять туннель
    Stop(ctx) error
    State() ConnectionState            // connecting | connected | disconnected | error

    // events/stats
    OnStateChange(cb func(StateInfo))          // коллбек для UI
    Stats() (*EngineStats, error)              // rx/tx, latency, handshake_at

    // config
    SetConfig(parts ConfigParts) error         // части без приватного ключа
    RotateKeys() (*PublicKey, error)           // новая пара на устройстве
    SetDns(servers []string) error

    // transport (TUN) — переопределяется платформой
    EnableTunnel(routes []string) error
    DisableTunnel() error
}
```

- `ConfigParts` — те же части, что приходят из CP (`/v1/configurations/:id`): `interface`,
  `peer`, `protocol` (obfuscation/REALITY). Приватный ключ клиент вставляет **локально**.
- Каждый движок реализует `VPNEngine` поверх своего TUN и внутренностей (wg-tunnel,
  amneziawg-tunnel, xray inbound). UI зависит только от интерфейса — не от движка.

---

## 3. Сборка конфига на клиенте

1. Клиент получает подписанные `ConfigParts` (см. ARCHITECTURE.md §8) и **проверяет подпись
   Ed25519** по встроенному публичному ключу CP.
2. Проверяет `config_version` ≥ кэшированной (исключает replay/устаревший конфиг).
3. Из secure storage достаёт **приватный ключ** и собирает полный конфиг движка:
   - AmneziaWG/WireGuard: `[Interface] PrivateKey=<device>, Address=<ip>, DNS=<dns>` +
     `[Peer] PublicKey=<server>, Endpoint=<host:port>, AllowedIPs=0.0.0.0/0,::/0`,
     + obfuscation-параметры для AmneziaWG;
   - Xray/REALITY: `outbound.vless` с `address`, `uuid`, `flow`, `publicKey` (REALITY), `shortId`,
     `serverName`.
4. Только после этого `VPNEngine.Start(...)`. Приватный ключ не покидает процесс приложения.

---

## 4. Платформенная реализация

### 4.1 Android (Kotlin)
- База: архитектура **wireguard-android** (Apache-2.0) — VpnService, Activity/Compose UI.
- TUN: `VpnService.Builder` (exclude/include routes, DNS).
- Движки: **amneziawg-android / amneziawg-go** (JNI) для AmneziaWG; **wireguard-android**
  (Go via JNI) для WG; **amnezia-libxray** (MIT) для Xray/REALITY.
- Ключи: Android **Keystore** (non-exportable, alias per device).
- Дополнительно: foreground service с постоянным уведомлением (policy Google Play).

### 4.2 iOS + macOS (Swift) — `clients/apple/`
- База: **wireguard-apple** (MIT) — общая кодовая база для iOS/macOS.
- TUN: `NetworkExtension` — `NEPacketTunnelProvider` / `NEDNSSettings` / маршруты.
- Движки: **amneziawg-go / amneziawg-apple** (Swift bridge) для AmneziaWG; **wireguard-go** для WG;
  **amnezia-libxray** для Xray.
- Ключи: iOS **Keychain** (`kSecAttrAccessibleAfterFirstUnlock`), macOS Keychain.
- Монетизация/настройки через App Store: VPN-конфигурация (NE) обязательна для прода в App Store —
  встроена, UI не показывает системные настройки.

### 4.3 Windows
- Собственный клиент: **Go-движок** (wireguard-go / amneziawg-go) + UI на C#/WPF или WinUI.
- TUN: **wintun.dll** (Prebuilt Binaries License — распространяется «рядом с ПО», подключается
  через `LoadLibraryEx` + динамические вызовы; не редистрибутится автономно).
- Движки: amneziawg-go, wireguard-go; Xray — встроенный процесс (xray-core, JSON-конфиг).
- Ключи: **DPAPI** (`CryptProtectData`, CurrentUser).
- Установка: инсталлятор (MSI/NSIS), драйвер tun/tap не требуется (wintun).

### 4.4 Linux
- Собственный клиент: Go-движок + UI (GTK/электро-опц.); для headless/серверов — CLI-режим.
- TUN: `/dev/net/tun`; требует `CAP_NET_ADMIN` (или root при установке).
- Движки: amneziawg-go / wireguard-go (userspace) или системный `wg-quick`/`amneziawg` (GPL,
  вызываем как подпроцесс), Xray — подпроцесс.
- Ключи: **libsecret** (Secret Service), fallback — зашифрованный файл 0600.

---

## 5. Жизненный цикл соединения (общий для платформ)

```
Idle
 ├─ Пользователь нажимает Connect
 ├─ AppCore: проверить подписку → (локальный кэш конфига валиден? да → использовать; нет →
 │    POST /v1/connections → GET /v1/configurations/:id → проверить подпись → собрать)
 ├─ VPNEngine.Prepare()      // системный запрос разрешений (VpnService/NE)
 ├─ VPNEngine.Start(config)  // туннель поднят → state = connected
 ├─ UI: состояние connected, метрики (rx/tx, latency)
 ├─ фон: heartbeat/telemetry (POST /v1/heartbeat) — раз в 30–60 с
 ├─ Сбой → ReconnectController (backoff, см. ARCHITECTURE.md §10.3)
 └─ Disconnect → VPNEngine.Stop() → state = idle (конфиг остаётся в кэше с TTL)
```

Кэш конфигов: хранится на диске (зашифрованный, связанный с устройством), TTL 24 ч; при
устаревании/версии — повторный `POST /v1/connections`.

---

## 6. Компоненты AppCore (общие для всех клиентов)

| Компонент | Ответственность |
|---|---|
| `AuthService` | логин/регистрация/refresh, хранение токенов в secure storage |
| `DeviceService` | регистрация устройства, генерация keypair, rotate-key |
| `ConfigCache` | кэш конфигов (шифрованный), проверка подписи/версии |
| `Connectivity` | выбор эндпоинта, failover, backoff |
| `Telemetry` | сбор минимальной телеметрии, heartbeat |
| `Settings` | страна/регион, протокол (по умолчанию AmneziaWG), DNS-режимы |
| `VPNEngine` | движки (см. §2) |
| `SecureStorage` | Keychain/Keystore/DPAPI/libsecret — абстракция хранения ключей и токенов |

---

## 7. `clients/shared/` — единые контракты

Общий пакет контрактов для всех платформ (избегает рассинхронизации между 5 клиентами):

- JSON-схемы: `ConfigParts`, `ConnectionRequest`, `Heartbeat`, `ServerEndpoint`, ошибки.
- события движка (`ConnectionState`, `EngineStats`, `EngineErrorCode`).
- настройки протокола (AmneziaWG obfuscation, REALITY params) — общая структура.

---

## 8. Версии движков и фиксация

- Все движки пиннуются по версиям (go.mod / gradle / SPM) и проходят CVE-мониторинг еженедельно
  (см. SECURITY.md §10).
- Любое изменение встроенных движков — отдельный PR с обновлением `NOTICE.md`
  и `THIRD_PARTY_LICENSES.md` (обязательно для App Store / Google Play).

---

## 9. Связанные документы

- `docs/OPEN_SOURCE.md` — детали лицензий и происхождение компонентов
- `docs/ARCHITECTURE.md` §7 (devices), §8 (config lifecycle), §10 (failover)
- `docs/API.md` — эндпоинты, которые дёргает клиент

## Связано

- [[OPEN_SOURCE]] · [[ARCHITECTURE]] · [[API]] · [[003-client-strategy]] · [[002-vpn-engine-strategy]] · [[MOC/Architecture]]
