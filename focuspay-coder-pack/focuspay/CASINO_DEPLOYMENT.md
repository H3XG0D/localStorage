# FocusPay Casino — статус integration

## Production rollout заблокирован

Casino-контур **не готов к production rollout**. Не применяйте миграции, не запускайте `DEPLOY_CASINO_FRONTEND.sh`, не включайте и не перезапускайте сервисы, не меняйте nginx по этому документу.

Любое production-действие требует отдельного явного одобрения, проверенного backup PostgreSQL, ручного runbook и post-checks. Канонические условия допуска описаны в [`../focuspay-casino/QUICKSTART.md`](../focuspay-casino/QUICKSTART.md).

## Реализовано локально

- Страницы казино: кабинет создателя `/casino/creator`, административные `/x8/casino`, `/x8/casino/games`, `/x8/casino/settings`, `/x8/casino/creator-payouts`.
- Backend предоставляет Internal Casino, Creator и Admin API.
- PVP, Baccara и Blackjack используют холды unified balance и один идемпотентный head-to-head settlement.
- Комиссия считается от проигравшей ставки. При ставках `100 ₽` и комиссии `15%` победитель получает `185 ₽`.
- Callback пополнения служит только сигналом: сумма, статус, exchanger и Telegram ID заново определяются backend по trusted сделке.
- Raffle выключен (`RAFFLE_ENABLED=False`) и не допускается к реальным средствам до отдельного trusted backend settlement и серверной проверки условий участия.

## Обязательные условия допуска

1. Backup production PostgreSQL создан и проверен.
2. Исторические `external_ledger` проверены на дублирование principal-зачислений.
3. Casino-миграции применены вручную с `psql -v ON_ERROR_STOP=1`, включая `add_casino_deposit_credits.sql`.
4. Проверены таблица `casino_deposit_credits` и partial unique index `ux_external_ledger_principal_deal`.
5. Через защищённое production configuration management настроены `CASINO_EXCHANGER_ID`, `FOCUSPAY_INTERNAL_TOKEN`, ключи Exchanger API и общий секрет webhook.
6. В изолированной среде пройдены сценарии пополнения, повторного callback, PVP-расчёта, ничьей и timeout карточных игр.
7. Для `settlement_failed` реализованы durable persistence, retry и reconciliation после рестарта бота.
8. Для отправителя callback реализованы durable outbox, retry и статус доставки.
9. Для Raffle реализованы отдельный атомарный backend-расчёт и server-side проверка turnover/deposit-условий.
10. Production runbook содержит pre-check, backup, миграции, post-check и безопасный план отката.

## Локальная проверка

```bash
cd ~/Desktop/focuspay-casino
PYTHONPATH="$PWD" python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q .
```

Для backend casino-контур проверяется целевыми тестами из `site/exchange-backend/tests/`.

## Архитектура

```text
Telegram Casino Bot
  ├─ PVP / Baccara / Blackjack
  └─ Raffle: disabled
        │
        ▼
Internal Casino API
  ├─ unified balance holds
  ├─ atomic head-to-head settlement
  └─ server-authoritative deposit credit
        │
        ▼
FocusPay PostgreSQL / casino_* tables
```

## Актуальные источники

- Бот: `~/Desktop/focuspay-casino/`
- Backend: `site/exchange-backend/routers/internal_casino.py`, `routers/admin_casino.py`, `routers/casino_creator.py`
- Финансовая логика: `site/exchange-backend/casino_finance.py`
- Миграции: `site/exchange-backend/migrations/add_casino_tables.sql`, `add_casino_deposit_credits.sql`
- Frontend: `focussite/frontend/src/pages/CasinoCreatorDashboard.tsx`, `focussite/frontend/src/panel/admin/Casino/`
