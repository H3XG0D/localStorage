---
type: spec
tags: [opensource, licenses, spec]
status: active
updated: 2026-10-07
---

# OPEN_SOURCE.md — проверенное исследование open-source компонентов для FocusVPN

> **Статус: ВЕРИФИЦИРОВАНО по актуальным upstream-репозиториям (10.08.2026).**
> Все лицензии и версии проверены напрямую через GitHub API и LICENSE-файлы репозиториев.
> Дата последней проверки каждого пункта указана в комментариях к таблице.

---

## 1. Цель

Мы не пишем собственный VPN-протокол и собственную криптографию. Выбираем проверенные
open-source движки (data plane), которые:

- реально работают и активно поддерживаются;
- проходят через сети РФ (стойкость к DPI);
- **позволяют строить коммерческий продукт с закрытым клиентским и серверным кодом**
  (или с управляемыми условиями копилефта).

Ключевая лицензионная дилемма: **копилэфт (GPL/AGPL) vs permissive (MIT/Apache/BSD)** и
**weak copyleft (MPL-2.0)**. Если код встраивается в наш продукт как библиотека — лицензия
компонента «тянет» наш код. Если вызывается как отдельный процесс/сервис — риск ниже, но
разбираться нужно по каждому случаю.

---

## 2. Сводная таблица (проверено 10.08.2026)

Легенда: ✅ встраиваем в закрытый коммерческий продукт | ⚠️ есть условия | 🚫 не встраивать в закрытый продукт без юрисконсульта/коммерческой лицензии

