# Быстрый старт FocusPay Casino

## Статус

Casino-бот **не готов к production rollout**. Не запускайте `deploy.sh`, не применяйте миграции и не перезапускайте production-сервисы по этой инструкции.

Перед развёртыванием обязательны:

1. резервная копия production PostgreSQL;
2. ручная проверка исторических `external_ledger` на повторные principal-зачисления;
3. ручное применение всех casino-миграций с `psql -v ON_ERROR_STOP=1`;
4. проверка таблицы `casino_deposit_credits` и partial unique index;
5. настройка `CASINO_EXCHANGER_ID`, `FOCUSPAY_INTERNAL_TOKEN` и общих секретов webhook;
6. проверка полного сценария пополнения, PVP-расчёта и повторной доставки callback в изолированной среде.

Автоматический deploy-скрипт не выполняет эти условия.

## Локальная проверка

```bash
cd ~/Desktop/focuspay-casino
PYTHONPATH="$PWD" python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
```

Для runtime-окружения используются следующие переменные:

```dotenv
FOCUSPAY_API_URL=https://focuspay.org
FOCUSPAY_INTERNAL_TOKEN=
FOCUSPAY_EXCHANGER_API_KEY=
FOCUSPAY_EXCHANGER_SECRET=
WEBHOOK_URL=https://casino.focuspay.org/webhook
```

Не добавляйте их значения в документацию, код или коммиты.

## Доступные контуры

- PVP, Baccara и Blackjack используют холды unified balance и атомарный endpoint расчёта head-to-head игры.
- Комиссия считается от проигравшей ставки: при ставках `100 ₽` и комиссии `15%` победитель получает `185 ₽`.
- Пополнение использует server-side сделку FocusPay; callback служит только сигналом и не является источником суммы, статуса или Telegram ID.
- Raffle выключен (`RAFFLE_ENABLED=False`): для него нет отдельного атомарного backend-расчёта, а legacy-поток не должен использоваться с реальными средствами.

## Незакрытые условия перед production

- Нужны durable persistence, retry и reconciliation для `settlement_failed` после перезапуска бота.
- Нужен durable outbox/retry у отправителя callback.
- Raffle требует отдельного доверенного backend-контракта и серверной проверки условий участия.
- Deployment runbook должен выполняться вручную с бэкапом, миграциями и post-checks.

Подробности по окружению находятся в [DEPLOYMENT.md](DEPLOYMENT.md). Перед любым production-действием сверьте её с фактическими миграциями и контрактом backend.