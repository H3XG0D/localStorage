---
type: adr
tags: [adr, engines, android, xray, vless]
status: proposed
updated: 2026-10-07
---

# ADR-009: Android — только VLESS (Xray-core), без AmneziaWG

- **Статус:** Предложено (07.10.2026). Принимается после полевой проверки транспорта и CDN (этап 0
  в [[plans/E3-android-vless]]).
- **Дата:** 07.10.2026
- **Частично заменяет:** [[002-vpn-engine-strategy]] — только для Android. Desktop/Linux/Windows не меняются.

## Контекст

CEO (полевой опыт): AmneziaWG в РФ — низкая скорость, протокол детектируется, сервер улетает в бан
примерно за месяц. Рабочий стандарт сейчас — VLESS + WebSocket. Заказчик выбрал: на Android только
VLESS+WS+TLS, ноды за CDN.

Состояние кода: CP уже отдаёт `vless-ws` по умолчанию, но `xrayPart` — заглушка
(`"uuid": "assigned-device-side"`, путь `/vpn-<alloc>` не совпадает с конфигом ноды); node-agent
Xray не знает; в Android нет Xray вообще. Исследование — [[2026-10-07-android-vless-xray]].

## Решение

1. **Движок Android:** Xray-core (MPL-2.0) in-process через **XTLS/libXray (MIT)** gomobile `.aar`,
   pinned tag. Трафик — нативный Xray `tun` inbound (fd через `XRAY_TUN_FD`), без tun2socks.
   Свой пакет исключается из VPN (`addDisallowedApplication`) против петли.
2. **AmneziaWG на Android удаляется:** `AmneziaTunnelEngine`, `libwg-go.so`, AWG-разбор ConfigParts.
3. **Транспорт:** VLESS + WS + TLS на 443. Поля `network`/`security`/`path`/`host`/`sni`/`address`
   приходят из ConfigParts — смена на `xhttp`/REALITY не требует релиза клиента.
4. **CDN — слой конфигурации, провайдер не зашит.** `address`/`sni`/`host` = CDN-домен ноды,
   origin скрыт. **Cloudflare не выбран:** по данным Cloudflare соединения из РФ режутся до ~16 КБ
   (с 06.2025, подтверждено 04.2026). Провайдер — по итогам этапа 0.
5. **Учётные данные:** CP генерирует **VLESS UUID на устройство**, хранит зашифрованным (KEK),
   отдаёт в подписанных ConfigParts (Ed25519 без изменений), node-agent добавляет/удаляет его на
   ноде через Xray API. Отзыв устройства = удаление UUID на всех нодах.

## Последствия

**Плюсы:** выглядит как HTTPS; IP ноды за CDN не виден; транспорт меняется с сервера.

**Минусы / риски:**
- MPL-ядро внутри APK (раньше — «отдельный процесс»). Допустимо: файлы Xray не правим, даём NOTICE
  + ссылку на исходники ([[OPEN_SOURCE]]).
- UUID — общий секрет, не ключевая пара. Правило «приватный ключ не покидает устройство»
  для VLESS неприменимо; компенсация — UUID на устройство, ротация, шифрование на CP и в
  `EncryptedSharedPreferences`.
- Лимит «1 устройство» слабее: Xray не ограничивает одновременные сессии на UUID. Контроль — через
  статистику ноды и ротацию UUID.
- TCP+TLS+WS медленнее WireGuard на чистом канале; APK больше (~20 МБ на ABI).
- Никакой протокол не переживает whitelist-фильтрацию на мобильном интернете.

## Альтернативы

- Оставить AmneziaWG основным — отклонено заказчиком (полевой опыт CEO).
- VLESS + запасной AmneziaWG — отклонено заказчиком в пользу одного движка.
- v2rayNG / AndroidLibXrayLite — отклонено: GPL-3.0 / LGPL-3.0.
- sing-box — отклонено: GPL-3.0-or-later.
- Xray как отдельный процесс на Android — возможно, но передача TUN fd в дочерний процесс и
  управление жизненным циклом сложнее; in-process через libXray проще.

## Связано

- [[002-vpn-engine-strategy]] · [[2026-10-07-android-vless-xray]] · [[plans/E3-android-vless]] ·
  [[OPEN_SOURCE]] · [[DECISIONS]] · [[MOC/Decisions]]
