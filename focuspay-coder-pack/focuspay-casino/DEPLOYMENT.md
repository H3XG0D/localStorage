# FocusPay Casino — условия production rollout

## Статус

Casino-бот **не готов к production rollout**. Эта инструкция намеренно не содержит команд deploy, миграций, перезапуска сервисов, nginx или отката: любые из них меняют боевое окружение и выполняются только по отдельному утверждённому runbook.

## Что реализовано локально

- PVP, Baccara и Blackjack используют unified balance FocusPay: холды создаются до начала игры, а head-to-head расчёт выполняется одним идемпотентным backend-вызовом.
- Комиссия вычисляется от проигранной ставки. При двух ставках по `100 ₽` и ставке комиссии `15%` итоговая выплата составляет `185 ₽`.
- Сумма выплаты для игрока берётся из ответа trusted backend, а не рассчитывается ботом.
- Callback пополнения проверяет HMAC по исходным байтам тела и ограничивает его возраст. Callback содержит только сигнал: сделка заново проверяется через Exchanger API, а зачисление выполняет backend по `deal_id`.
- Raffle выключен через `RAFFLE_ENABLED=False`: у него нет отдельного атомарного backend-расчёта и серверной проверки условий участия.

## Обязательные условия перед production rollout

1. Создать и проверить резервную копию production PostgreSQL.
2. На копии данных проверить исторические повторные `principal`-строки `external_ledger`.
3. Применить casino-миграции вручную через `psql -v ON_ERROR_STOP=1`, включая `add_casino_deposit_credits.sql`.
4. Проверить наличие `casino_deposit_credits` и partial unique index `ux_external_ledger_principal_deal`.
5. Настроить `CASINO_EXCHANGER_ID`, `FOCUSPAY_INTERNAL_TOKEN`, ключи Exchanger API и общий секрет webhook только через production environment.
6. В изолированной среде пройти: пополнение, повторную доставку callback, PVP-расчёт, ничью и timeout Baccara/Blackjack.
7. До включения реальных средств добавить durable persistence, retry и reconciliation для состояний `settlement_failed` после рестарта бота.
8. До включения Raffle реализовать его отдельный trusted backend settlement и серверную проверку turnover/deposit-условий.
9. Утвердить отдельный production runbook с pre-check, backup, миграциями, post-check и планом безопасного отката.

Автоматический `deploy/deploy.sh` не заменяет эти условия и не должен запускаться до их выполнения.

## Локальная валидация

```bash
cd ~/Desktop/focuspay-casino
PYTHONPATH="$PWD" python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
```

## Конфигурация runtime

Используются переменные окружения:

```dotenv
BOT_TOKEN=
BOT_USERNAME=
FOCUSPAY_API_URL=https://focuspay.org
FOCUSPAY_INTERNAL_TOKEN=
FOCUSPAY_EXCHANGER_API_KEY=
FOCUSPAY_EXCHANGER_SECRET=
WEBHOOK_URL=https://casino.focuspay.org/webhook
WEBHOOK_PORT=8001
ALLOWED_CHAT_ID=
ADMIN_IDS=
```

Не записывайте значения секретов в документацию, исходный код, историю команд или коммиты.
