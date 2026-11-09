---
type: hub
tags: [hub, project]
status: active
updated: 2026-08-10
---

# FocusVPN — Проект

## Описание
FocusVPN — коммерческий VPN-сервис с собственными закрытыми клиентами (Android, iOS, macOS, Windows, Linux)
и собственными VPN-нодами. Продукт proprietary: исходный код приложений и бэкенда закрыт, клиенты
публикуются в App Store / Google Play.

Рабочий каталог репозитория может называться `focusvpn`; **продукт и артефакты — FocusVPN**.

Протоколы: **AmneziaWG** (основной, MVP pin `amneziawg-go` `v0.2.19`), **WireGuard**,
**Xray / VLESS + REALITY** (обфускация/маскировка; не MVP).

Движки и клиентские базы — только permissive/open-source компоненты (MIT / Apache-2.0 / MPL-2.0);
GPL-компоненты в продукт не встраиваются. Детали и верификация: `docs/OPEN_SOURCE.md`, решения: `docs/adr/`.

## Цель
Построить надёжный, безопасный и монетизируемый VPN-сервис «под ключ»:
- минимальное время до работающего вертикального среза (MVP);
- закрытый код клиентов при использовании проверенных OSS-компонентов;
- масштабирование через добавление нод, а не архитектурные переделки.

## Ключевые решения (кратко)
- Control Plane — **modular monolith** (Go + PostgreSQL + Redis + REST + Docker). [ADR-001]
- Движки только permissive; клиенты на базах wireguard-android / wireguard-apple. [ADR-002, ADR-003]
- Node Agent: long-poll + mTLS; на ноде peers через `awg`. [ADR-004]
- Конфиги подписываются CP (Ed25519), приватные ключи клиентов не покидают устройство. [ADR-005]
- Access JWT **EdDSA**; refresh с ротацией и reuse detection. [ADR-006]
- Полный лог: `docs/DECISIONS.md`.

## Правила работы
1. Не начинай крупную реализацию без понимания архитектуры. Читай `CLAUDE.md` и [[CURRENT_TASK]].
2. Перед изменением архитектуры изучи [[ARCHITECTURE]].
3. После существенных изменений обновляй документацию и **Project Brain** ([[_system/BRAIN]]).
4. Новые архитектурные решения записывай в [[DECISIONS]] (ADR — в `adr/`).
5. Выполненные задачи отмечай в [[ROADMAP]].
6. Обнаруженные проблемы добавляй в [[TODO]] (Blockers / Risks / Future).
7. Не удаляй существующую функциональность без явного подтверждения.
8. Перед завершением задачи запускай тесты.
9. Информация из интернета — заметка в `research/` по шаблону; обнови [[MOC/Research]] и [[INDEX]].
10. Код нового milestone Phase 2 — только по явному запросу/утверждению milestone (см. [[CURRENT_TASK]]).
11. Поддерживай Project Brain: [[Home]], [[INDEX]], MOC, связи — по [[_system/BRAIN]].

## Навигация по документам
- Project Brain: [[Home]] · [[INDEX]] · [[_system/BRAIN|BRAIN]]
- Контекст для агентов: `CLAUDE.md` (корень репо)
- Архитектура: [[ARCHITECTURE]] · API: [[API]] · БД: [[DATABASE]] · Безопасность: [[SECURITY]]
- Клиенты: [[CLIENT_ARCHITECTURE]] · Деплой: [[DEPLOYMENT]]
- План: [[ROADMAP]] · Текущая задача: [[CURRENT_TASK]] · Решения: [[DECISIONS]] · Проблемы: [[TODO]]
- Открытые источники: [[OPEN_SOURCE]], [[MOC/Research]]
- MOC: [[MOC/Architecture]] · [[MOC/Security]] · [[MOC/Execution]] · [[MOC/Decisions]] · [[MOC/Research]]

## Связано

- [[Home]] · [[CURRENT_TASK]] · [[ROADMAP]] · [[MOC/Execution]]
