---
type: hub
tags: [hub, focusvpn]
status: active
updated: 2026-10-09
---

# FocusVPN — документация VPN

> [!tip] Ты внутри проекта FocusVPN
> Пульт всей экосистемы: [[Home|← назад в Штаб]] (файл `Home` в корне brain).  
> Задачи VPN двигай здесь: [[FocusVPN Board|🟣 доска FocusVPN]].

Эта папка — доки FocusVPN. Общий штаб (оба проекта, люди, сроки) — vault `~/Documents/brain`.

## Всегда записывать (после существенной работы)

| Событие | Куда |
|---|---|
| Смена фокуса / milestone | [[CURRENT_TASK]] (+ статус здесь, если фаза изменилась) |
| Решение | строка в [[DECISIONS]]; если архитектурное — ADR из `_templates/adr` |
| Research / лицензии | `research/` из `_templates/research` + [[MOC/Research]] + [[INDEX]] |
| Риск / долг | [[TODO]] |
| Любая новая заметка | frontmatter + `[[wikilink]]` + [[INDEX]] + MOC |

Полный протокол агента: корневой `CLAUDE.md` · схема: [[_system/BRAIN]].

## Статус

- **Phase 1** — архитектура: завершена
- **Phase 2** — Backend + Node Agent (MVP): **готов** (M1–M5)
- **Phase 3** — Клиенты: packet IO + **native lib pipeline** (NDK/Mac build) [[plans/P3]]
- **Phase 4** — Движки: **P4-M1…M10 готовы** [[plans/P4]]
- **Launch-L1** — sideload path готов; топология [[plans/Infra-TwoHost]]
  - Biz: `focuspay` 153.80.249.77 (уже live)
  - Следующий (человек): заказать FR dedic + DNS + provision
- **E4** — бухгалтерия VPN ⇄ FocusPay выложена ([[plans/E4-billing]]). 08.10.2026 на focuspay: докупка устройства, кнопка «FocusVPN» в боте FocusPay, выручка VPN в PnL.
- **Ноды** — DE2 (Франкфурт), NL1 и NL2 (Амстердам), RO1 (Бухарест), GB1 (Лондон), VLESS. DE1 `94.26.83.74` с 09.10.2026 не локация: на ней Оллама для Ops AI. Подробности: [[CURRENT_TASK]] · [[012-node-limits]].
- Детали: [[CURRENT_TASK]] · план: [[ROADMAP]]

## Non-negotiables

- Нет GPL/AGPL в product binary; GPL-tools на ноде только как отдельные процессы
- Приватные ключи клиента не покидают устройство; CP подписывает ConfigParts (Ed25519)
- Access JWT = EdDSA (Ed25519); refresh rotation + reuse detection
- MVP AmneziaWG: Jc + H/S/I уникально на ноду; pin `amneziawg-go` `v0.2.19`

## Maps of Content

- [[MOC/Architecture|Architecture]] — blueprint, API, БД, клиенты, деплой
- [[MOC/Security|Security]] — угрозы, JWT, подпись конфигов
- [[MOC/Execution|Execution]] — roadmap, текущая задача, TODO
- [[MOC/Decisions|Decisions]] — лог решений + ADR
- [[MOC/Research|Research]] — внешние источники и лицензии

## Быстрый вход

| Нужно | Открыть |
|---|---|
| Цель и правила | [[PROJECT]] |
| Что делать сейчас | [[CURRENT_TASK]] |
| Каталог всех заметок | [[INDEX]] |
| Как устроен мозг | [[_system/BRAIN\|BRAIN]] |
| Архитектура | [[ARCHITECTURE]] |
| Безопасность | [[SECURITY]] |

Агенты: корневой `CLAUDE.md` — operating manual + brain. Skills: `/grill-with-docs` → `/to-spec` → `/to-tickets` → `/tdd` (конфиг: [[agents/domain]] · [[agents/issue-tracker]] · `CONTEXT.md`).
