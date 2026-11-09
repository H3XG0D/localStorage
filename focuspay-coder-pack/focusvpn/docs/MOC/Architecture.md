---
type: moc
tags: [moc, architecture]
status: active
updated: 2026-10-08
---

# MOC — Architecture

Карта архитектурных спек FocusVPN.

## Спеки

- [[ARCHITECTURE]] — high-level blueprint, модули CP, ноды
- [[API]] — REST, auth, devices, servers, configurations
- [[DATABASE]] — таблицы, миграции, store
- [[CLIENT_ARCHITECTURE]] — платформы, AppCore, движки
- [[DEPLOYMENT]] — VM/systemd, local compose, Launch-L1 / [[plans/Infra-TwoHost]]
- [[OPEN_SOURCE]] — permissive-only, pins
- [[plans/Infra-TwoHost]] — biz + FR traffic topology

## Связанные ADR

- [[001-modular-monolith]]
- [[002-vpn-engine-strategy]]
- [[003-client-strategy]]
- [[004-node-agent]]
- [[012-node-limits]] — потолок скорости, адреса на UUID, автоотключение ноды

## Исполнение

- [[MOC/Execution]] · [[CURRENT_TASK]] · [[ROADMAP]] · [[plans/M3]] (M3 design draft)

## Связано

- [[Home]] · [[INDEX]] · [[MOC/Security]] · [[MOC/Decisions]]
