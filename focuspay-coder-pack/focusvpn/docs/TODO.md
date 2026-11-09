---
type: hub
tags: [hub, todo]
status: active
updated: 2026-10-12
---

# FocusVPN — TODO / известные проблемы

Проблемы, найденные в ходе работы. Классификация после context audit (10.08.2026).

---

## Blockers

*(Пусто. Phase 2 M1–M5 complete. Phase 3 ждёт явного APPROVED — START PHASE 3.)*

---

## Risks

- [x] **Ключ ссылкой на focuspay** — миграция 12, CP и бот перезапущены 12.10.2026.
      Бэкап `/opt/backups/focusvpn-db-20261012T172955Z.dump`. [[013-happ-subscription-link]]
- [ ] **Ключ подписи Android только на этой машине** — `secrets/android-release.keystore` (gitignored).
      Потеря ключа значит, что уже установленный APK с `https://focuspay.org/vpn.apk` нельзя обновить
      поверх: только удалить и поставить заново. Сделать копию ключа и пароля вне репозитория.

- [ ] **CLI AmneziaWG и macOS всё ещё full-tunnel** — российский трафик с этих клиентов уходит на ноду.
      GUI Linux и Windows (VLESS) и Android пускают RU мимо туннеля ([[011-ru-direct]]).
- [ ] **DE1: root-пароль засвечен в чате** — сменить (`passwd`), затем добавить свой SSH-ключ и
      выключить вход по паролю. Важно: `/etc/ssh/sshd_config.d/50-cloud-init.conf` содержит
      `PasswordAuthentication yes` и читается первым — правка только `60-*` не поможет.
- [ ] **DE2: сменить пароль в панели хостера** — SSH по паролю уже выключен (`00-focusvpn.conf`),
      ключ `~/.ssh/focusvpn_node_de2`. Пароль root был в чате и всё ещё открывает консоль панели.
- [ ] **NL1: сменить пароль в панели хостера** — SSH по паролю уже выключен (`00-focusvpn.conf`),
      ключ `~/.ssh/focusvpn_node_nl1`. Пароль root был в чате и всё ещё открывает консоль панели.
- [ ] **VLESS+WS deprecated в Xray** — на ноде параллельно XHTTP; выбрать по итогам этапа 0 [[plans/E3-android-vless]].
- [x] **vless_uuid в БД открытым текстом** — миграция `000008`: колонка `vless_uuid_enc` (конверт KEK),
      в индексе только SHA-256. ✅ 2026-10-07
- [x] **Страница VPN в живой админке** — `/x8/vpn` выложена 07.10.2026 (`deploy_all.py`, панель `panel-DRnE3gpM.js`). ✅
- [x] **Бот FocusVPN на focuspay** — @focusvpn1_bot, сервис `focusvpn-bot`, env `/etc/focusvpn/bot.env` (07.10.2026).
- [ ] **Перевыпустить токен бота** — токен засветился в чате и в journald `focusvpn-bot` (старые строки
      httpx до фикса). `/revoke` в BotFather → обновить `/etc/focusvpn/bot.env` и `bots/focusvpn-tg/.env`.
- [x] **Меню бота без FocusPay** — на проде `/api/internal/vpn/status` отвечает 200, бот смотрит на :8000. ✅ 07.10.2026
- [x] **E4: миграции FocusPay на проде** — `add_vpn_purchases.sql` и `add_vpn_notifications.sql` применены
      к `exchange_bot` 07.10.2026. На sandbox не применялись.
- [x] **E4: доступ после деплоя** — триал открыт всем; в CP на момент выкладки 0 подписок и 1 устройство.
- [x] **Кнопка «FocusVPN» в боте FocusPay** — выложена 08.10.2026, `VPN_BOT_USERNAME=focusvpn1_bot`. ✅
- [x] **E4: выручка VPN в PnL** — на focuspay с 08.10.2026: продажи подписки и доп. мест, минус рефералка и кешбэк. Реквизитный пул не выкладывался. ✅
- [x] **Докупка устройства** — выложена 08.10.2026 (CP `000010`, FocusPay `add_vpn_device_kind.sql`). ✅
- [ ] **FocusPay бот: тест `test_partner_referrer_still_gets_tickets` зависит от даты** — кампания
      в тесте кончилась 31.07.2026, тест падает не из-за кода.
- [x] **E4: деплой** — 07.10.2026, бэкап `/opt/backups/vpn-20261007T162839Z`, CP `000009`, бэкенд FocusPay,
      бот @focusvpn1_bot, `/x8/vpn`, node-agent DE1. Кнопку основного бота не трогали. [[plans/E4-billing]]
