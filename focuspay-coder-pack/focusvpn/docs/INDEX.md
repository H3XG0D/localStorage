---
type: system
tags: [index, system]
status: active
updated: 2026-10-12
---

# INDEX — каталог Project Brain

Полный список заметок vault `docs/`. При добавлении заметки — дописать сюда и в релевантный MOC. Схема: [[_system/BRAIN]].

## Hub

- [[Home]] — дашборд входа
- [[STATUS]] — статус-карточка для дашборда экосистемы (brain)
- [[FocusVPN Board]] — Kanban-доска задач
- [[PROJECT]] — цель, правила, навигация
- [[CURRENT_TASK]] — текущий фокус
- [[ROADMAP]] — фазы и DoD
- [[DECISIONS]] — хронологический лог решений
- [[TODO]] — blockers / risks / future

## Plans

- [[plans/M3]] — Phase 2 Milestone 3 design — **implemented**
- [[plans/P3]] — Phase 3 clients — **M6 native libs pipeline done**
- [[plans/P4]] — Phase 4 engines — **P4-M10 docker ABI done**
- [[plans/Launch-L1]] — Sideload launch path — **scripts + landing ready**
- [[plans/Infra-TwoHost]] — Biz focuspay + FR traffic dedic — **topology locked**
- [[plans/E1-vpn-bot]] — Ecosystem VPN Telegram bot + FocusPay wallet — **MVP + sandbox**
- [[plans/E2-app-login]] — Android Telegram login + 1 device + deposit gate — **MVP**
- [[plans/E3-android-vless]] — Android только VLESS+WS+TLS (Xray) — **draft, ждёт полевой проверки CDN**
- [[plans/E4-billing]] — бухгалтерия VPN ⇄ FocusPay: тарифы, триал, гейт, сверка — **в коде, не выложено**
- [[SANDBOX]] — isolated E1 test env (ports 15432/15433, never prod FocusPay)

## Spec

- [[ARCHITECTURE]] — целевая архитектура
- [[API]] — REST / контракты
- [[DATABASE]] — схема БД и миграции
- [[SECURITY]] — модель угроз и сессии
- [[CLIENT_ARCHITECTURE]] — клиенты и движки
- [[DEPLOYMENT]] — деплой и dev-стек
- [[OPEN_SOURCE]] — лицензии и pins

## ADR

- [[001-modular-monolith]] — modular monolith CP
- [[002-vpn-engine-strategy]] — permissive engines
- [[003-client-strategy]] — клиентские базы
- [[004-node-agent]] — agent poll + mTLS
- [[005-configuration-security]] — подпись ConfigParts
- [[006-auth-session]] — JWT EdDSA + refresh
- [[007-ecosystem-billing-federation]] — FocusPay wallet + FocusVPN bot federation
- [[008-telegram-app-login]] — Telegram login для Android (deep-link + код)
- [[009-android-vless-only]] — Android только VLESS (Xray-core), без AmneziaWG — **proposed**
- [[010-vpn-billing-saga]] — покупка VPN: сага FocusPay → CP, идемпотентный grant, сверка
- [[011-ru-direct]] — российские сайты и приложения с IP телефона, зарубежное через VLESS
- [[012-node-limits]] — 100 Мбит/с на UUID, пауза при четырёх адресах, нода сама уходит в OFFLINE с причиной
- [[013-happ-subscription-link]] — Happ и похожие клиенты берут ключ ссылкой, FocusVPN входит кодом

## Research

- [[research/README|research README]]
- [[2026-10-07-onest-font]] — шрифт Onest, SIL OFL-1.1, Android-клиент
- [[2026-10-07-android-vless-xray]] — Android VLESS: Xray TUN, лицензии, Cloudflare режется в РФ
- [[2026-08-11-awg-2-3-eval]] — AWG 2.0/3.0 eval; stay on v0.2.19
- [[2026-08-10-amneziawg-versions]] — pin AWG vs upstream 3.0
- [[2026-08-10-opensource-baseline]] — baseline OSS
- [[2026-08-10-go-dependencies-m1]] — deps Milestone 1
- [[2026-08-10-go-dependencies-m2]] — deps Milestone 2

## MOC

- [[MOC/Architecture]]
- [[MOC/Security]]
- [[MOC/Execution]]
- [[MOC/Decisions]]
- [[MOC/Research]]

## Agents

- [[agents/README|agents hub]] — обзор конфига skills
- [[agents/issue-tracker]] — куда skills пишут тикеты (`.scratch/` + board)
- [[agents/domain]] — как читать `CONTEXT.md` / ADR / brain
- [[agents/triage-labels]] — словарь triage-статусов
- Root `CONTEXT.md` — ubiquitous language (глоссарий)

## System

- [[_system/BRAIN|BRAIN]] — схема мозга
- [[INDEX]] — этот файл
- Шаблоны: `_templates/research`, `_templates/adr`, `_templates/decision-log`
- Запуск Obsidian: `./scripts/open-brain.sh` (Flatpak `md.obsidian.Obsidian`)
