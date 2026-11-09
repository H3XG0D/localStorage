# QR СБП — пакет для кошелька

Снято с бота обменника как есть, без нового API. В боевом боте входов больше нет.
Таблицы `qr_sbp_payments` в базе обменника не удалялись.

## Куда класть

Скопировать `services/qr_pay_*.py` в `services/` кошелька. Они импортируют соседние модули обменника, отдельно этот каталог не запускается.

Оплата идёт через `services.finance666_client.qr_pay(transaction_id)`. Клиент провайдера остался в боте обменника (`bot/tg_bot_btc/services/finance666_client.py`): его тоже нужно скопировать вместе с `verify_finance666_webhook` из `webhook_security.py`.

## Что ещё нужно кошельку

- `handlers/owner_qrpay.py` — команда `/qrpay` и callback `^qrpay:`.
- `http_routes.py` — `mount(app)` вешает `/webapp/qrpay`, `/webapp/api/qr/check`, `/webapp/api/qr/pay` и `/webhooks/finance666`.
- `webapp/qrpay/index.html` — страница кнопки.
- `migrations/add_qr_sbp_payments.sql` — таблицы. На базе обменника уже накатана, второй раз не выполнять.
- Геттеры настроек, которые модули берут из `services.runtime_settings`: `qr_pay_enabled`, `qr_pay_markup_pct`, `qr_pay_max_rub_per_tx`, `qr_pay_max_rub_per_day`, `qr_pay_min_merchant_usdt`, `qr_pay_low_balance_allowlist`, плюс `save_settings`. Из `services.config_rates`: `QR_PAY_ENABLED`, `QR_PAY_MARKUP_PERCENT`, `QR_PAY_MAX_RUB_PER_TX`, `QR_PAY_MAX_RUB_PER_DAY`, `QR_PAY_MERCHANT_MIN_USDT`, `QR_PAY_LOW_BALANCE_ALLOWLIST`, `FINANCE666_*`, `TELEGRAM_BOT_TOKEN`.
- Общий баланс: `services.user_unified_balance.unified_available`.
- Пул: `services.db.get_pool`. Фоновые задачи: `qr_pay_poll_task` и `qr_pay_balance_monitor_task` из `qr_pay_poll.py`, стартовать когда `finance666_client.configured()`.

Тесты (`tests/test_qr_pay_*.py`) рассчитаны на запуск из каталога бота с этими импортами.

## Баг суточного лимита

`spent_today_rub` считает `REFUNDED`. В кошельке оставить только `RESERVED` и `SETTLED`.
