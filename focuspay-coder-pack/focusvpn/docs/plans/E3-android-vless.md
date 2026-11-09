---
type: plan
tags: [plan, android, xray, vless, node-agent]
status: active
updated: 2026-10-09
---

# E3 — Android на VLESS+WS+TLS (Xray), без AmneziaWG

**Status: active — этапы 1–2 (CP и node-agent) написаны локально, не выложены.** Решение: [[009-android-vless-only]] (proposed). Исследование:
[[2026-10-07-android-vless-xray]].

## Goal

Android-клиент подключается только по VLESS+WS+TLS через Xray-core. CP выдаёт настоящий VLESS UUID
на устройство, node-agent добавляет/удаляет его на ноде. Транспорт и CDN меняются конфигом с CP.
Вход через Telegram, 1 устройство и оплата с баланса ([[plans/E2-app-login]]) не меняются.

## Этап 0 — полевая проверка (human, гейт для остального)

Без него весь план может уйти в схему, которую режет РКН.

- ~~Поднять тестовую ноду~~ — **готово 07.10.2026**, **снята 09.10.2026**: бывшая нода **DE1** (`94.26.83.74`, Франкфурт, `ssh focusvpn-de1`) теперь Оллама, не VPN. На 07.10 там стояли
  домен-заглушка `94-26-83-74.sslip.io` (Let's Encrypt). Nginx :443 с сайтом-приманкой, за ним Xray
  `v26.3.27`: VLESS+WS и VLESS+XHTTP на секретных путях. API Xray только на `127.0.0.1:10085`.
  Ставится одной командой: `scripts/node-vless-setup.sh <ssh-host> <domain>` (идемпотентно, ключи
  хранятся на ноде в `/root/focusvpn/node.env`). Тестовые ссылки/QR — `.scratch/node-de1/` (gitignored).
  Проверено с локальной машины: выход через оба транспорта = IP ноды, канал ноды ~460–690 Мбит/с.
- **DE2** (08.10.2026): `147.45.39.132`, ssh `focusvpn-de2`, `147-45-39-132.sslip.io`, в CP `HEALTHY`.
  Та же команда. С локальной машины WS и XHTTP выходят с IP ноды. Нода слабее (1 vCPU / 2 ГБ).
- **NL1** (08.10.2026): `193.233.82.168`, Амстердам, ssh `focusvpn-nl1`, `193-233-82-168.sslip.io`, в CP `HEALTHY`.
  WS и XHTTP с локальной машины выходят с IP ноды. 1 vCPU / 2 ГБ.
- **NL2** (08.10.2026): `199.91.221.37`, Амстердам, BitLaunch, ssh `focusvpn-nl2`, `199-91-221-37.sslip.io`, в CP `HEALTHY`.
  Заглушка HTTPS отвечает 200, сертификат до 06.01.2027. 1 vCPU / 1 ГБ, capacity 100.
- **RO1** (08.10.2026): `64.7.199.95`, Бухарест, BitLaunch, ssh `focusvpn-ro1`, `64-7-199-95.sslip.io`, в CP `HEALTHY`.
  Заглушка HTTPS отвечает 200, сертификат до 06.01.2027. 1 vCPU / 1 ГБ, capacity 100. В выложенном APK страна пишется «RO».
- **GB1** (08.10.2026): `193.149.189.177`, Лондон, BitLaunch, ssh `focusvpn-gb1`, `193-149-189-177.sslip.io`, в CP `HEALTHY`.
  Заглушка HTTPS отвечает 200, сертификат до 06.01.2027. 1 vCPU / 1 ГБ, capacity 100. В приложении «Великобритания».
- Проверить с SIM и домашнего интернета **целевых** провайдеров: напрямую, через Cloudflare,
  через другой CDN (Gcore / CloudFront). Мерить: подключается ли, скорость, живёт ли сутки+.
- Cloudflare по первоисточнику режется до ~16 КБ на соединение в РФ — ожидаем провал, но проверить.
- Итог: выбранный транспорт (`ws` / `xhttp` / REALITY) + CDN → ADR-009 в `accepted`.

## Этап 1 — CP: настоящие учётные данные VLESS

Код есть (07.10.2026), на focuspay ещё не выложен.

- Миграция `000007`: `vpn_allocations.vless_uuid`, `vpn_endpoints.xray` (transport/path/host/sni/alt),
  `node_traffic_daily`.
- `connections.xrayPart`: UUID подключения, основной сервер и запасные (плюс alt-транспорт той же ноды).
  Заглушки `assigned-device-side` больше нет.
- Отзыв устройства отзывает подключение и будит все Xray-ноды. Истёкшая подписка выпадает из desired
  state на тике планировщика. Нода без телеметрии 90 с помечается OFFLINE и при следующем подключении
  клиент уходит на другую.
- Выбор ноды: VLESS без WG-ключа, наименьшая нагрузка (онлайн/capacity), top-3.
- `POST /v1/internal/nodes` регистрирует ноду (идемпотентно по имени). `GET /v1/internal/reports/summary`
  — подписки, покупки, онлайн и трафик по нодам.
- Тесты: `connections/vless_test.go`, `nodereg/handler_test.go`, `nodeagent` VLESS state + heartbeat.

## Этап 2 — node-agent: Xray applier

Код есть (07.10.2026). На DE1 агент ещё не запущен: CP не выложен, тестовый вход с телефона живёт
статическим пользователем Xray.

- `AGENT_ENGINE=xray`: `node-agent/internal/xrayapplier` вызывает `xray api adu/rmu` (отдельный процесс).
  Формат проверен на DE1. Удаляются только email-UUID от CP; ручной `test-1@focusvpn` не трогается.
- Телеметрия: онлайн (`statsgetallonlineusers`) и дельты трафика inbound → CP (`load`, суточные байты).
- Пустой desired state тоже применяется, иначе отзыв не снимал бы пользователя.
- `scripts/node-vless-setup.sh` при `FOCUSVPN_CP_URL` + `FOCUSVPN_AGENT_URL` + `FOCUSVPN_INTERNAL_TOKEN`
  регистрирует ноду, собирает агент и ставит systemd `focusvpn-agent`.

## Этап 3 — Android: XrayTunnelEngine

Код есть (07.10.2026). Сборка `assembleDebug` проходит. На живом телефоне ещё не проверялось:
control plane не выложен, поэтому приложение пока не к чему подключать в проде.

- `libXray` `v26.9.30` (MIT), `scripts/fetch-libxray-android.sh`, AAR не в git.
- `XrayTunnelEngine`: TUN fd в `env["xray.tun.fd"]`, сокеты Xray защищены `protectFd`.
- AmneziaWG с Android убран (`AmneziaTunnelEngine`, `AwgConfig`, `libwg-go`).
- Протокол запроса — `vless`. По умолчанию локация «Авто». Серверы из ConfigParts пробуются по порядку;
  «Подключено» — только после ответа `generate_204` через туннель.
- Тест: `XrayClientConfigTest`.

## Этап 4 — проверка

- Локально: Xray-сервер в `.scratch` + эмулятор → HTTP изнутри туннеля (как `.scratch/awgserver`).
- На ноде: подключение с реального телефона у целевых провайдеров; отзыв устройства рвёт сессию.
- `make license-check`, `THIRD_PARTY_LICENSES.md`, `NOTICE.md`: Xray-core (MPL-2.0, ссылка на
  исходники), libXray (MIT).

## Открытые вопросы

- CDN-провайдер и транспорт — по этапу 0.
- AmneziaWG на desktop/Windows — оставляем или тоже переводим (вне скоупа E3).
- Контроль одновременных сессий на один UUID — насколько строго.

## Связано

- [[009-android-vless-only]] · [[002-vpn-engine-strategy]] · [[plans/E2-app-login]] ·
  [[plans/Infra-TwoHost]] · [[CURRENT_TASK]] · [[MOC/Execution]]