- [ ] **E4: hold без ответа CP** — деньги заморожены до успешного reconcile; если CP лежит долго,
      смотреть «Сверка» → `pending` в `/x8/vpn`.
- [ ] **E4: дедуп трафика по `seq` в памяти CP** — после рестарта CP один повтор может засчитаться
      целиком (мелкая погрешность отчёта).
- [ ] **Сырые VLESS UUID до `000008`** — колонка удалена миграцией; такие аллокации CP заменяет при
      следующем подключении. Re-encrypt шага нет — данных для него не осталось.
- [ ] **FocusPay pytest: 6 падений вне VPN** — `test_operator_live_ops` (BalanceAdjust ×3),
      `test_buyer_profile_service`, `test_payin_requisite_rail`, `test_shift_stats_role_split`;
      VPN/PnL-тесты зелёные. Разобрать в FocusPay.
      API бота: `http://127.0.0.1:18080`, внутренний токен уже в `/etc/focusvpn/env`.
- [ ] **DE1 на sslip.io** — для CDN-проверки нужен свой домен; sslip.io могут заблокировать целиком.

- [ ] **Прод-инвентарь в docs** — IP/SKU/SSH alias боевых хостов не должны попадать в архивы
      и внешние чекауты. Для передачи кода — sanitized pack (без `.git`, `.continue/`,
      `.env`, прод-IP). Не коммитить ключи из `.continue/`.
- [ ] **AmneziaWG: производительность userspace на ноде** — MVP path: `awg` + опц. kernel-модуль
      (GPL, не в продукте). Следить за load. [ADR-002]
- [ ] **Лицензионный гейт при сборке клиентов** — ~~риск~~: `make license-check` (pin
      amneziawg-go v0.2.19 + NOTICE). Полный THIRD_PARTY text dump — later pre-store.
- [x] **awg subprocess vs go embed** — P4-M1: product default = amneziawg-go; awg opt-in.
- [ ] **Задержка CP↔Node** — long-poll 30s + Redis wake; тюнинг при нагрузке; `409 stale_version`.
      [ADR-004] [DECISIONS.md]
- [ ] **Секреты / KMS** — Phase 2 MVP: file-backed KEK в `secrets/`; prod Secret Manager до
      прод-админки. [SECURITY.md §4.2] [[plans/M3]]
- [ ] **Дрейф клиентских кодовых баз** — `clients/shared/` с Phase 2 (контракты + CLI); UI Phase 3.
- [x] **Git инициализирован** (пустое repo + `.gitignore` для secrets/keys/env) — первый commit
      и monorepo skeleton при явном старте Phase 2.
- [x] **Upstream AWG 2.0/3.0 eval** — [[2026-08-11-awg-2-3-eval]]: stay on `v0.2.19`; v3 only with ADR + module path `…/amneziawg-go/v3`.
      [OPEN_SOURCE.md §3.1] [docs/research/]
- [ ] **Go toolchain 1.25** — поднят вынужденно (`golang.org/x/crypto` v0.54.0 требует >=1.25).
      Зафиксировано в `go.mod`. [docs/research/2026-08-10-go-dependencies-m1.md]
- [x] **In-memory store — только тесты/CLI** — Postgres реализован в M2; `FOCUSVPN_STORE=postgres`
      **без тихого fallback** (fatal при недоступной БД). memory остаётся test-only. [DATABASE.md §0]
- [x] **Реальный handshake Android (07.10.2026)** — эмулятор (APK + `libwg-go.so` v0.2.19) ↔
      userspace AmneziaWG-пир на gVisor netstack (`.scratch/awgserver`, без root): handshake, ping
      3/3, HTTP 200 изнутри туннеля, адрес клиента выдан IPAM CP. Попутно найдены и исправлены
      4 блокера туннеля — см. [[DECISIONS]] 07.10.2026 (проверка). **Не проверено:** живая FR-нода
      с node-agent и CLI-путь `FOCUSVPN_E2E_REAL_TUNNEL=1` (нет `awg-quick`, нет sudo на dev).
- [x] **Android SDK на dev-машине** — `~/Android/Sdk` (platform 35, build-tools 35, эмулятор,
      AVD `fv35`). Сборка: `JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ANDROID_HOME=~/Android/Sdk`.
