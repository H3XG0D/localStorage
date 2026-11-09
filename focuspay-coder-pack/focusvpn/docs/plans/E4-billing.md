---
type: plan
tags: [plan, billing, ecosystem, focuspay]
status: active
updated: 2026-10-08
---

# E4 — Бухгалтерия VPN ⇄ FocusPay

**Доп. устройство и кнопка в боте FocusPay выложены 08.10.2026.** Подписка — одно место. Покупка `kind=device` добавляет ещё одно на свой срок. Цены — `device_addons` в `/x8/vpn`. Миграции на проде: CP `000010`, FocusPay `add_vpn_device_kind.sql`. Бэкап `/opt/backups/vpn-20261008T072908Z`. В главном меню бота FocusPay кнопка «FocusVPN» открывает @focusvpn1_bot.

**Статус: выложено на focuspay 07.10.2026** (CP, бэкенд FocusPay, бот @focusvpn1_bot, `/x8/vpn`).
Кнопка в боте FocusPay на проде нет. Прибыль VPN в обзоре и `/dash`, рефералка (общая лесенка 5% → 20%) и кешбэк покупателя — в локальном коде FocusPay с 08.10.2026, на focuspay не выложены. Решение — [[010-vpn-billing-saga]]. Бэкап `/opt/backups/vpn-20261007T162839Z`.

## Что сделано

| Где | Что |
|---|---|
| FocusPay `migrations/add_vpn_purchases.sql` | таблица `vpn_purchases` (held → granted → paid / released / failed) |
| FocusPay `vpn_billing.py` | тарифы, гейт, сага покупки и триала, `reconcile_loop` |
| FocusPay `/api/internal/vpn/*` | `GET /plans`, `GET /status/{tg}`, `POST /purchase`, `POST /trial`; старые `quote/hold/confirm/release/crypto-*` → 410 |
| FocusPay `/api/admin/vpn/*` | `summary`, `settings` (GET/PUT), `purchases`, `reconciliation` |
| FocusPay админка `/x8/vpn` | вкладки «Сводка», «Тарифы и триал», «Покупки», «Сверка» |
| FocusPay PnL | `vpn_revenue_rub` в `total_net` |
| CP миграция `000009` | `billing_events`: `kind`, `plan_code`, `amount_kopecks`, `ends_at`; один триал на юзера; планы month/q3/trial |
| CP `/v1/internal/billing/*` | `POST grant`, `GET grants/{id}`, `GET grants?since=`, `GET status`; `extend` удалён |
| CP доступ | без живой подписки 402; планировщик истекает подписки |
| Бот | меню тарифов с nonce (двойное нажатие = replay), кнопка триала, тексты отказов |

## Итерация 2 — меню VPN в отдельном боте (07.10.2026)

Решение: VPN живёт в отдельном боте `bots/focusvpn-tg` (@focusvpn1_bot), как казино FocusBet;
в боте FocusPay — только кнопка «FocusVPN» в главном меню: прогресс обменов и ссылка
`https://t.me/<VPN_BOT_USERNAME>?start=fp`.

| Где | Что |
|---|---|
| FocusPay `vpn_billing.py` | гейт по **завершённым обменам** (`orders` PAID/COMPLETED), ключи `purchase_min_exchanges` (10) и `trial.min_exchanges` (0 — триал всем); старые `*_min_deposits` читаются; `app_url`; карточки тарифов (цена за день, скидка); `subscription_view`; напоминания `due_reminders` / `mark_reminded` |
| FocusPay миграция `add_vpn_notifications.sql` | журнал отправленных напоминаний, PK `(telegram_id, kind, ends_at)` |
| FocusPay `/api/internal/vpn/*` | расширенный `status`, `GET /expiring`, `POST /notified` — [[API]] §9.1 |
| FocusPay `/api/admin/vpn/*` | `summary.sales.daily` (30 дней), `GET user/{tg}`, `POST user/{tg}/devices/{id}/revoke` |
| FocusPay админка `/x8/vpn` | редизайн: KPI, график продаж, карточки нод с нагрузкой, карточки тарифов с ценой за день и скидкой, блоки «Доступ к покупке» / «Пробный период» / «Приложение», статус-чипы покупок, сверка по группам («Всё сходится»), вкладка «Пользователь» (подписка, обмены, устройства с отвязкой, покупки) |
| CP | `GET billing/ending`, `GET telegram/devices`, `POST telegram/devices/revoke` |
| Бот FocusPay | кнопка «FocusVPN» (`services/focusvpn_link.py`), env `VPN_BOT_USERNAME` |
| Бот VPN | главный экран (статус, до какой даты, баланс, прогресс ▰▱ «3 из 10»), тарифы с замком до 10 обменов, карточка → подтверждение «Списать N ₽» с новой датой, устройства с отвязкой, код входа, скачать приложение, `/menu`; фоновые напоминания «кончится через N ч» / «закончилась» (`bot/reminders.py`) |

