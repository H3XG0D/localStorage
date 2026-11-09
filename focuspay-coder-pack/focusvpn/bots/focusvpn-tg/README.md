# FocusVPN Telegram bot

Отдельный бот VPN (как обменник FocusPay и казино FocusBet). Из бота FocusPay в него ведёт кнопка
«FocusVPN» в главном меню. Туннель бот не поднимает — это делает приложение.

## Env

```bash
export TELEGRAM_BOT_TOKEN=...
export FOCUSPAY_API_BASE=http://127.0.0.1:8000   # FocusPay exchange-backend (/api/internal/vpn)
export FOCUSPAY_INTERNAL_TOKEN=...                 # = INTERNAL_API_SECRET на FocusPay
export FOCUSVPN_API_BASE=http://127.0.0.1:8080
export FOCUSVPN_INTERNAL_TOKEN=...
export VPN_CLIENT_DOWNLOAD_URL=https://focuspay.org/vpn.apk   # если в админке не задан app_url
export FOCUSPAY_BOT_URL=https://t.me/<бот FocusPay>           # «Совершить обмен», «Пополнить»
export VPN_REMINDER_INTERVAL_SEC=600
export PREMIUM_EMOJI=auto          # off — обычные emoji, без tg-emoji
```

CP должен знать юзернейм этого бота: `FOCUSVPN_TELEGRAM_BOT_USERNAME` (deep link входа из приложения
`/start vpnauth_…`). Бот FocusPay — `VPN_BOT_USERNAME`.

## Run

```bash
cp .env.example .env   # fill tokens
pip install -r requirements.txt
python -m bot.main
```

## Smoke (no Telegram, stub FocusPay)

```bash
make smoke-e1-full
```

## Экраны

Цены, тарифы, сроки доп. устройства, триал, порог обменов и ссылка на APK — в админке FocusPay (`/x8/vpn`). Бот ничего не
считает сам и не продлевает подписку напрямую ([ADR-010](../../docs/adr/010-vpn-billing-saga.md)).

- **Меню** (`/start`, `/menu`): карточка статуса (до какой даты, сколько дней), баланс FocusPay,
  число устройств. Кнопки: пробный период (если ещё не взят), «Продлить подписку» (замок до порога
  обменов или приглашённых), устройства, код входа в FocusVPN, ключ ссылкой для Happ и похожих клиентов, приложение, инструкция, баланс, отзывы, обновить.
  Цвет кнопок и premium-emoji — `PREMIUM_EMOJI=auto|off`.
- **Приложение**: файл APK уходит в чат только при живой подписке или пробном периоде. Встроенный
  браузер Telegram файл не сохраняет, поэтому URL-кнопки на APK нет.
- **Баланс**: доступные рубли FocusPay и переход в бот обменника. Бот сам баланс не пополняет.
- **Тарифы** → карточка с ценой, ценой за день и скидкой → подтверждение с новой датой
  окончания → `POST /api/internal/vpn/purchase`. Один nonce на показ меню: двойное нажатие = одна покупка.
  Зелёная кнопка — у тарифа с наибольшей скидкой из админки.
- **Устройства**: список из CP, «Отвязать» с подтверждением (`POST /v1/internal/telegram/devices/revoke`)
  — VPN на старом телефоне отключается, можно войти на новом. При живой подписке и непустом списке
  сроков — «Ещё устройство»: срок с момента оплаты, подписка не продлевается (`POST /api/internal/vpn/device`).
- **Напоминания**: раз в `VPN_REMINDER_INTERVAL_SEC` бот берёт `GET /api/internal/vpn/expiring`
  («кончится через N ч» за 6 ч и «закончилась» в течение суток), отмечает `POST /notified` и только
  потом шлёт — без дублей.