| Компонент | Repository | License | Что используем | Ограничения |
|---|---|---|---|---|
| **AmneziaVPN client** | github.com/amnezia-vpn/amnezia-client (v5.0.0.5, 26.07.2026) | **GPL-3.0** (подтверждено LICENSE) | Только как **референс архитектуры** (Qt/C++ клиент ↔ daemon ↔ привилегированный service) | 🚫 **Fork не делать**: обязывает раскрыть весь наш клиент под GPL-3.0. Как dependency не пригоден — это приложение, не библиотека. Клиент большой (Qt/C++/Kotlin/Swift), поддержка 5 платформ дорогая |
| **amneziawg-go** | github.com/amnezia-vpn/amneziawg-go **`v0.2.19`** (pin MVP; commit проверять при обновлении) | **MIT** (подтверждено LICENSE, Copyright 2017-2025 WireGuard LLC) | ✅ **Ядро протокола AmneziaWG** (userspace, Go). Встраиваемая библиотека для клиентов. На нодах peer-таблицы через `awg` (tools), не обязательно линковать go-движок в agent | Нет ограничений для коммерции. Форк wireguard-go + обфускация (junk Jc/Jmin/Jmax, рандомизация handshake, MTU). **MVP pin: tag `v0.2.19`** (AWG 1.x/1.5 param set, совместим с нашей схемой API). Upstream также публикует `v3.0.*` (AWG 3.0) — **не брать в MVP** без отдельного решения и расширения схемы (H/S/I / CPS); оценка в Phase 4 |
| **amneziawg-tools** | github.com/amnezia-vpn/amneziawg-tools | **GPL-2.0** (подтверждено COPYING) | CLI `awg` для конфигурирования интерфейса на нодах Linux | ⚠️ Вызываем как **отдельный процесс** на нодах (server-side). Не линкуем в наш код. Модификации распространяем под GPL |
| **amneziawg-windows** | github.com/amnezia-vpn/amneziawg-windows | **MIT** (подтверждено) | ✅ **Готовый туннель AmneziaWG для Windows** — embeddable DLL-сервис; работает через **wintun.dll** (userspace), без закрытого ядерного драйвера | Нет ограничений. В go.mod используется `golang.zx2c4.com/wintun`. Рекомендуемый способ встраивания AmneziaWG в Windows-клиент |
| **amneziawg-android** | github.com/amnezia-vpn/amneziawg-android | **Apache-2.0** (подтверждено) | ✅ База Android-реализации AmneziaWG | Нет ограничений для коммерческого закрытого клиента |
| **amneziawg-apple** | github.com/amnezia-vpn/amneziawg-apple | **MIT** (подтверждено) | ✅ AmneziaWG для iOS/macOS (Network Extension) | Нет ограничений |
| **amneziawg linux kernel module** | github.com/amnezia-vpn/amneziawg-linux-kernel-module | **GPL-2.0** (ядро Linux) | Опционально на нодах для максимальной производительности | Часть ядра — наш userspace-код лицензию ядра не наследует. Стандартная практика |
| **Xray-core** | github.com/XTLS/Xray-core (latest v26.3.27, 27.03.2026) | **MPL-2.0** (подтверждено LICENSE) | ✅ **Основной анти-DPI движок**: VLESS + REALITY (и XHTTP). Запускаем как отдельный процесс/бинарник | MPL — копилэфт **на уровне файлов**: только правленые нами файлы Xray открываем под MPL; весь остальной наш код закрыт. Модель «клиент ↔ сервер по Reality» нашего кода не раскрывает. Активно поддерживается |
| **amnezia-xray-core** | github.com/amnezia-vpn/amnezia-xray-core | **MPL-2.0** (подтверждено) | ✅ Форк Xray от Amnezia (активный, push 10.08.2026) — те же лицензионные свойства | Только файлы форка, которые правим, — под MPL. Либо не правим вовсе |
| **amnezia-libxray** | github.com/amnezia-vpn/amnezia-libxray | **MIT** (подтверждено) | ✅ **Встраиваемый Xray** (обёртка над amnezia-xray-core) для мобильных клиентов | MIT-обёртка, но внутри она вызывает MPL-ядро. Используем через готовую обёртку, не правим ядро |
| **XTLS/libXray** | github.com/XTLS/libXray (пин `v26.9.30`) | **MIT** (подтверждено GitHub API 07.10.2026) | ✅ **Вшит в Android** (`scripts/fetch-libxray-android.sh`, AAR не в git). Нативный TUN, fd в `xray.tun.fd` | MIT-обёртка, внутри немодифицированный Xray-core (MPL). NOTICE + ссылка на исходники |
| **Onest** | github.com/googlefonts/onest | **OFL-1.1** (OFL.txt, 07.10.2026) | ✅ Шрифт Android-клиента, веса 400–800 в `res/font` | Можно вшивать в APK. Нельзя продавать файлы шрифта отдельно. Текст лицензии: `clients/android/third_party/onest/OFL.txt`. [[2026-10-07-onest-font]] |
| **AndroidLibXrayLite** | github.com/2dust/AndroidLibXrayLite | **LGPL-3.0** (подтверждено GitHub API 07.10.2026) | — | 🚫 Не брать: статическая сборка в APK тянет обязательства LGPL по перелинковке |
| **v2rayNG** | github.com/2dust/v2rayNG | **GPL-3.0** (подтверждено GitHub API 07.10.2026) | — | 🚫 Не линковать и не копировать код |
| **hev-socks5-tunnel** | github.com/heiher/hev-socks5-tunnel | **MIT** (подтверждено GitHub API 07.10.2026) | Запасной TUN→SOCKS для Android | Нет ограничений; не нужен при нативном TUN Xray |
| **sing-box** | github.com/SagerNet/sing-box (branch `testing`) | **GPL-3.0-or-later** (подтверждено LICENSE) | Мощный универсальный движок (VLESS/Reality/WireGuard/TUN) | 🚫 Как **библиотеку** в закрытый клиент — нет (тянет под GPL-3.0). Как **отдельный процесс** — вероятно допустимо, но требует юрисконсульта. Держим как запасной вариант, если решим открыть клиент |
| **OpenVPN** | github.com/OpenVPN/openvpn | **GPL-2.0** + исключения линковки (OpenSSL/APL-2.0/LZO) (подтверждено COPYING) | Только резервный протокол на нодах (легаси-совместимость) | ⚠️ Как отдельный процесс, не линкуем. Приоритет низкий |
| **OpenVPNAdapter** | github.com/ss-abramchuk/OpenVPNAdapter | **AGPL-3.0** (подтверждено через THIRD_PARTY_LICENSES.md Amnezia) | — | 🚫 **AGPL-3.0 на iOS — критический риск**, если вдруг понадобится OpenVPN на iOS. Не использовать |
| **wireguard-go** | github.com/WireGuard/wireguard-go | **MIT** (подтверждено) | ✅ Запасной/доп. протокол WireGuard (userspace, Go) | Нет ограничений. Проще AmneziaWG, но без обфускации от DPI |
| **wireguard-android** | github.com/WireGuard/wireguard-android | **Apache-2.0** (подтверждено) | ✅ **База нашего Android-клиента** (Kotlin + VpnService): форкнуть и заменить движок на amneziawg-go, добавить Xray | Apache-2.0 позволяет закрытый коммерческий форк. Активная поддержка (push 29.06.2026) |
| **wireguard-apple** | github.com/WireGuard/wireguard-apple | **MIT** (подтверждено) | ✅ **База нашего iOS/macOS-клиента** (Swift + Network Extension): форкнуть, заменить движок | MIT — закрытый коммерческий форк допустим |
| **wireguard-tools** | github.com/WireGuard/wireguard-tools (`wg`, `wg-quick`) | **GPL-2.0** (подтверждено) | Управление WireGuard-интерфейсами на нодах | ⚠️ Как отдельный процесс, не линкуем |
| **wintun** | git.zx2c4.com/wintun (зеркало github.com/WireGuard/wintun) | Исходники **GPL-2.0**; **предсобранные бинарники — отдельная лицензия WireGuard LLC** (подтверждено COPYING + prebuilt-binaries-license.txt) | ✅ **TUN-адаптер Windows** для AmneziaWG/WireGuard: кладём `wintun.dll` рядом с продуктом и используем публичный API (`wintun.h`) | ⚠️ Бинарник НЕ модифицировать, НЕ редистрибутить сам по себе; разрешено распространять «рядом с ПО, использующим только Permitted API». Именно так делают коммерческие VPN (Mullvad/Nord и др.). Не линкуем в наш код, только `LoadLibraryEx` + динамический вызов |
| **tun2socks** | github.com/eycorsican/go-tun2socks | **MIT** (подтверждено через Amnezia) | ✅ Транспорт TUN→SOCKS/локальный стек для Android/Linux | Нет ограничений |
| **Mullvad split-tunnel driver** | github.com/mullvad/win-split-tunnel | **GPL-3.0 / MPL-2.0** (подтверждено через Amnezia) | Split-tunneling приложений на Windows | ⚠️ Драйвер ядра Windows: использовать как бинарник/подписанный драйвер, модификации — под GPL. Держим на более поздний этап |
| **Cloak / Shadowsocks-libev** | cbeuw/Cloak, shadowsocks/shadowsocks-libev | GPL-3.0 / GPL-3.0-or-later | Легаси-обфускация OpenVPN | ⚠️ Низкий приоритет; только как отдельные процессы |