- [ ] **UI «Подключено» ≠ туннель поднят** — `connected=true` ставится, когда CP выдал конфиг, а не
      после handshake. При сбое `awgTurnOn` сервис теперь гасит TUN (без чёрной дыры), но экран
      может показывать ON. Нужен статус из `FocusVpnService` в UI.
- [ ] **`internal_vpn.py`: поиск hold по `LIKE '%order%'`** — не через `casino_finance._hold_order_ids()`;
      крипто-инвойсы (`_CRYPTO`) в памяти процесса — теряются при рестарте, реального крипто-rail нет.
- [ ] **VLESS в CP — заглушка** — `connections.xrayPart` отдаёт `"uuid": "assigned-device-side"`,
      путь `/vpn-<alloc>` не совпадает с `infra/node/xray/server.json`; node-agent Xray не знает.
      Закрывается этапами 1–2 [[plans/E3-android-vless]].
- [ ] **CDN для РФ** — Cloudflare режет соединения из РФ до ~16 КБ ([[2026-10-07-android-vless-xray]]).
      Провайдер CDN и транспорт выбрать полевой проверкой до кода E3.
- [ ] **`eycorsican/go-tun2socks` archived** — упомянут в [[OPEN_SOURCE]] как транспорт; заброшен
      с 2021. Для Android не нужен (нативный TUN в Xray), не брать.
- [ ] **Боевые ключи нод** — seed кладёт DEV pubkey (32 байта, но не реальные); на проде pubkey
      должен прийти от node-agent (M4 confirm path), иначе handshake невозможен.
- [ ] **Provisioning подписок** — в MVP нет self-serve API создания подписки; подписки заводятся
      seed/админом. Лимит устройств у юзера без подписки = план `free` (fallback). Billing — Phase 5. [DECISIONS.md M2]
- [ ] **sqlc отложен** — в M2 ручной SQL на `pgx`; вернуться к codegen при росте числа запросов. [DECISIONS.md M2]
- [x] **`vpn_endpoints.public_key`/`state`** — M3 A1 DEV pubkey; M4 agent confirm path; seed pubkey
      fixed to 32 bytes (M5). Never store server private keys on CP.
- [ ] **Podman socket для compose** — провайдер требует активный rootless-сокет
      (`systemctl --user enable --now podman.socket`). Задокументировано в DATABASE.md §0.
- [x] **Canonical signing / envelope framing** — approved in [[plans/M3]] §17-D (`MVN1` + sorted JSON);
      freeze after first implementation; dual-read via `format_version` if changed later.
- [x] **M3 auto-active must stay dev-scoped** — prod default false; agent telemetry activates (M4);
      smoke harness may set `FOCUSVPN_ALLOCATION_AUTO_ACTIVE=true` for memory-only E2E.

---

## Future work (не Phase 2)

- [ ] Email-верификация, CAPTCHA при регистрации.
- [ ] 2FA для админов (обязательно до открытия **прод**-админки; не gate Phase 2 MVP).
- [ ] NodeSelector по стране/региону, несколько нод, failover.
- [~] WireGuard и REALITY как движки (клиенты + ноды) — **WG P4-M2 + Xray client P4-M3 done**;
      node-side Xray apply / CP `parts.xray` seed — later; ноды WG later.
- [ ] Billing-провайдеры, полноценные подписки.
- [ ] **Интеграция с FocusPay (экосистема)**: единая база пользователей двух проектов +
      пополнение баланса / оплата VPN из Telegram-бота-обменника. Потребует ADR
      (account-linking Telegram id ↔ user, контракт API пополнения). Детали —
      `~/Documents/brain/Ecosystem/Integration-users-balance.md`. Делать после биллинга (Phase 5).
- [ ] Kubernetes / автономный деплой нод (отдельный ADR при необходимости).
- [ ] Kill switch / Always-on / DNS leak UI (клиенты Phase 3+).
- [ ] ASN/subnet blocking playbook (Phase 4).

---

## Phase 2 deliverables (не «отложено»)

Эти пункты входят в Phase 2 и отслеживаются в ROADMAP §2, не здесь как «future»:

- [x] Envelope encryption + Ed25519 config signing — **M3 done**
- [x] mTLS agent + `awg` peer apply — **M4 done**
- [x] CLI connect/disconnect + full tunnel E2E — **M5 done** (`make smoke-e2e`)
- [x] SECURITY.md §11.1 MVP checklist — **M5 done** (Redis RL / public TLS / admin audit → pre-prod)

## Связано

- [[Home]] · [[CURRENT_TASK]] · [[ROADMAP]] · [[plans/M3]] · [[MOC/Execution]] · [[SECURITY]]
