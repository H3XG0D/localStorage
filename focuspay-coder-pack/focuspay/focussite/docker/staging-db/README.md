# Disposable staging PostgreSQL bootstrap

Этот каталог создаёт **только новую пустую disposable PostgreSQL database** с синтетическими fixtures. Он не использует production dump, персональные данные, реальные реквизиты, Telegram polling, секреты или внешние интеграции. Bootstrap не создаёт контейнеры и не использует Compose.

## Профили

### `pvp` — профиль по умолчанию

Поведение сохранено без изменений. Скрипт применяет Casino PvP/durable-recovery migrations и создаёт:

- игроков `100000001` и `100000002`, admin `100000003` и test exchanger `91001`;
- один approved PvP chat binding и одну `outcome_committed` PvP dice game;
- cashback-only funding, два active holds и выключенный raffle.

Никакие платежные migrations, PayFast records или finance entries в этом профиле не создаются.

### `payments` — opt-in профиль платежного потока

Запускается только явно: `bash 00-apply-migrations.sh payments`. Он применяет минимальную цепочку:

1. безопасно создаёт отсутствующую non-login роль `exchange_bot` до migrations, не меняя уже существующую роль;
2. `add_external_exchanges.sql`;
3. `add_external_deals_status.sql`;
4. `add_external_deal_payin.sql`;
5. `add_exchanger_hmac_api_and_expires.sql`;
6. `add_external_exchanger_accounts.sql`;
7. `add_exchanger_hmac_api_and_expires.sql`;
8. `add_external_deal_receipt_type.sql`;
9. `add_external_deal_client_is_new.sql`;
10. `add_external_exchanger_trust_flags.sql`;
11. `add_external_markup_mode.sql`;
12. `add_external_deal_operator.sql`;
13. `add_operator_dual_roles.sql`;
14. `add_external_deal_payout_on_credit.sql`;
15. `add_external_deal_payfast_reviews.sql`.

Создаются исключительно синтетические данные:

- exchanger `92001` с выключенными trust/auto-credit флагами, активным synthetic кабинетом и одной активной HMAC API-парой с тестовыми значениями;
- client и finance operators с `operator_roles` и открытыми сменами; finance operator назначен на synthetic deal;
- одна подтверждённая external deal с базовыми `receipt_type`, `client_is_new`, `markup_mode` и payout-on-credit полями, ровно один principal и один reward ledger entry;
- одна базовая confirmed entry в `owner_finance_ledger`.

PayFast review table создаётся migration, но fixtures не имитируют callback, реквизиты, чек, запрос к провайдеру или внешнюю доставку. Casino migrations и Casino tables в `payments` не устанавливаются.

### `full-panel-pvp` — полный synthetic panel + Casino PvP

Запускается явно: `bash 00-apply-migrations.sh full-panel-pvp`. Сначала создаёт fixtures полного сайта/панелей, затем Casino schema и PvP fixtures: `player_a`, `player_b`, active binding, finished game и `outcome_committed` recovery game с привязанными holds.

Требуются secret-store variables `STAGING_SYNTHETIC_ADMIN_USERNAME`, `STAGING_SYNTHETIC_ADMIN_PASSWORD`, `STAGING_SYNTHETIC_CLIENT_OPERATOR_PASSWORD`, `STAGING_SYNTHETIC_FINANCE_OPERATOR_PASSWORD`. Имена operator fixtures: `fixture_full_client_ops` и `fixture_full_finance_ops`; TOTP для synthetic logins выключен.

## Запуск

Запускайте скрипт только из уже подготовленного изолированного PostgreSQL окружения, передав обычные `PG*` variables. Не передавайте DSN или секреты в командной строке, логе либо Git.

```bash
PGHOST=... PGPORT=... PGUSER=... PGDATABASE=... \
  bash focussite/docker/staging-db/00-apply-migrations.sh pvp

PGHOST=... PGPORT=... PGUSER=... PGDATABASE=... \
  bash focussite/docker/staging-db/00-apply-migrations.sh payments

PGHOST=... PGPORT=... PGUSER=... PGDATABASE=... \
  bash focussite/docker/staging-db/00-apply-migrations.sh full-panel-pvp
```

## Повторный запуск

Все профили одноразовые и fail-closed. До DDL проверяются markers PvP, payments и full-panel-pvp, включая `external_deals`, `external_ledger`, `owner_finance_ledger` и `casino_games`. При любой найденной несовместимой сущности bootstrap завершается с кодом `65`: fixtures и ledger не переигрываются, поэтому дубликаты principal/funding записей не создаются.

Для `full-panel-pvp` используйте новый выделенный volume/database, например persistent runtime volume `focuspay_staging_runtime_full_panel_pvp_postgres`. Не накатывайте этот профиль на существующий `full-panel` volume.

Для чистого повтора нужен новый disposable PostgreSQL volume. Его удаление — destructive операция и не входит в bootstrap.

## Assertions

После запуска `pvp` проверяются существование таблиц/indexes, роли, единственный active binding, выключенный raffle, funding ledger и durable recovery fixture.

После запуска `payments` проверяются ровно один synthetic exchanger и активная HMAC credential, две активные operator shifts, единичная deal, единичный principal ledger и единичная finance entry. Также profile отклоняет наличие Casino tables.

После запуска `full-panel-pvp` проверяются panel fixtures, operator login setup, Casino tables, обе PvP роли, active binding, finished game и `outcome_committed` recovery game.

`bootstrap_static_test.sh` проверяет эти гарантии без контейнера. Runtime SQL validation допустима только на уже существующей disposable local/staging PostgreSQL database.
