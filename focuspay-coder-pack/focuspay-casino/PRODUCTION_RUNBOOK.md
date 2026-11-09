# FocusPay Casino — production runbook

> **Статус: не выполнять до успешной репетиции на изолированной копии production БД и отдельного одобрения production-этапа.**
>
> Этот документ определяет последовательность проверок. Он не заменяет backup, проверку SQL-результатов и контролируемый финансовый smoke-test.

## Границы релиза

В релиз входят PVP, Baccara и Blackjack с durable lifecycle, recovery и notification outbox.

Raffle остаётся выключенным (`RAFFLE_ENABLED=False`) и не включается этим runbook.

## Необходимые секреты

Файл `/etc/focuspay/casino-bot.env` создаётся на production вне репозитория, владельцем `root:focuspay`, с правами `0640`. В нём должны быть заданы:

- `BOT_TOKEN`;
- `BOT_USERNAME`;
- `FOCUSPAY_API_URL`;
- `FOCUSPAY_INTERNAL_TOKEN`;
- `FOCUSPAY_EXCHANGER_API_KEY`;
- `FOCUSPAY_EXCHANGER_SECRET`;
- `CASINO_EXCHANGER_ID` в backend environment;
- `WEBHOOK_URL` и общий webhook secret — только при webhook-режиме;
- `ALLOWED_CHAT_ID`, `GAME_CHAT_ID`, `ADMIN_IDS`;
- `DEPOSITS_ENABLED=0` — self-serve СБП/карта выключены, пока касса сайта тоже «скоро».
- Игровой чат (прод: FOCUS PAY `-1004058942735`): `@focusludka_bot` — **administrator** с правом удалять сообщения. Иначе Telegram не отдаёт кубики без reply на карточку, даже если BotFather privacy уже Disable (`can_read_all_group_messages=True`). Не кикать бота ради re-add, если можно повысить.

Значения секретов не записываются в этот документ, shell history или репозиторий.

## Обязательная репетиция

Перед production на изолированной копии production БД:

1. Выполнить preflight historical `external_ledger`: каждый principal должен быть однозначно связан со сделкой. Дубликат блокирует миграцию до отдельной сверки.
2. Применить миграции через `psql -v ON_ERROR_STOP=1` строго в порядке:
   1. `add_casino_tables.sql`;
   2. `fix_casino_backend_integrity.sql`;
   3. `add_casino_deposit_credits.sql`;
   4. `add_casino_durable_recovery.sql`;
   5. `add_casino_creator_accounts.sql`;
   6. `add_casino_creator_withdrawal_idempotency.sql`.
3. Подтвердить наличие `casino_deposit_credits`, `casino_notification_outbox`, `ux_external_ledger_principal_deal`, recovery/outbox индексов и `idempotency_key` у creator withdrawals.
4. Прогнать: trusted deposit, повтор того же callback, PVP win/draw, Baccara/Blackjack timeout, рестарт в `outcome_committed`, recovery и retry outbox.
5. До запуска polling выполнить `python3 deployment_smoke_check.py` с production-like secrets. Он только читает settings/snapshot и проверяет валидацию пустых POST без создания финансовых операций.

Любое расхождение останавливает rollout.

## Production pre-check

1. Проверить успешность локальных тестов casino-бота, backend casino-тестов и frontend build.
2. Создать backup production PostgreSQL и проверить, что dump читается отдельной командой restore/listing.
3. Сверить текущую схему с результатом репетиции, повторить historical duplicate preflight.
4. До restart API загрузить весь согласованный backend-набор, включая `casino_referral_stats.py`, затем выполнить `py_compile` модулей в production venv из `/tmp`.
5. Запустить `deployment_smoke_check.py` только после доступности API и схемы.

## Выкатка

1. Применять SQL по одному файлу с `psql -v ON_ERROR_STOP=1`; после каждого фиксировать результат и проверять требуемые таблицы/индексы.
2. Перезапускать API только после успешного `py_compile` полного dependency set.
3. Развернуть casino-бот в `/opt/focuspay-casino` отдельным системным пользователем и виртуальным окружением.
4. Установить `focuspay-casino-bot.service`; `focuspay-casino-webhook.service` и nginx нужны только при выбранном webhook-режиме. Для polling webhook не включать.
5. До старта polling проверить environment file и выполнить smoke-check. Затем запустить bot service: startup должен завершить bounded recovery до регистрации handlers.
6. Выкатывать frontend только с актуальной сборкой через `focussite/frontend/scripts/deploy_all.py`. Старый `DEPLOY_CASINO_FRONTEND.sh` запрещён: в нём неверный target и возможна устаревшая сборка.

## Post-check

1. Проверить active state API и casino bot systemd service.
2. Проверить `/api/internal/casino/settings`, recovery snapshot и API panel/creator с корректной авторизацией.
3. Убедиться, что Raffle не зарегистрирован и `RAFFLE_ENABLED=False`.
4. Выполнить только заранее согласованный минимальный тестовый финансовый сценарий и сверить balance holds, game status, ledger и outbox.
5. Проверить, что повторная доставка callback не создаёт второе зачисление.
6. Наблюдать журналы API/бота; ошибки recovery/outbox не должны подтверждать незавершённые финансовые операции.

## Откат

При ошибке до первого реального расчёта: остановить casino bot, не включать polling, сохранить журналы и результаты preflight. Схему и данные восстанавливать только из проверенного backup по отдельному одобрению, так как это необратимая production-операция.
