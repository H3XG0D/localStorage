---
type: research
tags: [research, android, xray, vless, licenses, censorship]
status: done
updated: 2026-10-07
source: "GitHub API (licenses), XTLS/Xray-core releases + proxy/tun/README, Cloudflare blog + support docs"
---

# Android VLESS: движок Xray, TUN, лицензии, CDN в РФ

Date: 2026-10-07

## Source

- Лицензии: `api.github.com/repos/<repo>` (поле `license.spdx_id`), проверено 07.10.2026
- Xray TUN: [release v26.1.23](https://github.com/XTLS/Xray-core/releases/tag/v26.1.23), [proxy/tun/README.md](https://github.com/XTLS/Xray-core/blob/main/proxy/tun/README.md), [docs TUN](https://xtls.github.io/en/config/inbounds/tun.html)
- Cloudflare в РФ: [blog](https://blog.cloudflare.com/russian-internet-users-are-unable-to-access-the-open-internet/), [support doc, обновлено 23.04.2026](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/service-disruption/)
- Полевые отчёты (вторичные, анекдотичные): [ntc.rkn.quest, июнь 2025](https://ntc.rkn.quest/t/vless-websocket-over-cloudflare-cdn-%D0%BF%D0%B5%D1%80%D0%B5%D1%81%D1%82%D0%B0%D0%BB-%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D0%B0%D1%82%D1%8C/16977), [r/VPN, март 2026](https://www.reddit.com/r/VPN/comments/1s44fhb/russian_isp_akado_moscow_blocking_all_vlesstunnel/)

## Summary

**Лицензии (первоисточник — GitHub API):**

| Компонент | Лицензия | Вывод |
|---|---|---|
| XTLS/Xray-core | MPL-2.0 | ✅ Можно встраивать; правленые файлы — под MPL. Мы не правим |
| XTLS/libXray (gomobile-обёртка) | MIT | ✅ Кандидат №1 для Android `.aar`; релиз v26.9.30 (30.09.2026) |
| amnezia-vpn/amnezia-libxray | MIT | ✅ Запасной кандидат (уже в [[OPEN_SOURCE]]), push 21.08.2026 |
| 2dust/AndroidLibXrayLite | **LGPL-3.0** | 🚫 Не брать: статическая сборка в APK тянет обязательства по перелинковке |
| 2dust/v2rayNG | **GPL-3.0** | 🚫 Запрещено правилом «без GPL в продукте»; код не копировать |
| heiher/hev-socks5-tunnel | MIT | ✅ Допустим, но не нужен (см. TUN ниже) |
| xjasonlyu/tun2socks | MIT | ✅ Допустим, но не нужен |
| eycorsican/go-tun2socks | MIT, **archived** | ⚠️ Заброшен — не брать (в [[OPEN_SOURCE]] был упомянут) |

**TUN без tun2socks:** с v26.1.23 (январь 2026) в Xray-core есть нативный `tun` inbound, включая
Android. Приложение передаёт fd от `VpnService` через переменную `XRAY_TUN_FD` до старта Xray.
Последний стабильный Xray-core — v26.3.27 (27.03.2026), TUN в нём есть. Отдельный tun2socks
не нужен. Петлю трафика (исходящие сокеты Xray уходят обратно в TUN) на Android закрывают
исключением собственного пакета из VPN (`addDisallowedApplication`).

**Cloudflare в РФ — критично для выбранной схемы:** по данным самого Cloudflare, с 09.06.2025
российские провайдеры режут соединения к IP Cloudflare примерно до **16 КБ на соединение**
(HTTP/1.1, HTTP/2, HTTP/3). Support-страница обновлена 23.04.2026 и подтверждает, что ограничение
действует, а Cloudflare вернуть доступ не может. Форумные отчёты с июня 2025: VLESS+WS через
Cloudflare в РФ перестал работать. Отдельные отчёты (март 2026) — часть провайдеров режет и
VLESS+WS+TLS напрямую; упоминается whitelist-фильтрация на мобильном интернете.

## Relevance to FocusVPN

- Движок Android: **Xray-core через libXray (MIT) + нативный TUN** — лицензионно чисто, без GPL/LGPL.
- **Cloudflare как CDN для пользователей в РФ — по первоисточнику не жизнеспособен.** Слой CDN
  нужно сделать настраиваемым (адрес/SNI/Host приходят из CP), а провайдера выбрать по полевой
  проверке. Транспорт тоже держать конфигурируемым (`ws` сейчас, `xhttp`/REALITY — без
  переписывания клиента), потому что блокировки меняются быстрее релизов.
- Решение — [[009-android-vless-only]], план — [[plans/E3-android-vless]].

## Related

- [[OPEN_SOURCE]] · [[002-vpn-engine-strategy]] · [[2026-08-11-awg-2-3-eval]] · [[MOC/Research]]
