---

kanban-plugin: board

---

## Backlog

- [ ] Launch-L1: DNS + wizard + distribute builds #focusvpn
- [ ] SECURITY §11.1 MVP-чеклист перед демо #focusvpn
- [ ] E1: VPN bot + tokens в prod (после Launch) #focusvpn
- [x] Оллама 7B на бывшей DE1 `94.26.83.74` для Ops AI, не на biz ✅ 2026-10-09
- [x] E3 этап 0: тестовая нода DE1 (VLESS WS + XHTTP, `scripts/node-vless-setup.sh`) ✅ 2026-10-07
- [x] Вторая локация DE2 (Франкфурт, VLESS, агент HEALTHY) ✅ 2026-10-08
- [ ] DE2: сменить пароль root в панели хостера (SSH по паролю уже выключен) #focusvpn [[Team/Я]]
- [x] Локация NL1 (Амстердам, VLESS, агент HEALTHY) ✅ 2026-10-08
- [ ] NL1: сменить пароль root в панели хостера (SSH по паролю уже выключен) #focusvpn [[Team/Я]]
- [ ] E3 этап 0: полевая проверка WS vs XHTTP с РФ SIM / домашнего (ссылки `.scratch/node-de1/`) #focusvpn [[Team/Я]]
- [ ] E3 этап 0: свой домен + проверка через Cloudflare / Gcore #focusvpn [[Team/Я]]
- [ ] DE1: сменить root-пароль, SSH-ключ, выключить вход по паролю #focusvpn [[Team/Я]]
- [ ] E3: Android на VLESS (Xray) — после этапа 0, [[plans/E3-android-vless]] #focusvpn
- [x] Кнопка «FocusVPN» в боте FocusPay #focusvpn ✅ 2026-10-08
- [x] Выложить докупку устройства: CP `000010`, FocusPay `add_vpn_device_kind.sql`, бот и `/x8/vpn` #focusvpn ✅ 2026-10-08
- [x] Доверенный аккаунт: покупка VPN без 10 обменов и 30 приглашённых, кнопка в `/x8/vpn` #focusvpn ✅ 2026-10-08

## В работе

- [ ] Order FR dedic PAR-SM5038 (VPN traffic only) #focusvpn 📅 2026-08-13 [[Team/Я]]
- [ ] Provision: CP on focuspay 153.80.249.77 + node on FR #focusvpn 📅 2026-08-13 [[Team/Я]]

## Готово

- [x] Infra-TwoHost topology locked (biz live + FR to buy) ✅ 2026-08-12
- [x] Launch test topology decided: CP@FocusPay + 1 traffic VPS ✅ 2026-08-12
- [x] M1: auth vertical slice (register/login/refresh/reuse detection) ✅ 2026-08-10
- [x] M2: PostgreSQL store + миграции + seed + devices + /v1/me ✅ 2026-08-10
- [x] M3: servers / connections / allocations / ConfigParts #focusvpn ✅
- [x] M4: node-agent mTLS / long-poll / awg / telemetry #focusvpn ✅
- [x] M5: CLI connect/disconnect + E2E #focusvpn ✅
- [x] E4: бухгалтерия VPN ⇄ FocusPay в коде (тарифы, триал, гейт, сверка, PnL) #focusvpn ✅ 2026-10-07
- [x] E4.2: меню VPN в отдельном боте, гейт 10 обменов, триал всем, отвязка устройств, напоминания, редизайн `/x8/vpn` (в коде) #focusvpn ✅ 2026-10-07
- [x] Докупка устройства на свой срок, цены в `/x8/vpn` (в коде, на focuspay не выложено) #focusvpn ✅ 2026-10-08
- [x] E4: бухгалтерия и меню бота VPN выложены на focuspay (без кнопки в боте FocusPay) #focusvpn ✅ 2026-10-07
- [x] E2: Android dark UI + Telegram login + 1 device + FocusPay VPN wallet #focusvpn ✅ 2026-10-07
- [x] Rename MYVPN → FocusVPN ✅ 2026-08-11
**Complete**


%% kanban:settings
```
{"kanban-plugin":"board","list-collapse":[false,false,false]}
```
%%
