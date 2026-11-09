# FocusCasino Bot

Telegram-бот казино, интегрированный с FocusPay.

## Статус

**Production rollout заблокирован.** Не включайте, не запускайте, не перезапускайте и не выкатывайте casino-сервисы по этому документу. Требования допуска перечислены в [QUICKSTART.md](QUICKSTART.md), а production-сценарий требует отдельного одобренного runbook.

## Локальная разработка

```bash
cd ~/Desktop/focuspay-casino
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Для локального runtime используются `BOT_TOKEN`, `BOT_USERNAME`, `FOCUSPAY_API_URL`, `FOCUSPAY_INTERNAL_TOKEN`, `FOCUSPAY_EXCHANGER_API_KEY`, `FOCUSPAY_EXCHANGER_SECRET`, `WEBHOOK_URL`, `WEBHOOK_PORT`, `ALLOWED_CHAT_ID` и `ADMIN_IDS`. Не добавляйте их значения в исходный код, документацию или коммиты.

## Финансовая модель

- Баланс — unified balance FocusPay, локальный самостоятельный баланс отсутствует.
- До старта игры создаются холды ставок.
- PVP, Baccara и Blackjack используют один идемпотентный backend settlement для head-to-head игры.
- Комиссия считается от проигравшей ставки: две ставки по `100 ₽` при `15%` дают победителю `185 ₽`.
- Распределение creator/referral/owner происходит на trusted backend по сформированной комиссии.
- Ничья освобождает оба холда.

## Пополнения

- Сделка создаётся через Exchanger API с HMAC.
- Webhook проверяет HMAC по исходным байтам и свежесть timestamp.
- Callback не является источником Telegram ID, суммы, статуса или exchanger: эти данные повторно читает backend по `deal_id`.
- Principal-зачисление защищено server-side идемпотентностью и unique index на сделку.

## Игры

- PVP: `/cub`, `/2cub`.
- Карточные: `/baccara`, `/blackjack`.
- Raffle **отключён** (`RAFFLE_ENABLED=False`) и не должен тестироваться или использоваться с реальными средствами. Для него требуются отдельный trusted backend settlement и серверная проверка условий участия.

## Локальная валидация

```bash
cd ~/Desktop/focuspay-casino
PYTHONPATH="$PWD" python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
```

## Ограничения до rollout

1. `settlement_failed` пока не имеет durable persistence, retry и reconciliation после рестарта бота.
2. У отправителя callback нет durable outbox/retry/status delivery.
3. Casino-миграции нужно проверить на изолированной PostgreSQL базе и вручную применить только после backup и pre-check.
4. Отдельный production runbook должен включать backup, migration, isolated checks, post-check и безопасный rollback.

Подробный статус развёртывания: [DEPLOYMENT.md](DEPLOYMENT.md).