## Тарифы по умолчанию

Неделя 7 дн / 300 ₽ · Месяц 30 дн / 990 ₽ · 3 месяца 90 дн / 2490 ₽. Триал 1 день, вкл.
Гейт (итерация 2): 10 завершённых обменов для покупки; триал — всем (0), один раз на аккаунт.
Обход гейта для тестов — `VPN_GATE_ALLOWLIST` (старое имя `VPN_DEPOSIT_GATE_ALLOWLIST` читается). Для человека — кнопка «Снять ограничение» на вкладке «Пользователь»: id пишется в `app_settings.vpn_trusted_ids`, оплата с баланса остаётся. Выложено на focuspay 08.10.2026, бэкап `/opt/backups/vpn-trusted-20261008T093116Z`.

## Ревью-фиксы в этой же итерации

- CP: перевыпуск конфига атомарный (`ReplaceActiveConfiguration`); повторное подключение к живой
  VLESS-ноде перевыпускает конфиг со свежим списком серверов; канон протокола `vless`
  (`vless-ws`/`xray` — алиасы); `vlessSetHash` сохраняется только после успешного уведомления нод;
  отчёт: окна включительные, триалы считаются отдельно (`trials_30d`); аллокация без UUID
  (до `000008`) заменяется при подключении.
- node-agent: трафик Xray без `-reset`, дельта от принятых CP счётчиков + `boot`/`seq` (CP
  засчитывает повтор только на прирост); подтверждения пиров не теряются при сбое POST;
  `AGENT_XRAY_RESYNC_INTERVAL` (60 с) повторно применяет пользователей после рестарта Xray.
- Android: одна попытка подключения за раз (однопоточный worker + поколение), `onRevoke`/`onDestroy`
  сообщают Down, отключение через `ACTION_DISCONNECT`, повторное нажатие «Подключить» игнорируется.

## Проверка

```
make test vet && make test-integration
make smoke-e1-billing smoke-e1-full
make android-check license-check
cd ~/Desktop/focuspay/site/exchange-backend && .venv/bin/python -m pytest tests/test_vpn_billing.py
cd bots/focusvpn-tg && PYTHONPATH=. <venv>/python -m pytest
cd ~/Desktop/focuspay/bot/tg_bot_btc && <venv>/python -m pytest tests/test_focusvpn_link.py
cd ~/Desktop/focuspay/focussite/frontend && npx tsc --noEmit -p tsconfig.app.json
```

## Выкладка 07.10.2026

Сделано: бэкапы, CP миграция 9 и новый сервер, node-agent на DE1 (HEALTHY), таблицы `vpn_purchases` и
`vpn_notifications`, `vpn_billing.py` + `internal_vpn.py` + новый `admin_vpn.py`, точечная правка прод-`main.py`,
бот VPN на :8000, панель `/x8/vpn`. С сервера API отвечает 200. Бот FocusPay и PnL не трогали.
Живой прогон кнопок в Telegram — за человеком.

## Деплой (только по отдельной команде «деплой»)

1. Бэкап обеих БД (`focusvpn`, `exchange_bot`).
2. FocusPay: применить `migrations/add_vpn_purchases.sql` и `add_vpn_notifications.sql`, выложить
   бэкенд, фронт и бот FocusPay (`VPN_BOT_USERNAME=focusvpn1_bot`).
3. CP: `migrate up` (000009), выложить сервер; node-agent на нодах обновить.
4. Существующим пользователям — триал (открыт всем) или allowlist, иначе 402.
5. Бот VPN: `FOCUSPAY_BOT_URL`, `VPN_REMINDER_INTERVAL_SEC`, перезапуск `focusvpn-bot`.
6. Проверить `/x8/vpn` → «Сверка»: «Всё сходится».

## Связано

- [[010-vpn-billing-saga]] · [[plans/E1-vpn-bot]] · [[007-ecosystem-billing-federation]] · [[CURRENT_TASK]] · [[TODO]]