### Комментарии по проверке (что изменилось относительно черновика)

1. **`amneziawg-go` — MIT, а не GPLv2.** Это самый важный факт: ядро протокола AmneziaWG
   можно встраивать в наш закрытый клиент как Go-библиотеку без обязательства открывать код.
2. **Windows AmneziaWG — не закрытый драйвер.** Реализация `amneziawg-windows` (MIT) —
   embeddable DLL-сервис поверх `wintun.dll` (userspace). Закрытого ядерного драйвера в текущем
   стеке нет. (В ранних версиях Amnezia использовала закрытый подписанный драйвер — но в текущем
   коде его нет; это снимает зависимость от вендора.)
3. **`wintun` — не MIT.** Исходники GPL-2.0, а предсобранный `wintun.dll` — под отдельной
   лицензией WireGuard LLC (Prebuilt Binaries License). Она разрешает коммерческое использование,
   но только через публичный API и только «рядом» с нашим продуктом. Это стандарт индустрии.
4. **sing-box — GPL-3.0-or-later** (подтверждено). Как библиотеку в закрытый клиент не берём.
5. **OpenVPN — GPL-2.0 с исключениями линковки** (OpenSSL, Apache-2.0-библиотеки, LZO) —
   для связки с OpenSSL проблем нет; но сам протокол в нашем стеке — низкий приоритет.
