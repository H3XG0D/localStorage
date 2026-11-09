---
type: moc
tags: [moc, decisions]
status: active
updated: 2026-10-12
---

# MOC — Decisions

Лог и ADR. Краткие записи — в [[DECISIONS]]; обоснования — в `adr/`.

## Лог

- [[DECISIONS]] — хронология (Phase 1, Phase 2 readiness, M1, M2, …)

## ADR map

| ID | Тема | Файл |
|---|---|---|
| 001 | Modular monolith CP | [[001-modular-monolith]] |
| 002 | VPN engine strategy (permissive) | [[002-vpn-engine-strategy]] |
| 003 | Client strategy | [[003-client-strategy]] |
| 004 | Node Agent | [[004-node-agent]] |
| 005 | Configuration security | [[005-configuration-security]] |
| 006 | Auth session (EdDSA + refresh) | [[006-auth-session]] |
| 007 | Ecosystem billing federation (FocusPay) | [[007-ecosystem-billing-federation]] |
| 008 | Telegram app login (Android) | [[008-telegram-app-login]] |
| 009 | Android только VLESS (Xray), без AmneziaWG — proposed | [[009-android-vless-only]] |
| 010 | Покупка VPN: сага FocusPay → CP, идемпотентный grant | [[010-vpn-billing-saga]] |
| 011 | Российские сайты и приложения мимо туннеля (Android) | [[011-ru-direct]] |
| 012 | Потолок 100 Мбит/с, пауза при 4+ адресах, автоотключение ноды | [[012-node-limits]] |
| 013 | Ключ ссылкой для Happ, код для Focus | [[013-happ-subscription-link]] |

Новый ADR: шаблон `_templates/adr.md` → файл `adr/00N-slug.md` → строка сюда и в [[INDEX]] · [[DECISIONS]].

## Связано

- [[Home]] · [[INDEX]] · [[MOC/Architecture]] · [[MOC/Security]]
