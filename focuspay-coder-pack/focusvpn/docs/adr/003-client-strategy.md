---
type: adr
tags: [adr, clients]
status: accepted
updated: 2026-08-10
---

# ADR-003: Стратегия клиентов

- **Статус:** Принято (PHASE 1, 10.08.2026)
- **Дата:** 10.08.2026
- **Основа:** `docs/OPEN_SOURCE.md`; `docs/CLIENT_ARCHITECTURE.md`

## Контекст

5 платформ (Android, iOS, macOS, Windows, Linux). Требование: закрытый код, полный контроль UX,
публикация в App Store / Google Play, один бренд. Варианты: взять открытый клиент целиком,
форкнуть его, написать с нуля, либо гибрид.

## Решение

- **Android** — на базе архитектуры `wireguard-android` (Apache-2.0): пермиссивно, ускоряет
  разработку, сохраняем закрытость. UI — собственный (Compose).
- **iOS/macOS** — на базе `wireguard-apple` (MIT), общая кодовая база `clients/apple/`
  (Network Extension). Отдельный Go+UI клиент для macOS **не** делаем.
- **Windows** — собственный: движок на Go + тонкий UI (wintun).
- **Linux** — собственный: движок на Go + GTK/CLI.
- Не форк amnezia-client (GPL-3.0).
- Общие контракты в `clients/shared/`; Phase 2 поставляет контракты + **CLI harness**
  (`clients/cli/`); полноценные UI — Phase 3.
- Движки: permissive, по ADR-002.

## Последствия

**Плюсы:** лицензионно чистый путь в сторы; контроль бренда и UX; сокращение сроков (базы
wireguard-экосистемы богаты готовыми решениями: VpnService, NEPacketTunnelProvider, тюнинг DNS);
единый интерфейс для трёх движков.

**Минусы:** нужно поддерживать 5 кодовых баз (снижаем общим `clients/shared/`); переписывание
UI wireguard-баз под бренд — трудозатраты; зависимость от чужого кода (нужен аудит обновлений).

## Альтернативы

- Форк amnezia-client — отклонено (GPL-3.0 → раскрытие кода).
- Писать всё с нуля — отклонено (сроки, TUN/NE/VpnService уже отлажены в базах).
- Использовать чужие закрытые SDK (без разрешения) — исключено.

## Связано

- [[CLIENT_ARCHITECTURE]] · [[OPEN_SOURCE]] · [[ARCHITECTURE]] · [[DECISIONS]] · [[MOC/Decisions]]
