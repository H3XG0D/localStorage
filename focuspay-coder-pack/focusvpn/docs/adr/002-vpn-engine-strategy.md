---
type: adr
tags: [adr, engines]
status: accepted
updated: 2026-08-10
---

# ADR-002: Стратегия VPN-движков

- **Статус:** Принято (PHASE 1, 10.08.2026)
- **Дата:** 10.08.2026
- **Основа:** `docs/OPEN_SOURCE.md` (верифицировано); `docs/ARCHITECTURE.md` §3; `docs/CLIENT_ARCHITECTURE.md`

## Контекст

Нужно поддерживать 3 протокола (AmneziaWG, WireGuard, Xray/VLESS+REALITY) на 5 платформах и на
собственных нодах, оставаясь лицензионно чистыми для закрытого продукта (App Store / Google Play).

## Решение

- Движки — **только permissive**: `amneziawg-go` (MIT), `wireguard-go` (MIT), `xray-core`
  (MPL-2.0, конфигурируем через JSON), `amnezia-libxray` (MIT, мобильные).
- **Не линкуем** GPL-компоненты: ни amnezia-wireguard (GPL-2.0), ни amnezia-client (GPL-3.0),
  ни kernel-модуль amneziawg как обязательный.
- На нодах: AmneziaWG интерфейс управляется через **`awg` / amneziawg-tools** (GPL-2.0) как
  **отдельный процесс** из Node Agent. Userspace `amneziawg-go` — основной путь **в клиентах**;
  на ноде go-userspace допустим как fallback/dev, но MVP production path — `awg` + опционально
  kernel-модуль для perf.
- Клиентские базы (для UI/архитектуры): `wireguard-android` (Apache-2.0), `wireguard-apple` (MIT).
- Единая абстракция `VPNEngine` (см. ADR-003 и CLIENT_ARCHITECTURE.md §2) изолирует клиентов от
  конкретного движка.
- **Pin MVP:** `amneziawg-go` tag **`v0.2.19`** (см. OPEN_SOURCE.md §3.1).

## Последствия

**Плюсы:** лицензионно чистый закрытый продукт; простой выбор движка по платформе; быстрый старт
через готовые Go-реализации.

**Минусы:** производительность userspace-движков ниже kernel; требует мониторинга и настройки.
MPL-2.0 (Xray) требует раскрытия модифицированных файлов — мы не модифицируем xray-core, только
конфигурируем.

## Альтернативы

- Форк amnezia-client (GPL-3.0) — отклонено: обязательное раскрытие кода продукта.
- Только WireGuard — отклонено: теряем обфускацию AmneziaWG и REALITY-маскировку.
- Собственный движок с нуля — отклонено: неоправданные трудозатраты и риски.

## Связано

- [[OPEN_SOURCE]] · [[ARCHITECTURE]] · [[CLIENT_ARCHITECTURE]] · [[DECISIONS]] · [[MOC/Decisions]]