6. **OpenVPNAdapter (iOS) — AGPL-3.0** — не использовать; если нужен OpenVPN на iOS, только через
   собственный отдельный процесс и консультацию юриста.
7. **Базы для своих клиентов:** `wireguard-android` (Apache-2.0) и `wireguard-apple` (MIT) —
   пермиссивные форки, на которых строим наши клиенты с движком AmneziaWG.

---

## 3. Лицензионная стратегия FocusVPN

1. **В закрытый клиент/сервис встраиваем только MIT/Apache/MPL**:
   - amneziawg-go (MIT) — движок AmneziaWG;
   - Xray-core / amnezia-xray-core (MPL-2.0) — движок VLESS+REALITY (через отдельный процесс
     или amnezia-libxray MIT-обёртку);
   - wireguard-go (MIT) — запасной протокол;
   - wintun.dll — по лицензии Prebuilt Binaries (публичный API, side-by-side).
2. **GPL-компоненты (wg/wg-quick/awg/OpenVPN/kernel-модуль) — только как отдельные процессы на
   нодах и серверах**, не линкуем, модификации не распространяем (или открываем под GPL).
3. **GPL-3.0/AGPL-компоненты в закрытом продукте не используем** (amnezia-client как fork,
   sing-box как библиотека, OpenVPNAdapter).
4. **MPL-файлы, которые правим, помечаем и открываем под MPL** (обычно править Xray не нужно —
   конфигурируем через JSON).
5. **Никакой собственной криптографии** — только реализованные в движках алгоритмы.
6. **Замораживаем версии движков** (vendoring / `go.sum`, фиксированные релизы xray), ведём
   `NOTICE.md`/`THIRD_PARTY_LICENSES.md` с происхождением каждого компонента — это требование и
   для стора, и для аудита перед коммерческим запуском.

### 3.1 Зафиксированные версии (MVP / Phase 2)

| Компонент | Pin | Примечание |
|---|---|---|
| amneziawg-go | **`v0.2.19`** | Клиентский userspace; схема Jc/Jmin/Jmax + H/S/I (P4-M8) |
| amneziawg-tools (`awg`) | совместимый с pin go / distro package; версия фиксируется в `DEPLOYMENT.md` при bootstrap | Node Agent управляет интерфейсом через subprocess |
| Upstream AWG 3.0 (`v3.0.20260805` и новее) | **отложено** | Требует ADR + module `…/amneziawg-go/v3`; eval: [[2026-08-11-awg-2-3-eval]] |

---

## 4. Вывод по стратегии «какой путь брать»

| Критерий | Fork amnezia-client | Собственный клиент на пермиссивных движках |
|---|---|---|
| Лицензия | GPL-3.0 — весь клиент обязан быть открыт | Полностью закрытый продукт |
| Скорость до MVP | Быстро (готовый клиент), но переписать UI под бренд — большой объём | Медленнее на старте, зато один раз |
| Поддержка 5 платформ | Тянем чужую Qt-кодовую базу | Наши тонкие клиенты, меньше кода |
| Зависимость от Amnezia | Полная (каждый upstream-апдейт — merge) | Никакой (движки стабильны, обновляем сами) |
| White-label/бренд | Ограничен GPL-3.0 | Свободен |
| **Итог** | **Отклонено** | **Рекомендуется** |

**Рекомендация:** свой клиент на базе `wireguard-android` (Apache-2.0) + `wireguard-apple` (MIT)
с заменой движка на `amneziawg-go` (MIT) и добавлением `xray-core` (MPL-2.0) для VLESS+REALITY.
Desktop-клиенты пишем самостоятельно (Go-движок + тонкий UI). Это единственный путь, при котором
мы сохраняем закрытость кода, контроль над UX и право публиковаться в App Store / Google Play.

## Связано

- [[MOC/Research]] · [[ARCHITECTURE]] · [[CLIENT_ARCHITECTURE]] · [[002-vpn-engine-strategy]] · [[003-client-strategy]] · [[2026-08-10-amneziawg-versions]]
