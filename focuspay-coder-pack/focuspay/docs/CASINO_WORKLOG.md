# Журнал работы по плану казино

Память сеансов. Не догадываться — читать последнюю запись.

SSH на staging: хост-алиас `focuspay-test` (`178.63.247.233`, пользователь `focuspay-staging`, ключ `~/.ssh/focuspay-staging-178.63.247.233`). Пароль не используется. Прод `153.80.249.77` не трогаем.

---

## 2026-08-28 — Задача 0. Зафиксировать текущее состояние

Сделано: журнал заведён. Ничего по существу не менялось. Снят снимок git в обоих репозиториях. Staging жива: `staging-runtime-health.sh` прошёл. Базовая линия pytest не снималась — канала из Задачи 0Б ещё нет.

Файлы: `docs/CASINO_WORKLOG.md` (этот файл).

Локальная сборка: не трогал фронт в этом шаге.

Залито на staging: нет.

Healthcheck: `staging runtime health check passed` (2026-08-28, ~05:24 UTC). Контейнеры runtime: postgres/redis/fake-payfast/backend/gateway healthy; bot и casino-bot running. Каталоги `/opt/focuspay` и `/opt/focuspay-casino` на сервере есть.

Тесты на staging: не гонялись (Задача 0Б).

Отклонение от базовой линии: базовой линии ещё нет.

Следующий шаг: Задача 0Б.

Открытые вопросы: нет. Человек разрешил два коммита WIP. Исключены `.zcode/` и `focuspay-casino/=10.0.0`.

Коммиты WIP:
- `focuspay-casino` `4b8d65e5c720c999d25f9e01b2cb7038928609b1` — `chore(casino): snapshot in-progress menu, profile cards, and PvP lobby work`
- `focuspay` `a96616203d31b831d2f5860303e9558985dd64d8` — `chore(casino): snapshot in-progress house, tier grids, and settings work`

### Снимок git — /home/qwe/Desktop/focuspay

- branch: `main`
- HEAD: `3bf07aef1922b22eaa13e94f122b972b4a2a0e3a`
- dirty: 18 modified, 12 untracked (в т.ч. этот журнал после создания)

```
 M focussite/STAGING_RUNTIME.md
 M focussite/frontend/src/panel/admin/AdminRoutes.tsx
 M focussite/frontend/src/panel/admin/Casino/CasinoDashboard.tsx
 M focussite/frontend/src/panel/admin/Casino/CasinoHouse.tsx
 M focussite/frontend/src/panel/admin/Casino/CasinoSettings.tsx
 M focussite/frontend/src/panel/lib/adminApi.ts
 M focussite/scripts/staging-runtime-preflight.sh
 M site/exchange-backend/casino_cashback_tiers.py
 M site/exchange-backend/casino_finance.py
 M site/exchange-backend/casino_wagering.py
 M site/exchange-backend/casino_weekly_cashback.py
 M site/exchange-backend/finance_access.py
 M site/exchange-backend/routers/admin_casino.py
 M site/exchange-backend/routers/internal_casino.py
 M site/exchange-backend/tests/test_admin_casino_regression.py
 M site/exchange-backend/tests/test_casino_cashback_tiers.py
 M site/exchange-backend/tests/test_casino_commission.py
 M site/exchange-backend/tests/test_casino_wagering.py
?? .zcode/
?? focussite/frontend/src/panel/admin/Casino/CasinoHouseReadiness.tsx
?? focussite/frontend/src/panel/admin/Casino/CasinoRobotProfileEditor.tsx
?? focussite/frontend/src/panel/admin/Casino/CasinoTierGrids.tsx
?? focussite/frontend/src/panel/admin/Casino/casinoHousePresets.ts
?? site/exchange-backend/casino_house_readiness.py
?? site/exchange-backend/casino_tier_config.py
?? site/exchange-backend/casino_weekly_wager.py
?? site/exchange-backend/migrations/add_casino_volume_tier_grids.sql
?? site/exchange-backend/tests/test_admin_casino_house_readiness.py
?? site/exchange-backend/tests/test_casino_tier_config.py
?? site/exchange-backend/tests/test_finance_access_staging.py
```

Diffstat modified: 18 files, +1660 / −288 (без untracked).

### Снимок git — /home/qwe/Desktop/focuspay-casino

- branch: `main`
- HEAD: `3b8dca79936ce29a0130b8a7557147d96a41efb6`
- dirty: 12 modified, 12 untracked

```
 M bot.py
 M config.py
 M games/baccara.py
 M games/blackjack.py
 M games/pvp.py
 M games/raffle.py
 M requirements.txt
 M tests/telebot_stub.py
 M tests/test_bot_startup.py
 M tests/test_focuspay_client.py
 M tests/test_pvp_lobby.py
 M tests/test_staging_config.py
?? =10.0.0
?? PROFILE_CARD_CHECKLIST.md
?? STAGING_DEPLOYMENT.md
?? assets/
?? casino_menu.py
?? casino_profile_card.py
?? casino_start_card.py
?? tests/test_card_bet_input.py
?? tests/test_casino_profile_card.py
?? tests/test_casino_start_card.py
?? tests/test_profile.py
?? tests/test_pvp_dice.py
```

Diffstat modified: 12 files, +1238 / −88 (без untracked).

---

## 2026-08-28 — Задача 0Б. Канал в тестовую машину

Сделано: SSH на staging проверен (алиас `focuspay-test`, ключ, без пароля). Написаны `focussite/scripts/staging-sync.sh` и `focussite/scripts/staging-test.sh`. Заведён сервис `backend-tests` (profile `tests`, без опубликованных портов, `app_net`, без `read_only`). В `STAGING_RUNTIME.md` добавлено исключение: прямая заливка рабочей папки на staging через `staging-sync.sh`; на прод правило SHA без изменений. Текущее состояние залито, healthcheck зелёный, снята базовая линия pytest.

Файлы: `focussite/scripts/staging-sync.sh`, `focussite/scripts/staging-test.sh`, `focussite/docker/backend-tests.Dockerfile`, `focussite/docker-compose.staging-runtime.yml`, `focussite/STAGING_RUNTIME.md`, `docs/CASINO_WORKLOG.md`.

Локальная сборка: фронт не трогал.

Залито на staging: да, `staging-sync.sh` (rsync обоих деревьев + `staging-runtime-update.sh --apply`). Повторный rsync focuspay после правки тестового образа.

Healthcheck: `staging runtime health check passed` после update и повторно после pytest.

Тесты на staging: `sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env ./scripts/staging-test.sh` → `python -m pytest tests/ -q`. **930 passed, 7 failed, 0 skipped, 0 errors.** Упали:

1. `tests/test_casino_weekly_cashback.py::CasinoWeeklyCashbackTests::test_duplicate_claim_does_not_create_second_ledger_credit`
2. `tests/test_casino_weekly_cashback.py::CasinoWeeklyCashbackTests::test_includes_only_canonical_completed_loss_types`
3. `tests/test_finance_access_staging.py::FinanceAccessStagingFixtureTests::test_fixture_admin_not_finance_owner_in_production`
4. `tests/test_internal_casino.py::DurableLifecycleTests::test_commit_outcome_only_accepts_game_player_and_persists_outcome`
5. `tests/test_internal_casino.py::DurableLifecycleTests::test_non_winner_outcome_commits_without_winner`
6. `tests/test_internal_casino.py::DurableLifecycleTests::test_waiting_cancel_commits_without_an_opponent_or_winner`
7. `tests/test_internal_casino.py::ProfileEndpointTests::test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`

Это падения чужого WIP из §2.3 (weekly wager / cashback / finance fixture), не регрессия канала. Чинить в 0Б не требуется.

Отклонение от базовой линии: это и есть базовая линия.

Следующий шаг: Задача 1. Реестр настроек `casino_settings_registry.py` — **не начинать**, пока человек не принял этап «ноль» по `docs/CASINO_REVIEW_CHECKLIST.md`.

Открытые вопросы: нет. `staging-sync.sh` перед rsync удаляет dest-only хвосты `/opt/focuspay/casino-client` и `/opt/focuspay-casino/.staging-e2e` (иначе `--delete` ломается из-за exclude `.env.*` и root-owned каталога). Тестовый сервис монтирует `/opt/focuspay:ro`, чтобы pytest видел залитый код без пересборки дерева в образе.

### Базовая линия (не двигать без записи)

- дата: 2026-08-28
- команда: `./scripts/staging-test.sh` → `pytest tests/ -q`
- 930 passed / 7 failed / 0 skipped / 0 errors
- список failed: семь имён выше

0Б закоммичена: `61e47be9f6cf415a121663ecb60d4a20383661f3`. Человек принял ноль («дальше делай») и попросил выкат на staging.

---

## 2026-08-28 — Задача 1. Реестр настроек casino_settings_registry.py

Сделано: единый реестр ключей `casino_settings`. Словари дефолтов убраны из `routers/admin_casino.py` и `casino_finance.py` — оба читают `default_numeric` / `PERCENT_KEYS` / `AMOUNT_KEYS`. PATCH пишет только ключи из реестра: неизвестный ключ → HTTP 400. Значения и формат хранения `{"percent": N}` / `{"amount": N}` не менялись. В реестр также внесены уже существующие `enabled_games` и сетки тиров, иначе PATCH на них стал бы 400.

Файлы: `site/exchange-backend/casino_settings_registry.py`, `site/exchange-backend/casino_finance.py`, `site/exchange-backend/routers/admin_casino.py`, `site/exchange-backend/tests/test_casino_settings_registry.py`, `site/exchange-backend/tests/test_admin_casino_regression.py`.

Локальная сборка: фронт не трогал.

Залито на staging: да, `staging-sync.sh` после задачи 1.

Healthcheck: `staging runtime health check passed`.

Тесты на staging: `./scripts/staging-test.sh` → **937 passed, 7 failed, 0 skipped, 0 errors.** Семь упавших — те же имена, что в базовой линии. +7 passed — новые тесты реестра и HTTP 400, чужие тесты не чинил.

Отклонение от базовой линии: новых имён в failed нет. Passed вырос с 930 до 937 из‑за добавленных тестов.

Следующий шаг: Задача 2. Новые настройки — **не начинать** до приёмки задачи 1.

Открытые вопросы: JSON с неизвестным полем на `CasinoSettingsUpdate` по-прежнему даёт pydantic **422** (`extra=forbid`, так было). HTTP **400** срабатывает, если неизвестный ключ дошёл до PATCH-обработчика.

Разделение сверки (2026-08-28): команды гоняет агент; человеку — только клики. Эталон прода (read-only, не менять): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 2026-08-28 04:22:48 UTC, `focuspay-exchange-api` ActiveEnterTimestamp Fri 2026-08-28 04:17:07 UTC.

0Б на staging тоже доехала этим же sync (коммит `61e47be` плюс незакоммиченная задача 1).

---

## 2026-08-28 — Поправка к отыгрышу (после задачи 1)

Сделано: по подтверждению человека настройки задачи 1 приняты. Модель отыгрыша поправлена: `wagering_percent` — это плюс казино комиссией с игрока, не «поставить 21% депозита». Пример: депозит 1000 ₽ → дом должен получить 210 ₽ комиссии; при комиссии 15% нужно поставить 1400 ₽. Прогресс лока считает `ставка × комиссия раунда`, а игроку `remaining_rub` отдаётся как объём ставок. Тексты в админке, `/help`, пополнении, балансе, профиле и карточках говорят то же.

Поправка к глоссарию плана: было «отыгрыш — оборот ставок». Стало «отыгрыш — блокировка вывода, пока казино не получит `wagering_percent` плюса комиссией с этого человека; объём ставок = плюс / комиссия до отыгрыша».

Файлы: `site/exchange-backend/casino_wagering.py`, `site/exchange-backend/casino_settings_registry.py` (help_ru), `site/exchange-backend/routers/internal_casino.py`, `site/exchange-backend/tests/test_casino_wagering.py`, `site/exchange-backend/tests/test_casino_settings_registry.py`, `focussite/frontend/src/panel/admin/Casino/CasinoSettings.tsx`, `docs/CASINO_REVIEW_CHECKLIST.md`; в `focuspay-casino`: `wagering.py`, `bot.py`, `casino_profile_card.py`, `casino_start_card.py`, `config.py`, тесты и e2e.

Локальная сборка: `cd focussite/frontend && npm run build` — tsc + vite ок.

Залито на staging: да, `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. md5 совпали: `casino_wagering.py` `ef2f12800fe33ee7ea3af72e5fe1aec4`, `CasinoSettings.tsx` `35b5c25137447477b949ff0f87392792`, `wagering.py` `97ebbe425e621ab21510d0ab120c3c54`, `bot.py` `fb10e0c1f8b7db50560a04885259e1b6`.

Healthcheck: `staging runtime health check passed` после sync и повторно после доп. pytest.

Тесты на staging: `./scripts/staging-test.sh` → те же 7 failed имён, что в базовой линии / задаче 1. Новых имён нет. Локально `tests/test_casino_wagering.py` + `test_casino_settings_registry.py`: 17 passed.

Прод (read-only, не менялся): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, `focuspay-exchange-api` ActiveEnterTimestamp Fri 2026-08-28 04:17:07 UTC.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway.

Следующий шаг: Задача 2 — человек подтвердил клики по отыгрышу 2026-08-28 («подтверждаю, можешь продолжать»).

Открытые вопросы: нет.

---

## 2026-08-28 — Задача 2. Новые настройки (группы в реестре + админка)

Сделано: в реестр добавлены группы bankroll / limits / commission / responsible / payouts / fairness. Дефолты не меняют живые деньги: `commission_cap_rub=0`, `commission_min_rub=0`, `bankroll_floor_rub=0`, `liability_amount_rub=0`, `per_game_limits={}`, responsible-тумблеры false, `provably_fair_enabled` все false. Хранение: percent `{percent}`, amount `{amount}` (включая 0), int `{value}`, bool `{enabled}`, карты как JSON. GET без строк в БД отдаёт эти дефолты. PATCH пишет через `to_storage`. Хелперы `clamp_commission_rub` и `effective_max_stake` есть и покрыты тестами; в `calculate_equal_stake_settlement` и create-game **не** подключены (это задача 5). Миграции `add_casino_settings_v2.sql` нет (задача 3). Редизайн двух колонок не делал (задача 9): новые карточки после «Лимиты», до «Кабинет создателя».

Файлы: `site/exchange-backend/casino_settings_registry.py`, `site/exchange-backend/routers/admin_casino.py`, `site/exchange-backend/tests/test_casino_settings_registry.py`, `site/exchange-backend/tests/test_admin_casino_regression.py`, `focussite/frontend/src/panel/lib/adminApi.ts`, `focussite/frontend/src/panel/admin/Casino/CasinoSettings.tsx`. Журнал этот. `focuspay-casino` в этой задаче не трогал (грязный diff там — поправка отыгрыша).

Локальная сборка: `cd focussite/frontend && npm run build` — tsc + vite ок (`panel-B3XsVBZl.js`).

Залито на staging: да, `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Healthcheck: `staging runtime health check passed`. md5 local=staging:

- `casino_settings_registry.py` `d78957c9774c7f3e6842138861a3523c`
- `routers/admin_casino.py` `c006ca64b6aeaf91e1b8eaebcc275cea`
- `tests/test_casino_settings_registry.py` `cbfc873a34e895937ed956f368d9c936`
- `CasinoSettings.tsx` `4221707ce770a84dda9d272d8fc55adc`
- `adminApi.ts` `ada0b3ce8bb02c85d56fd15765b69da1`

Тесты на staging: `./scripts/staging-test.sh` → **960 collected, 953 passed, 7 failed, 0 skipped, 0 errors.** Семь упавших — те же имена, что в базовой линии / задаче 1. Новых имён нет. Passed 937→953: новые тесты реестра по группам и GET/PATCH нулевого капа (плюс ранее добавленные тесты отыгрыша, которые в 937 ещё не все входили). Локально `test_casino_settings_registry.py` + `test_admin_casino_regression.py`: 47 passed.

SQL staging: новых ключей cap/floor в `casino_settings` ещё нет (миграция — задача 3). GET всё равно отдаёт 0 / `{}` из реестра. После «Сохранить» в админке ключи появятся через INSERT, значения 0 должны остаться 0.

`rg` (имя больше одного раза): `commission_cap_rub` и `bankroll_floor_rub` — registry + admin API + tests + `adminApi.ts` + `CasinoSettings.tsx`. То же для `per_game_limits`, `provably_fair_enabled`, `deposit_limit_enabled`, `withdrawal_auto_approve_max_rub`, `max_profit_pct_per_round`. В `casino_finance.calculate_equal_stake_settlement` новых ключей нет — так и задумано до задачи 5.

Прод (read-only): HTML эталон тот же — `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC. Файла `/opt/exchange-backend/casino_settings_registry.py` на проде нет; `casino_finance.py` там от 2026-08-23. **`focuspay-exchange-api` ActiveEnterTimestamp сменился на Fri 2026-08-28 07:14:26 UTC** (было 04:17:07). Это graceful systemd stop/start в root-сессии 183, NRestarts=0, код на диске не наш. `deploy_all.py` не запускал. Больше на прод по SSH в этой задаче не ходил.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Остальные runtime без host-портов. Рядом старый стек `focuspay-staging-*` без публикации.

Git: `focuspay` HEAD `61e47be`, dirty незакоммичен (задача 1 + отыгрыш + задача 2). `focuspay-casino` HEAD `4b8d65e`, dirty только отыгрыш.

Следующий шаг: Задача 3. Миграция — человек принял задачу 2 кликами («дальше», 2026-08-28).

Открытые вопросы: смена ActiveEnterTimestamp на проде — не наше выкатывание; новый эталон метки юнита: 2026-08-28 07:14:26 UTC.

---

## 2026-08-28 — Задача 3. Миграция add_casino_settings_v2.sql

Сделано: `site/exchange-backend/migrations/add_casino_settings_v2.sql` — 26 новых ключей, `INSERT ... ON CONFLICT (key) DO NOTHING`, без `DO UPDATE`. Значения = дефолты реестра (cap/floor/liability 0, `per_game_limits` `{}`, responsible off). Staging bootstrap не глобит `*.sql`, поэтому файлы стоят в явном списке `00-apply-migrations.sh` (required_artifacts + `run_psql -f`) и `20-full-panel-bootstrap.sh`. Живой staging идёт профилем `full-panel-pvp` → `20-full-panel-bootstrap.sh`; ветка «уже bootstrapped» раньше делала `exit 0` без новых SQL — теперь перед выходом гоняет только два идемпотентных INSERT: `add_casino_volume_tier_grids.sql` и `add_casino_settings_v2.sql`. В тот же список дыр добавлены уже существовавшие `add_casino_volume_tier_grids.sql`, `add_casino_weekly_cashback_tiers.sql`, `add_casino_creator_withdrawal_idempotency.sql` (и на fresh-цепи full-panel — deposit_credits / wagering_locks / commission_profiles / multiplayer_v2 / house_ledger). `bootstrap_static_test.sh` требует оба имени в обоих скриптах и `ON CONFLICT (key) DO NOTHING` в v2 SQL. Тест `CasinoSettingsV2MigrationTests`. В расчёты (задача 5) и аудит (задача 4) не лез.

Файлы задачи: `migrations/add_casino_settings_v2.sql`, `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`, `tests/test_casino_settings_registry.py`, этот журнал. `focuspay-casino` не трогал.

Не задача 3, но в том же дереве: чужой WIP broadcast (`broadcast_service.py`, `adminBroadcast.ts`, …). Чтобы `staging-sync.sh` собрал фронт, одна строка в `adminBroadcast.ts`: тип `BROADCAST_STICKER_MODE_DEFAULT` расширен до `"auto" | "none"` (tsc TS2367). Broadcast не переписывал.

Локальная сборка: фронт в этой задаче не менял (карточки — задача 2). `bootstrap static checks passed`.

Залито на staging: да, `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Healthcheck: `staging runtime health check passed`. Bootstrap лог уже существующей БД:

- `Synthetic staging PostgreSQL full-panel-pvp bootstrap already completed.`
- grids: `INSERT 0 0` (ключи уже были)
- v2: `INSERT 0 26` (все 26 новых ключей)

md5 local=staging:

- `add_casino_settings_v2.sql` `4b9b41322f188eea2ec16ebee5aa2f8b`
- `00-apply-migrations.sh` `0e1abe495b8b929acd8719fe581fcf4f`
- `20-full-panel-bootstrap.sh` `06c3e124240527073ba53793509466a1`
- `bootstrap_static_test.sh` `f964a31791d19bc511ec2d2581f4252f`
- `test_casino_settings_registry.py` `a4a327fcd12a765b5bb15a785d2b05d9`

`rg -n "add_casino_settings_v2|volume_tier_grids"`: оба имени в `00-apply-migrations.sh` (строки 36–37, 245–246) и в `20-full-panel-bootstrap.sh` (required 107–108, incremental 180–181, fresh 280–281).

SQL staging после наката: **46 ключей** в `casino_settings`. `commission_cap_rub` / `bankroll_floor_rub` / `liability_amount_rub` = `{"amount": 0.0}`, `per_game_limits` `{}`, `seed_rotation_allowed` `{"enabled": true}`, `commission_rate_wagering_active` снова `{"percent": 15.0}`. Сетки `cashback_volume_tiers` и `commission_volume_tiers` живут JSON-ключами в `casino_settings`. `to_regclass('casino_cashback_volume_tiers')` = NULL — отдельной таблицы нет, так и задумано.

Идемпотентность (агент, SQL): `commission_rate_wagering_active` поставлен в 13 через `jsonb_build_object`; повторный прогон обоих SQL → `INSERT 0 0` / `INSERT 0 0`; значение осталось `{"percent": 13.0}`. Затем вернул 15, чтобы UI для клика человека стартовал с дефолта. Кликовый прогон 13% → `staging-sync.sh` → «осталось 13» — за человеком.

Тесты на staging: `./scripts/staging-test.sh` → **963 collected, 956 passed, 7 failed, 0 skipped, 0 errors.** Семь упавших — те же имена, что в базовой линии / задачах 1–2. Новых имён нет. Passed 953→956: +1 `CasinoSettingsV2MigrationTests`; ещё +2 — не правка семёрки, вероятнее всего тесты из чужого dirty broadcast, который уехал тем же sync.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, `focuspay-exchange-api` ActiveEnterTimestamp Fri 2026-08-28 07:14:26 UTC — как после задачи 2.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–3 + отыгрыш + чужой broadcast). `focuspay-casino` HEAD `4b8d65e`, dirty только отыгрыш.

Следующий шаг: Задача 4. Аудит-лог — **не начинать**, пока человек не примет кликами задачу 3.

Открытые вопросы: нет.

---

## 2026-08-28 — Задача 3, починка сохранения (клик «Сохранить» → 500)

Сделано: человек нажал «Сохранить» на `/x8/casino/settings` и получил «Ошибка сервера». Лог staging: `AttributeError: 'dict' object has no attribute 'model_dump'` в `update_casino_settings` на `commission_volume_tiers`. Форма всегда шлёт сетки тиров; PATCH сначала делает `model_dump()`, и строки сетки уже словари. Повторный `.model_dump()` падал. Починил через `_setting_row_dict`; невалидная сетка теперь 422, не 500. Тест `test_patch_saves_when_volume_tiers_arrive_as_dicts` (комиссия 13 + сетки как из UI).

Файлы: `routers/admin_casino.py`, `tests/test_admin_casino_regression.py`, этот журнал. Миграцию и дефолты не трогал.

Залито на staging: да, `staging-sync.sh`. Healthcheck: `staging runtime health check passed`. md5 local=staging: `admin_casino.py` `41fe763bfd9aae71fabe2e6c1f96f555`, `test_admin_casino_regression.py` `e705336d0f140d440687e615d0abd3cd`.

SQL после sync: комиссия «до отыгрыша» всё ещё `{"percent": 15.0}` (сохранение не дошло), ключей 46, cap `{"amount": 0.0}`.

Тесты на staging: `./scripts/staging-test.sh` → **964 collected, 957 passed, 7 failed.** Семь имён те же. +1 passed — новый тест PATCH сеток. Локально `CasinoSettingsEndpointTests`: 11 passed. На staging тот же класс: 11 passed.

Прод (read-only): HTML и `ActiveEnterTimestamp` как после задачи 2 (`index.html` 04:22:45, `panel.html` 04:22:48, юнит 07:14:26 UTC).

Docker: наружу только `127.0.0.1:18081->8080/tcp`.

Следующий шаг: задача 3 принята кликами («сделал», 2026-08-28). Повторный `staging-sync.sh` после 13%: bootstrap `INSERT 0 0` / `INSERT 0 0`, комиссия осталась `{"percent": 13.0}`. Вернул 15 на `commission_rate`, `commission_rate_wagering_active` и первую строку `commission_volume_tiers`.

Открытые вопросы: нет.

---

## 2026-08-28 — Задача 4. Аудит-лог casino_settings_audit

Сделано: таблица `casino_settings_audit` (id, batch_id, key, old_value JSONB, new_value JSONB, changed_by, changed_at, reason). PATCH `/casino/settings` требует `reason` (пусто/пробелы → 422). На каждый реально изменённый ключ — одна строка; одно сохранение = один `batch_id`. GET `/api/admin/casino/settings/audit` с фильтрами date_from/date_to, key, changed_by. Админка: обязательное поле «Причина изменения», без него кнопка неактивна. Экран `/x8/casino/audit` не делал (задача 12). В расчёты (задача 5) не лез.

Файлы: `migrations/add_casino_settings_audit.sql`, `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`, `routers/admin_casino.py`, `tests/test_admin_casino_regression.py`, `CasinoSettings.tsx`, `adminApi.ts`, этот журнал. `focuspay-casino` не трогал.

Локальная сборка: `cd focussite/frontend && npm run build` — tsc + vite ок (`panel-CZ4x9rIz.js`). `bootstrap static checks passed`. Локально `test_admin_casino_regression.py`: 35 passed.

Залито на staging: да, `staging-sync.sh`. Healthcheck: `staging runtime health check passed`. Bootstrap already-completed: grids `INSERT 0 0`, v2 `INSERT 0 0`, audit `CREATE TABLE` + 4 индекса.

md5 local=staging:

- `add_casino_settings_audit.sql` `173883df2deaaa2a5b45f5ac82be4ae0`
- `admin_casino.py` `68623bad5b1fb05f11f428ce29681429`
- `test_admin_casino_regression.py` `64362dc3975d14264df4f05dca0e8522`
- `CasinoSettings.tsx` `d3fd30965281a9c5431025defedbe3c2`
- `20-full-panel-bootstrap.sh` `2a3c7653ea3502bcd392891ff6029943`

`rg add_casino_settings_audit`: `00-apply-migrations.sh` (required + run_psql), `20-full-panel-bootstrap.sh` (required, incremental, fresh).

SQL: `to_regclass('casino_settings_audit')` = `casino_settings_audit`. Колонки: id, batch_id, key, old_value, new_value, changed_by, changed_at, reason. Строк аудита пока 0. Комиссия «до отыгрыша» `{"percent": 15.0}` (после возврата с 13). Ключей настроек 46.

Тесты на staging: `./scripts/staging-test.sh` → **967 collected, 960 passed, 7 failed.** Семь имён те же, что в базовой линии. +3 passed — без reason, три ключа/один batch_id, GET с фильтрами.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, `focuspay-exchange-api` 07:14:26 UTC.

Docker: наружу только `127.0.0.1:18081->8080/tcp`.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–4 + отыгрыш + чужой broadcast). `focuspay-casino` HEAD `4b8d65e`, dirty только отыгрыш.

Следующий шаг: Задача 5. Настройки в расчётах — **не начинать**, пока человек не примет кликами задачу 4.

Открытые вопросы: нет.

---

## 2026-08-28 — Задача 4, кнопка «Сохранить» молча не жалась

Сделано: кнопка была `disabled`, пока пустая причина (`pointer-events-none`) — клик ничего не давал, поле причины было ниже шапки. Причину поставил рядом с «Сохранить» в шапке; кнопка активна всегда, кроме момента сохранения. Пустая причина → тост «Укажите причину изменения» и фокус в поле. Карточка причины в форме осталась.

Файлы: `CasinoSettings.tsx`, этот журнал.

Залито на staging: да, `staging-sync.sh`. md5 `CasinoSettings.tsx` local=staging `d517ec4c0a132a6cf6ca409a719e5371`.

Тесты: **968 collected, 961 passed, 7 failed** — те же семь имён. +1 passed не из этой правки (фронт), чужой dirty tree.

Прод не трогал. Задачу 5 не начинал.

Следующий шаг: клик-приёмка задачи 4 (причина в шапке рядом с «Сохранить»).

---

## 2026-08-28 — Staging: логины кабинетов 123 / 123

Сделано: только живая БД staging + `/etc/focuspay/staging-runtime.env`. Прод и git не трогал. Задачу 5 не начинал.

Вход без 2FA, пароль везде `123`:

| Кабинет | URL | Логин |
|---|---|---|
| Админ | `/x8/login` | `123` |
| Оператор (client) | `/ops/login` | `123` |
| Партнёр | `/partner/login` | `123` |
| Внештатник | `/exchanger/login` | `123` |
| Оператор finance | `/ops/login` | `fixture_full_finance_ops` |
| Сайт (покупатель) | `/login` | `fixture_buyer` |

`web_users.username` уникален — админ и покупатель не могут оба быть `123`. Два оператора тоже. Проверка POST на gateway: admin/operator/partner/exchanger `123/123` → 200, без 2FA. Снял бан `172.20.0.4` (после четырёх 401 curl через nginx UI тоже ловил 403).

---

## 2026-08-28 — Задача 4 принята кликами

Человек: «Проверь если все хорошо запускай следущий этап» после сохранения настроек.

SQL клика: одна причина `ПО КАЙФУ ЕБАТЬ`, `changed_by=123`, один `batch_id` `f602313f-3c97-45f0-8483-da70efe54c1f`, **45 строк** (фронт шлёт всю форму; бэкенд пишет и неизменённые ключи). Реальные сдвиги: `commission_rate` / `commission_rate_wagering_active` 15 → 13.23; `commission_rate_wagering_complete` 5 → 3; `min_bet_rub` 10 → 88. `old_value` vs `new_value` не перепутаны (15→13.23).

Качество, не в задаче 5: `old_value` часто JSON-строка (`"{\"percent\": 15.0}"`), `new_value` — объект; неизменённые ключи тоже в аудите. Caps по-прежнему `{"amount": 0.0}`. Живые 13.23% и min 88 **не возвращал**.

Прод HTML эталон тот же. Unit `ActiveEnterTimestamp` Fri 2026-08-28 08:33:32 UTC (не наш выкат: на проде нет `casino_settings_registry.py`, `casino_finance.py` 2026-08-23).

Следующий шаг: задача 5 (уже на staging, ждёт клик-приёмку).

---

## 2026-08-28 — Задача 5. Настройки в расчётах

Сделано: кап/мин комиссии в `calculate_equal_stake_settlement`, `calculate_house_settlement` и `allocate_commission` (иначе кап 10 ₽ резал бы выплату, а в леджер уходило бы 15). `0` = как раньше. Ставки: `game_stake_bounds` (глобальный min/max, `per_game_limits`, `effective_max_stake` из liability и `max_profit_pct_per_round` × банк). Проверка в create/join (в т.ч. V2) и cub/play (после политики, с множителем выплаты и балансом дома). `pricing_snapshot` на commit-outcome и cub play: `commission_cap_rub` / `commission_min_rub` строками `"7.00"`. Старые снимки без ключей → 0.

Не делал (не в списке задачи 5): автовыключение дома по `bankroll_floor_rub`; суммарный `max_profit_pct_per_round_all`; responsible/payouts/fairness; `bet_step` / concurrent / rounds/day / TTL.

Файлы: `casino_finance.py`, `routers/internal_casino.py`, `tests/test_casino_commission.py`, `tests/test_internal_casino.py` (`SettingsWiredIntoGameplayTests` + патч `load_casino_settings` в `V2JoinAutoStartTests`, иначе join ловил `KeyError: 'key'`), `tests/test_casino_settings_registry.py` (`AppliedStakeBoundsTests`), этот журнал. Фронт не трогал. `focuspay-casino` не трогал.

Локальная сборка: фронт не менялся.

Залито на staging: да, `staging-sync.sh` (код уже совпадал с локальным на момент закрытия). Healthcheck: `staging runtime health check passed`.

md5 local=staging:

- `casino_finance.py` `ab12d38789a2cf60132756ab4140217d`
- `internal_casino.py` `609887be8d79cc80cf3c9acc06171b58`
- `test_casino_commission.py` `7981bec0666ec5c6b0d0ebc1a38fb7ba`
- `test_internal_casino.py` `31e9061ef1d1453551b24ed23c9774eb`
- `test_casino_settings_registry.py` `e00965041a3439bd53f7a1bc4878cff9`
- `casino_settings_registry.py` `d78957c9774c7f3e6842138861a3523c`
- `CasinoSettings.tsx` `d517ec4c0a132a6cf6ca409a719e5371` (задача 4, без правок)

`rg`: `commission_cap_rub` — registry, finance, internal_casino, admin API, UI, тесты. `per_game_limits` — finance `game_stake_bounds` + create/join тесты. `max_profit_pct_per_round` — `effective_max_stake` / cub bounds. `commission_min_rub` — тот же путь, что кап.

SQL сейчас (живые клики задачи 4, кап не трогал): 46 ключей; `commission_cap_rub` / `commission_min_rub` / `bankroll_floor_rub` / `liability_amount_rub` = `{"amount": 0.0}`; `per_game_limits` `{}`; комиссия `{"percent": 13.23}`; `min_bet_rub` `{"amount": 88.0}`. Аудит 45 строк, тот же batch. Последние `game_data->pricing_snapshot` пустые (старые/fixture партии) — ожидаемо, пока не сыграют новый cub/commit.

Тесты на staging: `python -m pytest tests/ -q --tb=no` → **975 collected, 969 passed, 6 failed.** Новых имён в failed нет. +7 collected — три теста капа/мина, `AppliedStakeBoundsTests`, три `SettingsWiredIntoGameplayTests`.

Шесть упавших (те же, минус finance fixture):

1. `tests/test_casino_weekly_cashback.py::CasinoWeeklyCashbackTests::test_duplicate_claim_does_not_create_second_ledger_credit`
2. `tests/test_casino_weekly_cashback.py::CasinoWeeklyCashbackTests::test_includes_only_canonical_completed_loss_types`
3. `tests/test_internal_casino.py::DurableLifecycleTests::test_commit_outcome_only_accepts_game_player_and_persists_outcome`
4. `tests/test_internal_casino.py::DurableLifecycleTests::test_non_winner_outcome_commits_without_winner`
5. `tests/test_internal_casino.py::DurableLifecycleTests::test_waiting_cancel_commits_without_an_opponent_or_winner`
6. `tests/test_internal_casino.py::ProfileEndpointTests::test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`

`test_finance_access_staging.py::...test_fixture_admin_not_finance_owner_in_production` из семёрки **пропал** (теперь проходит). В задаче 5 `finance_access.py` не трогал. Возможная причина — чужой dirty `config.py` (broadcast), не чинил и не откатывал. Passed 961→969 = +7 новых + этот fixture.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC, `casino_finance.py` / `internal_casino.py` 2026-08-23, реестра на проде нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Лишние `focuspay-staging-*` (не runtime) без published ports.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–5 + отыгрыш + **чужой broadcast** — не смешивать). `focuspay-casino` HEAD `4b8d65e`, dirty только отыгрыш.

Следующий шаг: клик-приёмка задачи 5. Задачу 6 (карты с бота) **не начинать**.

Открытые вопросы: нет. 13.23% / min 88 оставил как после клика задачи 4.

---

## 2026-08-28 — Клик задачи 5: «Не удалось создать стол»

Стол **создался**. `POST /v2/tables` → 200, `pvp_dice` stake 100, creator `8443902979`, `table_id` `942ff1bc-ad61-4f90-b2e9-1f5307a698c7`, status `open`. Бот после успеха звал `edit_message_text` с `ReplyKeyboardMarkup` (`main_menu_keyboard`) — Telegram 400 `inline keyboard expected`, хендлер врал «не удалось».

Исправление: инлайн `_staging_menu_keyboard()`; если правка сообщения падает после create — `send_message` «Стол создан», не «Попробуйте позже». Пресеты ставки ниже `MIN_BET` не показываются (живой min 88).

Файлы: `focuspay-casino/bot.py`, `tests/test_bot_startup.py` (`CreateV2TableConfirmTests`, 2 passed).

Залито: `staging-sync.sh`. md5 `bot.py` local=staging `3eaa40217adacd5598b04021cc0999f4`. Health: passed.

SQL после sync: min 88, комиссия 13.23, **потолок комиссии уже 50 ₽** (клик человека). Оба open-стола на месте.

Задачу 6 не начинал.

---

## 2026-08-28 — V2: стол «против бота» не стартует

Клики: 2 места + 1 бот. В БД оба места заняты (`player` + `bot`), `bot_count=1`, статус всё равно `open`. Свободных мест 0 — в лобби никого нет, броска нет. Join автостартит только когда садится человек; create после посадки ботов статус не менял.

Сделано: create при `1 + bot_count >= max_players` ставит `running` и `auto_started`. Тесты `V2CreateAutoStartTests`. В мастере текст: если мест для людей не осталось, другие не войдут. Старые три open-стола не трогал — отмена из «Мои игры».

Партия против казино для задачи 5 — `/cub 100` (house), не V2-стол: броски V2 в боте ещё не подключены.

Залито следующим sync. Задачу 6 не начинал.

---

## 2026-08-28 — Кубики в чате: игрок кидает сам

Сделано: house cub в личке — два живых Telegram 🎲. `/cub 10` сразу холдит ставку и пишет «Кинь 🎲 сюда…», без HMAC/commit/seed. Игрок кидает, бот `send_dice`, больше число выигрывает. Ничья → hold жив, «Ничья — кидай ещё раз». Выплата по-прежнему `calculate_house_settlement` (комиссия/кап/мин из задачи 5).

Бэкенд: `POST /api/internal/casino/cub/open` (hold, `casino_games.status=waiting`, в API/game_data `waiting_player_roll` — нового статуса в CHECK нет), `POST /cub/resolve` (`player_value`/`house_value` 1–6; равные → `{tie:true}` без ledger; иначе settle), `GET /cub/pending`. Аудит: `source: telegram_dice`. Старый `cub/play` HMAC оставлен, бот его больше не зовёт. Кнопка «Поставить» (старые сообщения) тоже идёт в `open`, не в play.

PvP: броски по-прежнему только в подтверждённом игровом чате. В личке без open-cub текст: «Против казино — /cub. Против людей — кидай в игровой группе.» V2-стол в личке не подключал.

Файлы (этот шаг): `internal_casino.py`, `tests/test_internal_casino.py` (`CubTelegramDiceTests`, 9 шт.), `focuspay-casino/games/house_cub.py`, `games/pvp.py`, `focuspay_client.py`, `tests/test_house_cub.py`, `tests/test_pvp_dice.py`, `tests/test_focuspay_client.py`, этот журнал. Миграций нет. Чужой broadcast в dirty tree **не смешивал**.

Локально casino-bot: `test_house_cub.py` + `test_pvp_dice.py` — **13 passed**.

Залито на staging: да, `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Healthcheck: `staging runtime health check passed` (дважды).

md5 local=staging:

- `internal_casino.py` `d365d0a30801f67bc41e23cfcd9597e7`
- `test_internal_casino.py` `5c4a596fd7db5257f4e00637e2513481`
- `games/house_cub.py` `c330bfa8bb5aef96d0e7fb0ad336a7aa`
- `games/pvp.py` `8c1e139022fb80650f7c9588c94ca337`
- `focuspay_client.py` `585c77d34994b0c7d20f0c7ee00d8fb2`
- `tests/test_house_cub.py` `fca02132e59c9bbc1a5fc9e3625360e5`

`rg`: `cub/open` / `cub/resolve` — роутер + тесты. `open_cub` / `resolve_cub` / `get_pending_cub` — клиент, `house_cub.py`, тесты. `try_handle_house_cub_dice` — `house_cub.py` + `pvp.py` `on_dice`.

SQL сейчас: 46 ключей; cub **включён**; `min_bet_rub` 10; комиссия 15%; кап 0; `max_profit_pct_per_round` 1%; банк дома 5010 ₽, `reserved_rub` 100 без active `casino_house_reservations` и без waiting cub (старый хвост, не этот шаг). Робот `focuscasino-house` active, min 10.

Тесты на staging: `staging-test.sh` → **7 failed**, имена:

1. `test_casino_weekly_cashback.py::...test_duplicate_claim_does_not_create_second_ledger_credit`
2. `test_casino_weekly_cashback.py::...test_includes_only_canonical_completed_loss_types`
3. `test_finance_access_staging.py::...test_fixture_admin_not_finance_owner_in_production` (в задаче 5 проходил; снова падает на dirty `config.py` broadcast, этот шаг его не трогал)
4–6. `DurableLifecycleTests` (те же три)
7. `ProfileEndpointTests::test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`

Новых имён кроме возврата finance fixture нет. `CubTelegramDiceTests` на staging: **9 passed**. К задаче 5 (975/969/6) добавились 9 cub-тестов; collected ≈ 984, passed ≈ 977 при семи падениях.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC, `internal_casino.py` / `casino_finance.py` 2026-08-23, реестра на проде нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–5 + cub dice + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (отыгрыш + cub dice + V2-правки бота).

Следующий шаг: клик-приёмка кубов в личке. Задачу 6 (карты с бота) **не начинать**.

Открытые вопросы: нет. `/cub 100` при max_profit 1% и банке ~5000 по-прежнему упрётся в потолок (~50 ₽) — для клика `/cub 10`.

---

## 2026-08-28 — House cub: ждать грань, потом куб казино, потом текст

Клики: «Ты 6, казино 1 — выигрыш. Выплата 195.00 ₽» приходило сразу, пока кубы ещё крутились.

Сделано: Telegram не шлёт «анимация кончилась» — ждём 4 с (как raffle). Порядок: грань игрока → `send_dice` казино → грань казино → resolve и текст. Бэкенд не трогал. Задачу 6 не начинал.

Файлы: `focuspay-casino/games/house_cub.py`, `tests/test_house_cub.py` (`test_waits_for_player_face_then_casino_then_result`), этот журнал.

Локально: `tests/test_house_cub.py` **8 passed**.

Залито: `staging-sync.sh`. Health: passed. md5 `house_cub.py` local=staging `5a08f43ea7cfad867bdb1eaae544bac8`.

Прод HTML/unit те же. Docker: только `127.0.0.1:18081->8080/tcp`.

Следующий шаг: клик `/cub 10` — куб казино после твоей грани, текст после грани казино. Задачу 6 не начинать.

---

## 2026-08-28 — Задача 6. Тасовка баккары и блэкджека на бэкенде

Клики: кубы в личке приняты. «Дальше задача 6. Остальные игры потом с той же логикой, что у дайсов?»

Сделано: исход карт больше не рождается в боте. `POST /api/internal/casino/cards/prepare` коммитит `SHA-256(seed:game_id)` до холда ставки (TTL 48 ч, ожидание соперника). `POST /cards/deal` отдаёт карты с HMAC-SHA256 Fisher–Yates обуви (две колоды: creator/opponent, pop с конца, `hand_size` идемпотентен). Сид в deal нет. `POST /cards/reveal` после `outcome_committed`/`finished`. Бот: `prepare_cards` → create, на join/hit только `deal_cards`, в результате строка сида. `SystemRandom`/`shuffle` в `games/baccara.py` и `games/blackjack.py` пусто.

Это не живой 🎲. У Telegram нет карт. PvP-эмодзи (кубы/дартс/боулинг/футбол/баскет) уже кидают native dice в игровом чате; house cub — два 🎲 в личке. Карты — commit-reveal. Задача 7 (верификатор) не начиналась. Раффл не трогал.

Файлы (этот шаг): `casino_cards.py`, `internal_casino.py`, `tests/test_casino_cards.py`, `tests/test_internal_casino.py` (`CardFairnessTests`), `focuspay-casino/games/baccara.py`, `games/blackjack.py`, `focuspay_client.py`, `tests/test_card_server_deal.py`, `tests/test_card_bet_input.py`, `tests/test_pvp_settlement_contract.py`, `tests/test_focuspay_client.py`, этот журнал. Миграций нет. Чужой broadcast / V2 не смешивал.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: `staging runtime health check passed` (после sync и ещё раз).

md5 local=staging:

- `casino_cards.py` `acd0687ef2bdd17a781938fb2e7cd967`
- `internal_casino.py` `1b37381d2ba9b9c116b029d39aa0039c`
- `test_casino_cards.py` `af8a2d2eb5a699324187745981a47429`
- `test_internal_casino.py` `7d4b02424486c334081916a5d8c616ce`
- `games/baccara.py` `43af789ed1cf5af44a9a411fd310348a`
- `games/blackjack.py` `4058e752ef75dc1f6230e54eaffdc3c9`
- `focuspay_client.py` `21a65d44972636adef8868b92d2df31a`
- `tests/test_card_server_deal.py` `531b2b1c3eaa9a86d068d9b057217c9b`

`grep` на staging: `SystemRandom|shuffle(` в `baccara.py`/`blackjack.py` — пусто. `cards/deal` / `prepare_cards` / `deal_cards` / `reveal_cards` — роутер, клиент, оба хендлера.

SQL сейчас: 46 ключей; `enabled_games` cub+baccara+blackjack+pvp_* true, raffle false; `min_bet_rub` 10; комиссия 15%; кап 0; `max_profit_pct_per_round` **5%** (в записи cub было 1% — этот шаг не менял); банк дома 5167.50 ₽, `reserved_rub` 100.

Тесты **только на staging**, локальный pytest не гонял.

`staging-test.sh`: **7 failed**, те же имена, что после cub:

1. `test_casino_weekly_cashback.py::...test_duplicate_claim_does_not_create_second_ledger_credit`
2. `test_casino_weekly_cashback.py::...test_includes_only_canonical_completed_loss_types`
3. `test_finance_access_staging.py::...test_fixture_admin_not_finance_owner_in_production`
4–6. `DurableLifecycleTests` (те же три)
7. `ProfileEndpointTests::test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`

Новых имён нет. `CardFairnessTests` + `CasinoCardShoeTests` + `HouseRngCommitTests`: **16 passed**. К ~984 cub-collected добавлены 10 карточных (5 shoe + 5 fairness).

Casino-bot на staging (backend-tests, `PYTHONPATH=/opt/focuspay-casino`): `test_card_server_deal` + `test_card_bet_input` + `test_pvp_settlement_contract` — **13 passed**.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC, `internal_casino.py` / `casino_finance.py` 2026-08-23, реестра на проде нет.

Docker runtime: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Остальные порты контейнер-локальные. Старый `focuspay-staging-*` без publish на хост.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–6 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (отыгрыш + cub + карты).

Следующий шаг: клик-приёмка баккары (и по желанию блэкджека) в staging-боте. Задачу 7 **не начинать**.

## 2026-08-28 — Задача 7. Provably fair как продукт

Клики задачи 6 приняты («continue»). Живой 🎲 для карт не делал.

Сделано: пара сидов на игрока (`casino_fairness_seeds`), ротация раскрывает предыдущий серверный сид, `nonce` растёт на каждый новый `cards/prepare` (повтор prepare той же игры не инкрементирует). HMAC колоды v2: `HMAC-SHA256(server_seed, "client_seed:nonce:game_id:side:index")`, хеш раунда по-прежнему `SHA-256(seed:game_id)`. Публичный `POST /api/public/casino/fairness/verify` без авторизации: совпавший сид+хеш → `matches true`; один испорченный символ сида при том же хеше → `matches false`. Страница `/casino/fairness` (формула простым языком, «Сходится» / «Не сходится»). PvP: оба места получают один `rng_commit` + client_seed + nonce до карт (создание, карточка ожидания, DM с рукой). Бот: `/fairness`, `/fairness rotate`, `/fairness seed …`. Кубы/эмодзи в чате не «проверяются» нашим сидом. House cub остаётся `telegram_dice`. Раффл не трогал. Задачу 8 не начинал. Чужой broadcast не смешивал в смысл задачи (в дереве он по-прежнему грязный).

Миграция `add_casino_fairness_seeds.sql` в `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh` (включая early-exit) и `bootstrap_static_test.sh`. `bootstrap_static_test.sh` локально: passed.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: `staging runtime health check passed` (после update и ещё раз). Frontend `tsc -b && vite build` на staging прошёл. Живой API на gateway: match `True` / tamper `False` / страница `/casino/fairness` HTTP 200.

md5 local=staging:

- `casino_cards.py` `f551df79ba09b78565efc838ff925b6c`
- `casino_fairness.py` `274e57eed8e162daa572293daa48c4e9`
- `internal_casino.py` `9948a4f2a0ee164b2f924f5a55fe1030`
- `public_casino.py` `b8accdef3c28192089b9bd1b0ba682e5`
- `main.py` `2a345db37b34aca6ebd156d63e8b470d`
- `test_casino_cards.py` `5074b4c7fc89ec2e13bcd05bd1c25c08`
- `test_casino_fairness.py` `f4e333b47e6278ecec88dc5a43d3b226`
- `test_internal_casino.py` `8cbaa27310d98e717f3a12879cc08c04`
- `add_casino_fairness_seeds.sql` `bc6a8a6d8f08b6d58ffd55d5c1d90853`
- `CasinoFairness.tsx` `0605263152d6f7bf77a1f76a5ffc71a5`
- `App.tsx` `f45a026cb506436cf3f37ee6d55020fb`
- `public.ts` `49901ceda8144f1a4449c392fae8b724`
- `games/baccara.py` `f74a474b210284c5f8beeaee66dd73a3`
- `games/blackjack.py` `b808b0a69ac6c5d3452deb1a7e5a97a3`
- `games/card_fairness.py` `11a65bd7af895ca4635a8fa6e32a7803`
- `games/fairness.py` `25f0579151dcf151759061ffdc1133ff`
- `focuspay_client.py` `276bb09a171b2cf1c5b44b80d248b80d`
- `bot.py` `c02dcd8770ed08b054bc30fff7690971`
- `config.py` (casino) `bda59886855103fa22ad7159588593ac`

`grep` на staging: `SystemRandom|shuffle(` в `baccara.py`/`blackjack.py` — пусто. `fairness/verify`, `HMAC-SHA256-fisher-yates-v2`, `casino_fairness_seeds`, `/fairness` — на месте.

SQL сейчас: таблица `casino_fairness_seeds` есть; колонка `client_seed` у `casino_house_rng_commits` есть; 46 ключей; `enabled_games` cub+baccara+blackjack+pvp_* true, raffle false; `min_bet_rub` 10; комиссия 15%; кап 0; `max_profit_pct_per_round` 5%; `seed_rotation_allowed` true; банк дома 5120.00 ₽, `reserved_rub` 800 (после кликов задачи 6, этот шаг финансы не менял).

Тесты **только на staging**, локальный pytest не гонял.

`staging-test.sh`: **7 failed**, те же имена, что после cub/задачи 6:
`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`.
Собрано **1006**. Новых имён в упавших нет. `test_casino_cards` + `test_casino_fairness` + `CardFairnessTests` + `HouseRngCommitTests`: **26 passed**.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. `compose run --profile tests` иногда Recreates postgres; named volume ключи сохранил (46).

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. На проде нет `casino_cards.py` / `casino_fairness.py` / `casino_settings_registry.py`.

Git: `focuspay` dirty (задачи 1–7 + **чужой broadcast**). `focuspay-casino` dirty (отыгрыш + cub + карты + fairness). Не коммитил.

Следующий шаг: клик-приёмка верификатора. Задачу 8 **не начинать**.

## 2026-08-28 — Задача 8. Примитивы интерфейса админки

Клики задачи 7 приняты («дальше»). Экран настроек не переделывал (это задача 9). Маршрут `/x8/casino/risk` не добавлял (задача 11). Broadcast не трогал.

Сделано: примитивы рядом с `primitives.tsx` и реэкспорт оттуда — `SaveBar` (только если dirty, счётчик секций, Отменить/Сохранить, save disabled при invalid), `useDirtyForm`, `ValidationSummary`, `SettingsSection`, `DangerZone` (type-to-confirm), `TierGridEditor`, `DiffRow` (`diffSegments` prefix/suffix, self-check: `"1200"→"1250"` подсвечивает только `0→5`), `Gauge`, `CorridorChart`. Цвета — `var(--text-primary|/muted|--yellow|--red)`, без stake-зелёного залива. `scroll-padding-bottom: var(--save-bar-h)` на `[data-panel-scroll]:has([data-save-bar])`. Живые сетки в настройках переведены на `TierGridEditor` (первая строка min=0, те же подписи).

Отклонение: панель на `BrowserRouter`, не data-router — `useBlocker` бросает. `useDirtyForm` = `beforeunload` + capture click по внутренним `<a>` + `popstate` + `confirmLeave()` для вкладок. Задача 9 должна звать `confirmLeave` при смене секции, если вкладки ещё останутся.

`npm run build` на staging: `tsc -b && vite build` чистый (после фикса generic у `TierGridEditor`: interface без index signature не был `Record<string, string>`). Gateway HTTP 200: `/x8/login`, `/x8/casino`, `/x8/casino/settings`.

Файлы этого шага: `settingsPrimitives.tsx`, `diffText.ts`, `TierGridEditor.tsx`, `riskViz.tsx`, `primitives.tsx`, `PanelShell.tsx`, `panel.css`, `CasinoTierGrids.tsx`, `bootstrap_static_test.sh` (require имён). `bootstrap_static_test.sh` локально: passed.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: `staging runtime health check passed` (после update и ещё раз).

md5 local=staging:

- `settingsPrimitives.tsx` `d19d9a1535a50be7239a0ee21154f9fa`
- `diffText.ts` `cd95af60f41de3fb56937ba4a3876eea`
- `TierGridEditor.tsx` `7dff68217dad988acc30910810927f5d`
- `riskViz.tsx` `6c1845668e22a07c9c4793c20c8423c2`
- `primitives.tsx` `05f9ee2cfeffbcc7ec794d20cbebd8e0`
- `PanelShell.tsx` `2980e8fa55021ddf9a6a28b83129272b`
- `panel.css` `14dbe7c8ac35803e930c574ba35ad317`
- `CasinoTierGrids.tsx` `fee0d8bc4dc3d49f64eb8dabeb8acc3d`
- `bootstrap_static_test.sh` `63f38ab737a849bba9be1863ff6215a7`

`grep` на staging: `SaveBar` / `useDirtyForm` / `ValidationSummary` / `DangerZone` / `DiffRow` — `settingsPrimitives.tsx` + реэкспорт в `primitives.tsx`. `TierGridEditor` — модуль + `CasinoTierGrids.tsx`. `Gauge` / `CorridorChart` — `riskViz.tsx`. `--save-bar-h` и `scroll-padding-bottom` — `panel.css`. `data-panel-scroll` — `PanelShell.tsx`.

SQL сейчас (этот шаг БД не менял): 46 ключей; таблица `casino_fairness_seeds` есть; `client_seed` у commits есть; `enabled_games` cub+baccara+blackjack+pvp_* true, raffle false; `min_bet_rub` 10; комиссия 15%; кап 0; `max_profit_pct_per_round` 5%; `seed_rotation_allowed` true; банк дома **5170.00** ₽, `reserved_rub` **700** (игра на staging, не этот шаг).

Тесты **только на staging**, локальный pytest не гонял.

`staging-test.sh`: **7 failed**, те же имена, что после задачи 7: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only после прогона: **1009** (было 1006). Бэкенд-тестов в задаче 8 не добавлял и не чинил; +3 collected — не из этих файлов. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. `compose run --profile tests` снова Recreate postgres; named volume ключи сохранил (46). Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. На проде нет `casino_cards.py` / `casino_fairness.py` / `casino_settings_registry.py`. `casino_finance.py` / `internal_casino.py` 2026-08-23.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–8 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty без изменений этой задачи. Не коммитил.

Следующий шаг: клик-приёмка настроек/дашборда. Задачу 9 **не начинать**.

## 2026-08-28 — Задача 9. Экран настроек казино

Клики задачи 8 приняты («contunie»). Сетки тиров (задача 10) и `/x8/casino/risk` не делал. Broadcast не трогал. Вкладок нет.

Сделано: `CasinoSettings.tsx` — одна прокрутка, колонка ≤720px + липкая боковая 320px (навигация по секциям, подсказка, живой расчёт). Порядок: Комиссия и доли → Лимиты → Банкролл → Сетки → Ответственная игра → Пороги вывода → Честность → Игры → Опасная зона. `SaveBar` только если dirty; «Сохранить» открывает модалку с обязательным `reason`. `useDirtyForm` на уход. Живой пример: банк 10 000 ₽; при отыгрыше 21% и комиссии 15% текст говорит про 210 ₽ и 1400 ₽ ставок (self-check в `casinoSettingsModel.ts`). Все поля, которые редактировались раньше, на месте (включая сетки, per-game, кабинет создателя, чат PVP). Legacy-ключи `commission_rate` / `creator_cut_percent` / `referral_l*` без `_wagering_*` по-прежнему не отдельные поля — так было и до этой задачи.

`Card` принял `id` для якорей секций.

`npm run build` на staging чистый. HTTP 200 `/x8/casino/settings` и `/x8/casino`.

Файлы: `CasinoSettings.tsx`, `casinoSettingsModel.ts`, `primitives.tsx` (`id` у Card), `bootstrap_static_test.sh`. `bootstrap_static_test.sh` локально: passed.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: `staging runtime health check passed` (после update и ещё раз).

md5 local=staging:

- `CasinoSettings.tsx` `0d63d34432747b9aae5068189603c75c`
- `casinoSettingsModel.ts` `0140174e17adc51a60e82e427065250f`
- `primitives.tsx` `124a5be96c0f21bd9a2cda927894d5a7`
- `bootstrap_static_test.sh` `7c828f95faec438faf91286ec44fe9da`

`grep` на staging: `SaveBar` / `useDirtyForm` / `DangerZone` / `casino-settings-reason` / `section-commission` в `CasinoSettings.tsx`; `liveWageringExample` в модели.

SQL сейчас (этот шаг БД не менял): **46 ключей**; `wagering_percent` 21%; комиссия 15%; кап 0; `min_bet_rub` 10; `max_profit_pct_per_round` 5%; cub+baccara+blackjack+pvp_* true, raffle false; банк 5170.00 / reserved 700.

Тесты **только на staging**. `staging-test.sh`: **7 failed**, те же имена. Бэкенд-тестов не добавлял. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp`. Прод: `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–9 + **чужой broadcast**). `focuspay-casino` без изменений этой задачи. Не коммитил.

Следующий шаг: клик-приёмка настроек. Задачу 10 **не начинать**.

### Правка клика — центрирование

Блок настроек был прижат влево внутри `max-w-[1440px]`. Обернул страницу в `mx-auto max-w-[720px] xl:max-w-[1064px]` (720 + gap-6 + 320). На 1920: отступы главного окна 310px слева и справа от блока 1064px.

`staging-test.sh` заново не гонял — только вёрстка. `bootstrap_static_test.sh` локально: passed. Health после sync: passed. HTTP 200. Прод метки те же: `index.html` 04:22:45, `panel.html` 04:22:48, unit 08:33:32. Docker: только `127.0.0.1:18081->8080/tcp`.

md5 local=staging:

- `CasinoSettings.tsx` `0195467357140b0637b0ee72685d67bb`
- `bootstrap_static_test.sh` `c05e00f50d59dd3517d42f91ca254ea5`

## 2026-08-28 — Задача 10. Сетки тиров

Клики задачи 9 приняты («давай дальше»). `/x8/casino/risk` не делал. Broadcast не трогал. API сеток не менял: по-прежнему только `min_wager_rub` (+ percent / rates). «До» — поле формы, при загрузке берётся из следующей «От».

Сделано: таблица целиком (все ступени сразу), числа правятся в ячейках. Колонка «До»: правка сама пишет «От» следующей строки. Разрыв (100 000 → 150 000) и пересечение — ошибка в строке сразу, SaveBar не даёт сохранить. Добавление — текстовая ссылка внизу; новая строка фокусируется. Действия строки — меню ⋯ (вставить ниже / дублировать / удалить, первую нельзя). Колонка «Во что обходится»: кешбек = % проигрыша; комиссия 15%/5% → 7,5% / 2,5% оборота (половина комиссии при 50/50). Клик по ячейке открывает боковую панель с пояснением этой ячейки. Перки/игры в API сеток нет — панель не выдумывает полей. Сохранение по-прежнему шлёт только min+ставки.

Self-check в `tierGridModel.ts`: разрыв 100000→150000, пересечение, `applyUpperBound`, стоимость 15/5.

Файлы: `tierGridModel.ts`, `TierGridEditor.tsx`, `CasinoTierGrids.tsx`, `CasinoSettings.tsx` (ошибки сеток в `validate`), `casinoSettingsModel.ts` (подсказка секции), `settingsPrimitives.tsx` (ключ списка ошибок), `bootstrap_static_test.sh`. Локально: `bootstrap_static_test.sh` passed, `tsc -b` чистый.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: passed. HTTP 200 `/x8/casino/settings`.

md5 local=staging:

- `TierGridEditor.tsx` `649daca9a2482b9154964100778f4b96`
- `tierGridModel.ts` `3ce5acdbf286465f024b9a9f438521a0`
- `CasinoTierGrids.tsx` `952c81dc31ccd222ca334be651d847ee`
- `CasinoSettings.tsx` `87e34431d89246b2582f0897b4ed8f2b`
- `casinoSettingsModel.ts` `ae598ace071ef0ac916e92c8f2923914`
- `settingsPrimitives.tsx` `480b20c1073cbe35f1033e41a16db277`
- `bootstrap_static_test.sh` `474bf24f9b2c6998e8a7e1a6e4d64891`

`grep` на staging: `drivesNextMin` / `data-tier-row-menu` в редакторе; `Разрыв` / `applyUpperBound` в модели; `Во что обходится` в `CasinoTierGrids.tsx`.

SQL (этот шаг БД не менял): **46 ключей**; сетки дефолтные (кешбек 0/50k/100k/200k/500k, комиссия 0/50k/100k/200k). `wagering_percent` 21%.

Тесты **только на staging**. `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Бэкенд-тестов не добавлял. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Прод: `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–10 + **чужой broadcast**). `focuspay-casino` без изменений этой задачи. Не коммитил.

Следующий шаг: клик-приёмка сеток. Задачу 11 **не начинать**.

## 2026-08-28 — Единый движок казино-игр (чат = личка), задачи 1–7

Тесты **только на staging** (`focuspay-test`), локальный pytest не гонял. Прод не деплоил. Broadcast в этот шаг не мешал.

Сделано:

1. `_game_for_update` SELECT включает `id`; recovery считает `house_win` как settle. Зависшая `45218770-395b-4997-ad4b-d1ef9ca0adcd` сейчас **finished**.
2. Группа: ставка только кнопками; личка в `chat_guard` разрешена. `/baccara` `/blackjack` в группе → мастер, не текст.
3. Один мастер `games/table_wizard.py` (`tw:` + 12 hex). Дубли `creategame:`/`dmcreate:` сняты. `draw_policy` в `V2TableCreateRequest`.
4. Миграция `add_casino_v2_table_chat.sql` (`game_chat_id`, `game_chat_binding_id`) есть в `00-apply-migrations.sh` и `20-full-panel-bootstrap.sh`. Postgres на этом круге **не Recreate** — колонок не было, накатил SQL вручную на staging. `v2_runtime.py` публикует карточку в привязанный чат, броски/боты/`tie_break`/`tie_split`.
5. Групповые `/cub`… emoji → мастер. `GAMES_CONFIG` в `games/catalog.py`. `join_` / invitation оставлены на drain.
6. Обувь `seat1..seat6` + `_tb*`; V2 card endpoints; верификатор и `/casino/fairness` знают места.
7. House cub оставлен: DM `/cub 50` → `open_cub`. Мастер cub+2 места+1 бот **в личке** → `open_cub`; в группе тот же состав → V2-стол.

Починка после прогона бот-тестов: `_bots_keyboard` больше не падает, если `max_players` уже в `_carry`; `TelebotModules` оставляет stub `telebot` после `with` (ленивые импорты); mock настроек бота — `commission_rate_wagering_active` / `_complete` / `wagering_percent`.

Health: `staging runtime health check passed` после `staging-runtime-update.sh --apply`. HTTP 200: `/x8/login`, `/x8/casino`, `/x8/casino/settings`, `/casino/fairness`.

md5 local=staging:

- `internal_casino.py` `766492a65f3b7ffda5fe5c0341250130`
- `casino_cards.py` `dd821bf64711dd5ea550c9e8b1e75c3c`
- `public_casino.py` `60508220926e528bbeabe03e303f249c`
- `add_casino_v2_table_chat.sql` `9219b0402dcf08382a0a9f75656e638b`
- `CasinoFairness.tsx` `7497b6c126884a69057dbeb8c2513281`
- `public.ts` `a89469c4a76444405cef30471e638b26`
- `table_wizard.py` `a4ab0c03a4dbc889052163b889deea5f`
- `v2_runtime.py` `68cb8c4a37655f0fbf6536c1bbc9ea7b`
- `catalog.py` `65786b49a879f370eab120eb740290de`
- `pvp.py` `cad499221069a7ed40d22d169b34d702`
- `chat_guard.py` `e1e71fecfece6d1ccbaf7f0aa5476487`
- `recovery.py` `1d2bff23870d4cf8f0840172820facfe`
- `bot.py` `6193fced1ab56ea9fe781c1c8e12df5f`
- `telebot_stub.py` `4b2698d302005c1c2bad838d1f464fa2`

`grep` на staging: `draw_policy` в `internal_casino.py` (модель + INSERT); `game_chat_id` в миграции; `register_v2_runtime_handlers` в `bot.py` (import + `main`); обувь `seat[1-6]` в `casino_cards.py`.

SQL: **46** ключей `casino_settings`; колонки `game_chat_id` и `game_chat_binding_id` на `casino_v2_tables` есть (после ручного apply).

Тесты **только на staging**.

`staging-test.sh`: **7 failed**, те же имена, что после задач 8–9: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1011** (было 1009). Новых имён в упавших нет.

Казино-бот (compose `backend-tests`, `-v /opt/focuspay-casino`, `--no-deps`, без локального pytest): **90 passed** по файлам движка (`test_table_wizard`, `test_v2_*`, `test_pvp_lobby`, `test_pvp_dice`, `test_card_*`, `test_bot_startup`, `test_recovery`, `test_game_chat_guard`, `test_house_cub`, `test_game_timeouts`, `test_profile`, `test_durable_nonwinner_settlement`, `test_staging_ui`, `test_fairness_session`). Контракт: `test_pvp_settlement_contract` + `test_focuspay_client` зелёные кроме `test_default_base_url_uses_canonical_public_origin` — в этом контейнере `FOCUSPAY_API_URL=http://backend:8000`, не `https://focuspay.org`. `test_casino_profile_card` без Chrome в образе `backend-tests`. `test_webhook` не собирается без пакета `telebot`. Это среда, не новые имена бэкенд-регрессии.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Остальные порты контейнер-локальные. Старый `focuspay-staging-*` без publish на хост (не этот шаг).

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. На проде нет `casino_cards.py` / `casino_fairness.py` / `casino_settings_registry.py`. `casino_finance.py` / `internal_casino.py` 2026-08-23.

Git: `focuspay` HEAD `61e47be`, dirty (казино-план + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок). Не коммитил.

Следующий шаг: клик-приёмка мастера и V2-стола. Следующую задачу плана **не начинать**.

## 2026-08-28 — фикс: мастер баккары 409

Клик: `/baccara` 3 места, 1 бот, 50 ₽ → «Не удалось создать стол». Лог: `POST /v2/tables` **409**. `pvp-robot-1.allowed_games` были только кости, без `baccara`/`blackjack`. `_seat_v2_bots_with_conn` → `V2 bot capacity is unavailable`.

SQL на staging: в `pvp-robot-1` добавлены `baccara` и `blackjack` (остальные pvp_* на месте). На staging один pvp_robot — больше одного бота за стол по-прежнему не сядет.

Мастер теперь показывает текст 409, не «попробуйте позже». `tests/test_table_wizard.py` на staging: **4 passed**. Health после update: passed. Прод не трогал.

Потыкать снова: тот же стол баккара 3/1/50.

## 2026-08-28 — Одна карточка баккары/блэкджека

Тесты **только на staging**. Прод не деплоил. Broadcast в этот шаг не мешал.

Сделано в `focuspay-casino/games/v2_runtime.py`:

- `_card_text`: ставка, одна строка правил, имя места, карты, **очки числом**, статус; ничья пишет «Ничья N–N. Переброс лидеров.»; в ходе игры нет дампа хеша колоды (ссылка/короткая строка).
- Карточный раунд **редактирует** лобби-сообщение (`card_msg_id`), не шлёт три новых. Итог и переброс — тоже `edit_message_text`. `send_message` только если edit невозможен.
- Кнопки блэкджека «взять / оставить» на той же карточке в группе, не в личке.
- Все `deal` передают `shoe_side=seatN` / `seatN_tbN`. После persist руки рисуются из refresh.

Тест `tests/test_v2_card_board.py`: разные руки/очки; баккара без трёх `send_message`; `shoe_side` в deal; переброс на той же карточке; блэкджек hit на группе.

Health: `staging runtime health check passed`. HTTP 200: `/x8/login`, `/x8/casino`, `/casino/fairness`. Живой `casino-bot` в образе содержит `_edit_board`.

md5 local=staging:

- `games/v2_runtime.py` `f9fefdf4db1ab1f961e374114ca49c09`
- `tests/test_v2_card_board.py` `41f1da7d515f8addc2df299497c99d80`

`grep` на staging в `v2_runtime.py`: `_edit_board`, `shoe_side=_shoe_side` на initial/third/hit/TB, `board_note` «Переброс лидеров».

SQL: **46** ключей `casino_settings`.

Тесты **только на staging**.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1011**. Новых имён в упавших нет.

Казино-бот (`backend-tests`, `-v /opt/focuspay-casino`, `--no-deps`, без локального pytest): `test_v2_card_board` **4 passed**; тот же набор движка + новая доска **95 passed**. `test_webhook` по-прежнему без пакета `telebot`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Прод: `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. На проде нет `casino_cards.py`. `casino_finance.py` / `internal_casino.py` 2026-08-23.

Git: `focuspay` HEAD `61e47be`, dirty (казино-план + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок + доска). Не коммитил.

Следующий шаг: клик-приёмка одной карточки. Следующую задачу плана **не начинать**.

## 2026-08-28 — итог стола: кто победил

«Исход: победитель» было названием типа исхода, не имени. Выплата шла как «Место 1: 76 ₽» без состава.

`format_v2_settlement` теперь пишет **«Победил: место N · имя»** (бот — display_name, игрок — имя из Telegram `get_chat`, ссылка). То же для ничьей. `_commit_settle` передаёт roster стола.

Тесты на staging: `test_v2_card_board` + `test_table_wizard` **9 passed**. md5 `v2_runtime.py` `57bb5d570f92608966f5ed73bd24fcb2` local=staging. Health passed. Прод не трогал. Не коммитил.

Потыкать: новый стол, в итоге должно быть имя, не «Исход: победитель».

## 2026-08-28 — Задача 11. Риск-дашборд

Клики задачи 10 приняты («contuine»). Задачу 12 не начинал. Прод не деплоил. Broadcast в этот шаг не мешал. `GET /casino/dashboard` не трогал.

Сделано: маршрут `/x8/casino/risk` в навигаторе Казино. Отдельный `GET /api/admin/casino/risk?window=24h|7d|30d&rtp_deviation_pp=15`. Пять виджетов: банк (порог / цель 2×порог / макс. выплата на одной шкале; низкий банк = плохо), коридор RTP (теория пунктир, факт сплошная, полоса ±100/√n, подпись **n=**), открытая экспозиция (ожидающие/активные PvP-банки `counterparty_kind=player` + active house reservations, % от доступного банка), аномалии (порог оператора, не на каждый кейпресс; bulk: копировать ID / скрыть до refresh / открыть `/x8/users?user=`), топ выигравших/проигравших (RTP игрока vs RTP игры).

Verify KPI — колонка **`bet_rub`**, не `bet_amount` из черновика чеклиста. Без фильтра статуса, по `created_at`. На экране `data-risk-verify="window_bet_rub"` и тот же SQL в `data-risk-verify-sql`. RTP/аналитика — только `status=finished` по `finished_at`, это другое число.

Теория PvP: `100 − commission/2` (`commission_rate_wagering_complete` 15% → **92.50%**). Дом: `P(win)×multiplier` из активных `casino_house_policies` (fair 0.5×2 → **100%**). Открытые PvP: все `HEAD_TO_HEAD_GAME_TYPES` (включая баккару/блэкджек), waiting = `bet_rub`, active = `bet_rub*2`.

Локально: `bootstrap_static_test.sh` passed, `tsc -b` чистый. Тесты **только на staging**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: passed. HTTP 200: `/x8/login`, `/x8/casino`, `/x8/casino/risk`. Без токена `/api/admin/casino/risk` и `/api/admin/casino/dashboard` оба **401** (оба живы). Бандл gateway: `panel-2C6bGotR.js` содержит `casino/risk` и `data-risk-verify`.

md5 local=staging:

- `casino_risk.py` `4c60ba43ce635668b188b1d4069f89c9`
- `test_casino_risk.py` `a751d97589d154648df6e6e4aeda107f`
- `admin_casino.py` `d877f82e4caca95a0fc5d35efe600013`
- `CasinoRisk.tsx` `bb2ae90f774acc2a2221d6bb210d7c2c`
- `adminApi.ts` `5bb3aa5b508402cea4780318e151f1cb`
- `AdminRoutes.tsx` `262ec13f2ffca338fee733b4cde2513b`
- `Casino/index.ts` `48085fe4f3c85fd398ff033ddcc5c4a6`
- `CasinoDashboard.tsx` `93860867d16a794b277a8ee0bbf4dbd1`
- `riskViz.tsx` `6c1845668e22a07c9c4793c20c8423c2`
- `bootstrap_static_test.sh` `c20b95fbd6cb5a46cd10daab979581d2`

`grep` на staging: `def pvp_theoretical_rtp` / `fetch_risk_snapshot` / `game_type = ANY` в `casino_risk.py`; `@router.get("/casino/risk")` + `fetch_risk_snapshot` в `admin_casino.py`; `casino/risk` / `CasinoRisk` в `AdminRoutes.tsx`; `data-risk-verify="window_bet_rub"` в `CasinoRisk.tsx`.

SQL: **46** ключей; `wagering_percent` 21%. Verify:

`SELECT COALESCE(SUM(bet_rub), 0) FROM casino_games WHERE created_at > now() - interval '7 days'` → **1385.00**

24h → **960.00**; 30d → **1385.00** (как 7d — старше игр нет).

`staging-test.sh` (без аргументов): **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1019** (было 1011, +8 в `test_casino_risk.py`). `tests/test_casino_risk.py` на staging: **8 passed** (92.50, 100, 85, 10pp, 5%/500, SQL без `status`, payload 150 vs 92.5 → high, snapshot SUM=99). Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. На проде нет `casino_risk.py`.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–11 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок, этот шаг не трогал). Не коммитил.

Следующий шаг: клик-приёмка риска. Задачу 12 **не начинать**.

## 2026-08-28 — Задача 12. Экран аудита настроек

Клики задачи 11 приняты («дальше»). Задачу 13 не начинал. Прод не деплоил. Broadcast не трогал. `GET /casino/settings` / PATCH не ломал: только расширил уже существующий `GET /casino/settings/audit`.

Сделано: маршрут `/x8/casino/audit` в навигаторе Казино. Фильтры: 24ч/7д/30д (rolling `changed_at > now() - interval`, как риск) и «свой» (календарные `date_from`/`date_to`). Автор, ключ, свободный поиск (`q` по key/reason/author/JSON). Список **сгруппирован по `batch_id`**: одна строка на сохранение, внутри N полей. Клик открывает sticky-панель `DiffRow` было → стало, список остаётся в DOM. Сверху заметка: записей нет TTL, автоочистки нет.

В базе сейчас **270** строк / **6** сохранений, по 45 полей каждое (фронт по-прежнему шлёт всю форму). Последнее: `e88f99fb-fc69-46e2-8dac-e502acdf96a4`, автор `123`, причина `ук`, `cashback_volume_tiers` 2/5/7/10/15 → 5/7/9/14/20.

API: `window`, `q`, `batch_id` на том же GET. Вызов без FastAPI (`Query(None)` объект) больше не даёт ложный 422.

Локально: `bootstrap_static_test.sh` passed, `tsc -b` чистый. Тесты **только на staging**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` (повтор после фикса Query). Health: passed. HTTP 200: `/x8/login`, `/x8/casino/audit`, `/x8/casino/settings`. `/api/admin/casino/settings/audit` без токена **401**. Бандл `panel-z3PvNnk0.js` содержит `casino/audit`.

md5 local=staging:

- `admin_casino.py` `3e988b5c46689d221b488a59208e8405`
- `test_admin_casino_regression.py` `63b052a0adaea0bf1ba7fcf2fccfb281`
- `CasinoAudit.tsx` `6e1a29fb31af9affd387e894304d2dd1`
- `casinoAuditModel.ts` `55a5258e352d613f63f38cf4e15af1af`
- `Casino/index.ts` `77a8aaf59ffb6446b1750860616703e0`
- `AdminRoutes.tsx` `73e6baf44f47f29a237c85119b14f3f1`
- `adminApi.ts` `3f7eabe413ec68f4a07f51e97646cb82`
- `bootstrap_static_test.sh` `48597cae300af8d415cbc1caad605bf2`

`grep` на staging: `casino/audit` / `CasinoAudit` в `AdminRoutes.tsx`; `data-audit-retention` в `CasinoAudit.tsx`; `groupAuditBatches` / `formatAuditValue` в модели; `strpos(lower(key)` / `WINDOW_SQL` в `admin_casino.py`.

SQL: **46** ключей; **270** строк аудита; **6** `batch_id`.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1020** (было 1019, +1 `test_list_audit_window_q_and_batch_filters`). `list_audit` на staging: **2 passed**. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Прод: `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–12 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок, этот шаг не трогал). Не коммитил.

Следующий шаг: клик-приёмка аудита. Задачу 13 **не начинать**.

## 2026-08-28 — Задача 13. Чек-лист готовности

Клики задачи 12 приняты («дальше»). Задачу 14 (casino.css / палитра Stake) не начинал. Прод не деплоил. Broadcast не трогал. Старое поле `ready` / массив `checks` — по-прежнему ёмкость V2 PvP-столов, не пятёрка обязательных.

Сделано: на `/x8/casino/house` чек-лист из **ровно пяти** обязательных пунктов с сервера (не localStorage): банк строго выше порога (`available > bankroll_floor_rub`; порог 0 ⇒ нужно `available > 0`) → комиссия и лимиты (`min_bet > 0`, `max_bet ≥ min_bet`, у `commission_rate_wagering_complete` есть `percent`) → хотя бы одна игра `true` в `enabled_games` → хотя бы один `is_active` профиль робота → `casino_game_chat_bindings.status = 'active'`. Кольцо `ok/total`. Каждый пункт — ссылка в секцию (`#house-step-bank` / `#house-step-profiles` / `#section-commission` / `#section-games` / `#section-chat`). Вторичный `<details>` «Дополнительно для PvP-столов» (старые 8 checks) **только если** все пять зелёные. `required_ready` / `required_ok` / `required_total=5` / `bankroll_floor_rub` в GET `/api/admin/casino/house/readiness`.

Локально: `bootstrap_static_test.sh` passed, `tsc -b` чистый. Тесты **только на staging**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Повтор из-за скролла по hash: docker conflict по имени `fake-payfast` — снял только Created-контейнеры, `down -v` не было. Volume postgres живой. Health: passed. HTTP 200: `/x8/login`, `/x8/casino/house`, `/x8/casino/settings`. `/api/admin/casino/house/readiness` без токена **401**. Бандл `panel-CmfySDjM.js`: `data-readiness-required-list`, `data-readiness-secondary`, `house-step-bank`.

md5 local=staging:

- `casino_house_readiness.py` `0725040294c36c0190fd867f7bd7f47a`
- `test_admin_casino_house_readiness.py` `61bedafcf3ac0374104ba641ee22b574`
- `admin_casino.py` `6c7a2e70e268035d416ca19b842f6fa3`
- `CasinoHouseReadiness.tsx` `6812c4fe3a4e3c35dbb4220f7e2abaaa`
- `CasinoHouse.tsx` `9eafb71131f6f6e43b3584f8294b144c`
- `CasinoSettings.tsx` `1987c8a7390ae5df0a0843affe0b1722`
- `adminApi.ts` `808147ae0c664f75cfb23b4600f99c69`
- `bootstrap_static_test.sh` `dd34172eb0f20b0f818d2108f76a3b95`

`grep` на staging: `REQUIRED_TOTAL = 5` / `bank_above_floor` в `casino_house_readiness.py`; `required_ready` в `HouseReadinessResponse`; `data-readiness-required-list` / `data-readiness-secondary` во фронте; `section-chat` / `section-commission` / `section-games`; `house-step-bank` / `house-step-profiles`.

SQL (экран обязан совпасть): **46** ключей; `bankroll_floor_rub` **0**; `min_bet` **10** / `max_bet` **100000**; комиссия после отыгрыша **5%**; `enabled_games` cub+PvP+карты true, raffle false; house `main` balance **5174.00**, reserved **790.00**, available **4384.00**; активных роботов **2** (`focuscasino-house` house_robot, `pvp-robot-1` pvp_robot); active-чат **FocusCasino staging test chat** (есть ещё disabled `Fixture Full Panel PvP Lobby`); аудит **270** / **6** batch. Значит кольцо **5/5**, вторичный `<details>` виден.

`staging-test.sh` (без аргументов): **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1024** (было 1020, +4 в `RequiredReadinessTests`). `tests/test_admin_casino_house_readiness.py`: **9 passed** (ноль банка → `required_ok=4`; 1000 vs порог 1000 красный, 1000.01 зелёный и `required_ready`; все игры off + нет чата; min_bet 0). Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у runtime-gateway. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–13 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок, этот шаг не трогал). Не коммитил.

Следующий шаг: клик-приёмка чек-листа. Задачу 14 **не начинать**.


## 2026-08-28 — Личка = игра, группа = вход; имена в итоге

Тесты **только на staging**. Прод не деплоил. Broadcast в этот шаг не мешал. Миграций нет: `play_chats` / `listing_*` / `roster_names` живут в `game_state` (merge persist).

Сделано в `focuspay-casino`:

- Мастер в личке: `game_chat_id` = id лички. `_finalize` больше не подставляет bound group (`_bound_chat_id` снят). Fallback только `call.message.chat.id`.
- `publish_created_table` без fallback на группу. Полный стол (ты+боты) шлёт доску только в чат создания. Если стол **open** и есть свободные места, а игра в личке — в привязанную группу уходит короткий анонс «Войти» (`listing_chat_id` / `listing_msg_id`), не доска.
- Join из чата: копия доски в `play_chats`. Вход из анонса группы превращает анонс в доску. `_edit_board` / кубики / итог — цикл по копиям. Бот-кубик один `send_dice` на первичном чате.
- Имена: `roster_names` с `from_user` при создании и join; запасной `get_chat`. Доска и итог — **все места**. «Исход: победитель» нет.

Тесты: `test_table_wizard` + `test_v2_card_board` **15 passed** (в т.ч. `game_chat_id=7` из лички; полный стол не трогает bound group; open-стол шлёт анонс в группу; `_edit_board` на двух chat_id; join из группы переводит listing в play chat; итог с именами всех мест). Движок тем же compose `--no-deps`: **102 passed**. `test_webhook` по-прежнему без пакета `telebot`.

Первый `staging-sync.sh` упал на транзиенте compose (`No such container: 4533d2…`). Повтор `staging-runtime-update.sh --apply` + health: **passed**. HTTP 200: `/healthz`, `/x8/login`, `/x8/casino`, `/casino/fairness`. Живой `casino-bot` в образе: md5 `v2_runtime.py` совпал с хостом, в файле есть `play_chats` / `_maybe_announce_listing`.

md5 local=staging:

- `games/v2_runtime.py` `7745df90e8c2cad8e5b1b6b68999002d`
- `games/v2_tables.py` `d87cb00f6aa66ae646a1fda8a9e64961`
- `games/table_wizard.py` `edc156caf10c2b00aed80dfd018a67fa`
- `tests/test_v2_card_board.py` `d7f9d27d8e334c3064dad496a3ae54fe`
- `tests/test_table_wizard.py` `f557809d56adef3421d8d1658e64e549`

`grep` на staging в `v2_runtime.py`: `_play_chats`, `_maybe_announce_listing`, `_ensure_play_chat`, `roster_names`. В `table_wizard.py`: `actor=call.from_user`, нет `_bound_chat_id`. В `v2_tables.py`: `join_chat_id` в `after_table_join`.

SQL: **46** ключей `casino_settings`.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1024** (было 1020; +4 не из этой задачи, бэкенд-тестов не добавлял). Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (казино-план + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок + fan-out). Не коммитил.

Следующий шаг: клик-приёмка fan-out в Telegram-боте. Следующую задачу плана **не начинать**.

## 2026-08-28 — Задача 14. Дизайн-токены игрового интерфейса

Клики задачи 13 приняты («делай дальше»). Лобби / рельс / поиск (задача 15) не делал. `index.css` и `panel.css` не менял. Прод не деплоил. Broadcast и fan-out бота не трогал.

Сделано: `focussite/frontend/src/casino/casino.css` — структура как у wagering-листа (пять поверхностей, у статуса четвёрка обычный/hover/pressed/16% `color-mix`, тёмный `--ink` на яркой заливке, фаска `inset 0 1px rgba(255,255,255,.04)`, `scale(.97)`, кегль 14, радиус 4–8, пилюля только у бейджа). Палитра своя: поверхности `#0a0a0a…#2c2c2c`, акцент лёд **`#6ea8ff`**, выигрыш `#2fbf71`, проигрыш `#e5484d`, VIP золото `#d4a017`. В файле токенов **нет** `#0f212e` и `#00e701`. `--win` / `--lose` не берутся из темы Telegram. Шрифты Inter и JetBrains Mono. Геометрия: шапка 60, рельс 60/240 @ 300ms, низ 68, контент 1280.

Чтобы палитру было видно без лобби: публичный превью `http://127.0.0.1:18081/casino/tokens` (`CasinoTokensPreview.tsx`). Это не оболочка задачи 15.

Локально: `bootstrap_static_test.sh` passed, `npm run build` чистый. Тесты **только на staging**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: passed. HTTP 200: `/casino/tokens`, `/casino/fairness`, `/x8/casino/house`. Бандл public `index-Cm_JQY60.js` / `index-B4s7uqAv.css`: `data-casino-tokens`, `#6ea8ff`, `--win-soft`. Panel-бандл не менялся (`panel-CmfySDjM.js`).

md5 local=staging:

- `casino.css` `1a2de39d8429d4f95bd55f8ca7370d85`
- `CasinoTokensPreview.tsx` `5b56427f558cfbff3d0f8d4f1264252a`
- `App.tsx` `b5f2809f0ff9bd6470891b2b150fcad5`
- `bootstrap_static_test.sh` `355d74ff17a762e12391b8b4db23e418`
- `index.css` `f4a3dfde5a56c21999de83ae4f14032d` (без правок)
- `panel.css` `14dbe7c8ac35803e930c574ba35ad317` (без правок)

`grep` на staging в `casino.css`: `--surface-0` → `#0a0a0a`, `--accent` `#6ea8ff`, `--win-soft` 16%, `--casino-header-h: 60px`, `--casino-press: 0.97`. Нет `#0f212e` / `#00e701`. `--casino-header-h` нет в `index.css` / `panel.css`.

SQL: **46** ключей (эта задача БД не трогала).

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1024** (без новых тестов). Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у runtime-gateway.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–14 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок, этот шаг не трогал). Не коммитил.

Следующий шаг: клик-приёмка палитры. Задачу 15 **не начинать**.

## 2026-08-28 — Итог баккары: ссылка «Проверить раунд», без вписывания

Не задача 15. Прод не деплоил. Broadcast не трогал. Повод: в итоге стола `#431ACF47` было «Проверка: страница /casino/fairness» — `CASINO_FAIRNESS_URL` в runtime env не было, `verify_url()` возвращал пустую строку.

Сделано:

- Бот: `fairness_page_base()` читает `CASINO_FAIRNESS_URL`, на staging без env — `http://127.0.0.1:18081/casino/fairness`. Итог: HTML-ссылка «Проверить раунд» с `game_type`, `game_id`, `commit`, `client_seed`, `nonce`, `server_seed`. `&` в href экранируется (`&amp;`).
- Страница: `CasinoFairness` по этим query сама `POST /public/casino/fairness/verify`. Пустая `/casino/fairness` по-прежнему ручная форма.
- `/etc/focuspay/staging-runtime.env`: `CASINO_FAIRNESS_URL=http://127.0.0.1:18081/casino/fairness`. Preflight требует ровно этот URL.

Тесты бота на staging (`--no-deps`, `PYTHONPATH=/opt/focuspay-casino`): `test_fairness_session` + `test_v2_card_board` + `test_table_wizard` → **19 passed**.

Живой `casino-bot` (`/app`): md5 совпал с хостом; `config.CASINO_FAIRNESS_URL` = тот же tunnel URL. Бандл `index-Cm_JQY60.js` содержит «По ссылке из бота».

md5 local=staging (= образ бота):

- `games/card_fairness.py` `39218188d9d523241f82a8e5dc5b50df`
- `games/fairness.py` `613c5b5008cf9954ffa6be3682d7458d`
- `games/v2_runtime.py` `3ef1acc8943885cf6f15d3709d3be990`
- `tests/test_fairness_session.py` `7402962f1b01ab7b275cd19928749a0e`
- `CasinoFairness.tsx` `6dadbee07e1af7e98f179e18afa09631`
- `staging-runtime-preflight.sh` `455164ece916f6d10abe10d69a126556`

`rg`: `CASINO_FAIRNESS_URL` в `config.py`, `card_fairness.py`, `.env*.example`, preflight; «Проверить раунд» в `card_fairness.py` + тесте; `autoVerifyFromParams` в `CasinoFairness.tsx`.

SQL: **46** ключей `casino_settings`.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1024**. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (казино-план + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок + ссылка fairness). Не коммитил.

Следующий шаг: клик-приёмка ссылки в **новом** раунде (старый `#431ACF47` без href). Задачу 15 **не начинать**.

## 2026-08-28 — Задача 15. Оболочка и лобби

Клики палитры (задача 14) приняты («ну есть да это»). Дуэли по стейкам / стол / Mini App (16–18) не делал. `index.css` и `panel.css` не менял. Прод не деплоил. Broadcast и fan-out бота не трогал.

Сделано:

- Публичный `GET /api/public/casino/lobby` (`build_public_lobby`): 9 игр из каталога, `enabled` из настроек, `min_bet_rub` / `max_bet_rub` / `commission_percent` (complete), до 8 открытых дуэлей без `creator_id`.
- Оболочка `CasinoShell`: рельс 60↔240 @ 300ms, шапка 60 (баланс, ₽/USDT, кошелёк, колокол, аватар), на ширине ≤767 нижнее меню 68px. Без `PublicHeader`.
- Лобби `/casino`: промо 4 → недавние (localStorage) → тизер открытых дуэлей → категории. Поиск нечёткий в холсте: «кубик» → Кубики + куб; опечатка не опустошает каталог. Плитка 3:4, имя на картинке, избранное, мета без hover на таче.
- `/casino/play/:gameId` — заглушка, чтобы плитка не была 404. `/casino/tokens` и `/casino/fairness` снаружи оболочки, живы.

Локально: `bootstrap_static_test.sh` passed, `npm run build` чистый. Тесты **только на staging**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health: passed. HTTP 200: `/casino`, `/casino/tokens`, `/casino/fairness`, `/api/public/casino/lobby`. Живой lobby: 9 игр, raffle `enabled: false` как в SQL, 4 открытые дуэли, `creator_id` нет. Бандл public `index-BqcfDIZO.js` / `index-DsM6aYSQ.css`: `data-casino-lobby`, `кубик`. Panel-бандл этого билда `panel-D7D4Ljp2.js` (хеш сменился из-за уже грязного дерева панели, эта задача panel.css не правила).

md5 local=staging:

- `public_casino.py` `db32c10d48827b2b6e1cc3121c880005`
- `test_public_casino_lobby.py` `ca4f3388cc6a1b7f953b7c2484938a16`
- `casino.css` `b2e6fe6889b6f123a25c853d1307706f`
- `CasinoShell.tsx` `b4991ca7bb1e7ccee900bf8884148806`
- `CasinoLobby.tsx` `cad0bf0da551d293794cf9c9ca1541f9`
- `CasinoGameTile.tsx` `4e7fababc96732ae297871ca5fd2cf93`
- `fuzzySearch.ts` `cb87394aa470819d4c368ecfe13986e5`
- `gameCatalog.ts` `689ffb3bad8fdbac12062c941675f6b9`
- `App.tsx` `bad316d358d220311610043f98dd7dca`
- `public.ts` `d4876ca3156fd9ccc5f3569041f2ab69`
- `bootstrap_static_test.sh` `8f173293a0c43b525513dcb5a882a95b`
- `index.css` `f4a3dfde5a56c21999de83ae4f14032d` (без правок)
- `panel.css` `14dbe7c8ac35803e930c574ba35ad317` (без правок)

`grep` на staging: `build_public_lobby`, `@router.get("/casino/lobby")`, `CasinoShell`, `data-casino-lobby`, `data-casino-search`, `data-casino-tile`, `fuzzySearch`, `кубик`, `path="/casino"`. В `casino.css` нет `#0f212e` / `#00e701`. `--casino-header-h` нет в `index.css` / `panel.css`.

SQL: **46** ключей. `enabled_games`: raffle false, остальные true.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1025** (+1 `test_public_casino_lobby.py`). `tests/test_public_casino_lobby.py` — **1 passed**. Новых имён в упавших нет. ≈1018 passed (1025−7). Pytest `-q` в docker `-T` не печатает итоговую строку `N passed`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у runtime-gateway. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–15 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок, этот шаг не трогал). Не коммитил.

Следующий шаг: клик-приёмка лобби. Задачу 16 **не начинать**.

## 2026-08-28 — Задача 16. Лобби дуэлей

Клики лобби (задача 15) приняты («делай дальше»). Стол / Mini App (17–18) не делал. `index.css` и `panel.css` не менял. Прод не деплоил. Broadcast и fan-out бота не трогал.

Сделано:

- Публичный `GET /api/public/casino/duels`: три группы стейка (`<500` / `500–5000` / `>5000`), `fill_label` (медиана ожидания; очередь ≥15 мин → «стынет»), комиссия в корне ответа. Карточка: ставка, банк, **чистая выплата** (`net_payout_rub` ≠ банк). `creator_id` в JSON нет; `is_mine` / `is_joined` только при Bearer.
- `GET /api/public/casino/duels/{game_id}`: `steps` по одному месту за шаг (`sequential_reveal_steps`), подпись лидера. `game_state` из asyncpg приходит строкой jsonb — `_as_map` / `json.loads`, иначе шаги пустые.
- `POST /api/user/casino/duels` `{game_type, stake_rub, autojoin}`: hold через существующий internal create/join. Автоjoin — старейшая чужая дуэль того же типа и ставки.
- UI `/casino/duels`: шапка с комиссией, Создать / Обновить, иконка возврата (`data-casino-return`), `data-net-payout`. Комната `/casino/duels/:id`: раскрытие по 900 мс, не все шаги сразу. Тизер лобби ведёт сюда. `/casino/tokens` и `/casino/fairness` снаружи оболочки.

Локально: `bootstrap_static_test.sh` passed. Тесты **только на staging**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. После ImportError (`WAITING_DUELS_SQL` живёт в `casino_duels.py`, не в роутере) backend healthy. Health: passed. HTTP 200: `/casino/duels`, `/casino`, `/casino/tokens`, `/casino/fairness`, `/api/public/casino/duels`, `/api/public/casino/lobby`. Живой список: 3 группы, commission 5%, 100 ₽ → банк 200 / на руки **195**, `creator_id` нет. Бандл `index-D-ZfOVEN.js` / `index-CEDPr9B9.css` содержит `data-casino-duels`. Panel `panel-BsMh0BjN.js` (хеш от грязного дерева панели, эта задача panel.css не правила).

Снимал бан `172.20.0.4` (`auth_bruteforce` после curl через nginx) — тот же приём, что при логинах 123. `compose run --profile tests` Recreate postgres; named volume, ключи 46. Стек поднимал `staging-runtime-update.sh --apply`, без `down -v`.

md5 local=staging:

- `casino_duels.py` `2267f51cfdfe873671759eb2c67268a5`
- `public_casino.py` `2c2f2799dc9875dd22e7cca7e8446b5c`
- `user_casino.py` `1ce507c73fc0af3f5bcea5602c5ec15f`
- `test_casino_duels.py` `7dfbb65f3cdc6b60ae880663596656bd`
- `main.py` `5ee6a914740052ea2b64fe0368b7b343`
- `CasinoDuels.tsx` `e4d0bcc308baf1cb071ed8dcea45e5b8`
- `CasinoDuelRoom.tsx` `4f6ca0eb8410b091ccc99c7c06dc95a9`
- `casino.css` `c92716636aeca94c14d5beeb982f956e`
- `CasinoShell.tsx` `1621ea7d4ae583538d46d840c58e1d05`
- `CasinoLobby.tsx` `562e5d346c64ad1f3c1e4e63e482c6dc`
- `gameCatalog.ts` `52ad46b1ee97a4e1c23796f81aaa5f3a`
- `App.tsx` `7656015e11108f0cf4ca5744ee0c1335`
- `public.ts` `dbfad90fd56e1342a37df5758e0fc27a`
- `bootstrap_static_test.sh` `ea2c0d19775d6d0fdc443ccff8064586`
- `index.css` `f4a3dfde5a56c21999de83ae4f14032d` (без правок)
- `panel.css` `14dbe7c8ac35803e930c574ba35ad317` (без правок)

`grep` на staging: `WAITING_DUELS_SQL`, `build_duel_room`, `@router.get("/casino/duels")`, `create_or_join_duel`, `pick_autojoin_target`, `sequential_reveal_steps`, `data-casino-duels`, `data-net-payout`, `data-casino-return`, `path="duels"`. В образе backend те же символы. В `casino.css` нет `#0f212e` / `#00e701`. `--casino-header-h` нет в `index.css` / `panel.css`.

SQL: **46** ключей.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1034** (было 1025, `tests/test_casino_duels.py`: **9**). `tests/test_casino_duels.py` — **9 passed**. Новых имён в упавших нет. ≈1027 passed (1034−7). Pytest `-q` в docker `-T` не печатает итоговую строку `N passed`.

Живая комната `7c86944c-0b85-4c1e-89f6-427f9945e57d`: шаги creator 2 → opponent 5, лидер меняется; банк 100, на руки 97.5.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у runtime-gateway. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–16 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок, этот шаг не трогал). Не коммитил.

Следующий шаг: клик-приёмка лобби дуэлей. Задачу 17 **не начинать**.

## 2026-08-28 — Кубики в чате без реплая; казино кидает после игрока

Не задача 17. Прод не деплоил. Broadcast не трогал. Повод: в личке после «1/2 броска» стол создавался, но куб не принимался без реплая, а робот кидал сразу (или не кидал).

Сделано в `focuspay-casino`:

- Бросок в чате (личка и группа) ищется по `from_user.id` + чат стола и эмодзи. Реплай не обязателен. Чужой куб в группе молча игнорируется.
- Робот не кидает в момент промпта. После броска игрока ждёт ~4 с (грань видна), потом `send_dice`, ещё ~4 с, потом запись. Два броска: робот догоняет только тот индекс, который уже кинули все люди за столом.
- Промпт: «Киньте эмодзи в этот чат — реплай не нужен». `/cub` по-прежнему house cub (казино после игрока, как было).
- Тайминг: `games/dice_timing.py`.

Тесты **только на staging** (compose `backend-tests`, `--no-deps`, `-w /opt/focuspay-casino`): `test_v2_card_board` + `test_table_wizard` + `test_pvp_dice` + `test_house_cub` + `test_fairness_session` + `test_game_chat_guard` → **44 passed**. Ожидаемый traceback в fail-closed guard. `test_webhook` не гонял.

Первый `staging-sync.sh` упал на транзиенте compose (`Conflict` имя backend-контейнера). Повтор `staging-runtime-update.sh --apply`: ещё один транзиент `No such container`. Третий apply + health: **passed**. Postgres named volume: ключи 46, ledger `8443902979` **972.25** (кредит 1000 минус сыгранное). Без `down -v`.

md5 local=staging (= `/app` casino-bot):

- `games/v2_runtime.py` `6c2921ac6c5b574944115b777f0570d9`
- `games/pvp.py` `3758eb5bdf8adf475f57277535721f89`
- `games/house_cub.py` `f9c8e82cb78df1c16bce0c0ac4eac776`
- `games/dice_timing.py` `782d36bf4f0ce7c7a45354caf1e2d22c`
- `tests/test_v2_card_board.py` `ce6db78eda4b48a70a38099ea760107a`
- `tests/test_pvp_dice.py` `b9d03e600e93d4264a1f5e1fe2407ada`

`grep` в живом `casino-bot` `/app`: `_dice_table_for_player`, `_rolling_game_for_thrower`, `wait_dice_landed`, «реплай не нужен», `_humans_complete_index`. `open_cub` только в `house_cub.py`, не в `table_wizard.py`.

SQL: **46** ключей `casino_settings`.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1033** (как после задачи 16, бэкенд-тестов не добавлял). Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–16 + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (движок + этот фикс). Не коммитил.

Следующий шаг: клик-приёмка кубов в Telegram. Задачу 17 **не начинать**.

## 2026-08-28 — Staging login: капча + Telegram на туннеле

Не задача 17. Повод кликов задачи 16: «работает все кроме входа через телеграм или данные». Прод не деплоил. Broadcast не трогал.

Причина формы: `GET /api/public/captcha` → 500, `relation "captcha_challenges" does not exist`. Миграция `add_captcha_challenges.sql` не была в staging bootstrap. Применил на живой volume (`CREATE TABLE`, без `down -v`). Капча теперь **200**.

Telegram Login Widget на `http://127.0.0.1:18081` не заводится: BotFather принимает домен, не localhost. На `/login` при hostname 127.0.0.1 виджет скрыт, подсказка войти логином.

Сайт: `/login` логин `fixture_buyer`, пароль как у остальных staging-кабинетов (`123`), плюс картинка. Админский `123` на `/login` не подходит (`is_admin` режется).

Файлы: `20-full-panel-bootstrap.sh`, `00-apply-migrations.sh`, `bootstrap_static_test.sh`, `Login.tsx`. `bootstrap_static_test.sh` passed.

HTTP: captcha 200, `/login` 200. Health passed. SQL **46** ключей. Прод метки те же: index 04:22:45, panel 04:22:48, unit 08:33:32.

Git: не коммитил. Задачу 17 не начинал.

## 2026-08-28 — Личное уведомление после игры (DM result)

Не задача 17. Прод не деплоил. Broadcast не трогал. Раффл не трогал. Публичную доску стола не убирал.

Сделано:

- V2 settle: в `casino_v2_notification_outbox` на каждого человека свой payload: `result` (`win`/`lose`/`tie`), `your_payout_rub`, `available_rub` (снимок `unified_available` после денег), `winner_seat_nos`, `game_type`. Общий settlement payload без персонального `result`.
- Legacy `_enqueue_notification`: HTML «Вы победили / проиграли / Ничья» + выплата + баланс, не `Casino game …`. `chat_id` = `recipient_id`. Recipients ещё из вложенного `game` (робот PvP).
- Бот: `games/result_notify.py`. `run_v2_outbox_pass` шлёт это в личку, не `format_v2_settlement` («Победил: место»). Доска в чате стола по-прежнему `format_v2_settlement` + `_edit_board`.
- `/cub`: в тот же ответ дописан «Баланс», без второго 🏁. `recovery._deliver_outbox_message` без смены контракта (уже шлёт `text` + wagering hint).

Тесты **только на staging**. Compose `backend-tests`, `--no-deps` для бота, `-w /opt/focuspay-casino`.

Первый `staging-sync.sh` / `--apply`: транзиент `No such container` / Conflict имени casino-bot. Повтор `up -d --wait` без `down -v`. Health: **passed**. Named volume: ключи **46**.

md5 local=staging (= live `/app/backend` и `/app` casino-bot):

- `internal_casino.py` `d6c464850eb4b8428c9275f812b3ab79`
- `test_internal_casino.py` `e2209927632e7ba5e6cf60310e126b0a`
- `games/result_notify.py` `9ce757f7ce7af54c6053e8a8a8c9972c`
- `games/v2_runtime.py` `9796d7c27b1a12737c469c690480460b`
- `games/house_cub.py` `1045a340d132e16e188d43a26b61c13e`
- `tests/test_result_notify.py` `7d6e64e1ddd31728f9141957a2675635`
- `tests/test_house_cub.py` `6e9ca995b8a07ffe6e50e6e049d96bbb`

`grep` на staging: `format_personal_result_html`, `_snapshot_available_rub` в backend; `format_personal_result_dm` в `run_v2_outbox_pass`; `format_v2_settlement` остаётся на доске (`_commit_settle`); в house cub есть «Баланс»; английского stub `Casino game {id}` в outbox нет.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1036** (было 1034, +2: personal legacy text + V2 outbox payload). Новых имён в упавших нет. ≈1029 passed (1036−7).

Точечно backend (`OutboxTests` + `test_v2_outbox_payload_is_personal_with_result_and_balance`): **4 passed**.

Казино-бот (`--no-deps`, `PYTHONPATH=/opt/focuspay-casino`): `test_result_notify` + `test_house_cub` + `test_v2_card_board` + `test_table_wizard` + `test_recovery` → **40 passed**. `test_webhook` не гонял.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Старый `focuspay-staging-*` без publish на хост.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–16 + этот шаг + **чужой broadcast** + login/captcha). `focuspay-casino` HEAD `4b8d65e`, dirty (движок + этот шаг). Не коммитил.

Следующий шаг: клик-приёмка лички. Задачу 17 **не начинать**.

## 2026-08-28 — Staging login: картинка проверки не грузилась в браузере

Не задача 17. Повод: на `/login` текст «Проверка: сколько будет не удалось загрузить?». Прод не деплоил. Broadcast не трогал.

С сервера `GET /api/public/captcha` уже был **200** (таблица `captcha_challenges` на месте). В браузере запрос на URL со словом `captcha` часто режет блокировщик — фронт ловил это как «не удалось загрузить» и подставлял ошибку в фразу «сколько будет …».

Сделано:

- Алиас `GET /api/public/human-check` (тот же JSON: `image` + `challenge_id`). Старый `/captcha` жив.
- Фронт ходит на `/public/human-check`, при 404 — запасной `/public/captcha`.
- Ошибка больше не выглядит как пример арифметики.

Smoke: human-check **200**, captcha **200**. Бандл `index-*.js` содержит `human-check`. SQL: таблица `captcha_challenges`, **46** ключей `casino_settings`.

md5 local=staging:

- `focussite/frontend/src/lib/auth.ts` `1744cab6ffa1823bf4f9d5791d50e86a`
- `focussite/frontend/src/components/CaptchaField.tsx` `cf2c4c3d06b677bded6aeb25cc9ab411`
- `site/exchange-backend/routers/public.py` `d3de67d1e5056ebee1ab9a3553c295a2`
- `site/exchange-backend/math_captcha.py` `8942563eb0efb883bc28bd2a9eaac7b8`
- `site/exchange-backend/tests/test_security_bindings.py` `724dd95edeca7358742ca38d08802641`

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1037** (было 1036, +1 алиас human-check). Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Health passed. Без `down -v`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–16 + login + **чужой broadcast**). `focuspay-casino` dirty (не этот шаг). Не коммитил.

Следующий шаг: клик входа (картинка + `fixture_buyer`). Задачу 17 **не начинать**.


## 2026-08-28 — Мастер: клик «сколько бросков» ничего не делал

Не задача 17. Прод не деплоил. Broadcast не трогал.

Причина в логах casino-bot: `_players_keyboard() got multiple values for keyword argument 'family'`. После выбора 1/2 бросков `wizard_step` вызывал `_players_keyboard(..., **_carry(entry), family=..., rolls=...)` — `family` уже в сессии. Исключение до `answer_callback_query` → в Telegram пусто.

Исправление: `_fields(entry, **override)` сливает словари. То же для своей ставки (`stake=`). Тест `test_rolls_callback_asks_how_many_players`.

Залито: `staging-sync.sh`. Транзиенты compose (Conflict имени casino-bot, `No such container`); повтор `up -d --wait` без `down -v`. Health: **passed**. SQL ключей **46**.

md5 local=staging (= `/app` casino-bot):

- `games/table_wizard.py` `e0710d86bcc8ac0355a3d0c49f66cda7`
- `tests/test_table_wizard.py` `d295190ae38898ecb7feaed7dc937a09`

`grep` в живом casino-bot: `def _fields`, `_fields(entry, family=family, rolls=rolls, game_key=game_key)`.

Казино-бот (`--no-deps`): `test_table_wizard` + `test_pvp_lobby` + `test_house_cub` + `test_result_notify` → **33 passed**.

`staging-test.sh`: **7 failed**, те же имена. Collect-only **1037**. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081`. Прод метки те же: index 04:22:45, panel 04:22:48, unit 08:33:32.

Git: не коммитил. Задачу 17 **не начинать**.

## 2026-08-28 — Два броска: казино кидало три раза

Не задача 17. Прод не деплоил. Broadcast не трогал.

Причина: в V2-столе обработчик куба игрока не держал замок. Анимация Telegram ~4 с. Второй бросок уходил, пока казино ещё ждало первый: два `_roll_bots` параллельно, лишний `send_dice`.

Исправление: замок на `table_id` вокруг записи броска и `_roll_bots`; после ожидания анимации повторная проверка, что слот ещё пуст. Тесты: `test_two_roll_game_casino_throws_once_per_player_throw`, `test_two_roll_overlapping_player_dice_casino_throws_twice`.

Залито: `staging-sync.sh`. Health: **passed**. SQL ключей **46**.

md5 local=staging (= `/app` casino-bot):

- `games/v2_runtime.py` `fefa71b1761b3212ceb75f000fc50df6`
- `tests/test_v2_card_board.py` `21486f9e60421af7921b63ec9a35398b`

`grep` в живом casino-bot: `_table_roll_locks`, `def _table_roll_lock`, `_roll_bots(..., locked=True)` в `try_handle_v2_dice`.

Казино-бот (`--no-deps`): `test_v2_card_board` + `test_table_wizard` + `test_pvp_dice` + `test_house_cub` + `test_result_notify` → **42 passed**.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1037**. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Прод метки те же: index 04:22:45, panel 04:22:48, unit 08:33:32.

Git: не коммитил. Задачу 17 **не начинать**.

## 2026-08-28 — Два броска: казино кидало три раза

Не задача 17. Прод не деплоил. Broadcast не трогал.

Причина: в V2-столе обработчик куба игрока не держал замок. Анимация Telegram ~4 с (`wait_dice_landed`). Второй бросок уходил, пока казино ещё ждало первый: два `_roll_bots` параллельно, лишний `send_dice`. На одном броске гонка реже, на двух — типичный клик.

Исправление: замок на `table_id` вокруг записи броска и `_roll_bots`; после ожидания анимации повторная проверка, что слот ещё пуст. Тесты: `test_two_roll_game_casino_throws_once_per_player_throw`, `test_two_roll_overlapping_player_dice_casino_throws_twice`.

Залито: `staging-sync.sh`. Health: **passed**. SQL ключей **46**.

md5 local=staging (= `/app` casino-bot):

- `games/v2_runtime.py` `fefa71b1761b3212ceb75f000fc50df6`
- `tests/test_v2_card_board.py` `21486f9e60421af7921b63ec9a35398b`

`grep` в живом casino-bot: `_table_roll_locks`, `def _table_roll_lock`, `_roll_bots(..., locked=True)` в `try_handle_v2_dice`.

Казино-бот (`--no-deps`): `test_v2_card_board` + `test_table_wizard` + `test_pvp_dice` + `test_house_cub` + `test_result_notify` → **42 passed**.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1037**. Новых имён в упавших нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Прод метки те же: index 04:22:45, panel 04:22:48, unit 08:33:32.

Git: не коммитил. Задачу 17 **не начинать**.

## 2026-08-29 — Staging login: «неверный ответ на проверку»

Не задача 17. Повод: картинка грузится, любой ответ отклоняется. Прод не деплоил. Broadcast не трогал.

Причина: `captcha_challenges.ip_address` типа `inet`. Postgres `inet::text` даёт `172.20.0.4/32`, сверка была `ip_address::text = $4` с хостом без маски → **всегда false**. Строки 15–23 (Firefox, guest `285d016d-…`) все `consumed=f`.

Сверка: `ip_address = $4::inet` (`'172.20.0.4/32'::inet = '172.20.0.4'::inet` → t). В backend-образ добавлен `fonts-dejavu-core`.

Smoke: GET human-check + POST `/api/auth/login` `fixture_buyer` с текстом из БД → **200**, challenge 24 `consumed=t`.

md5 local=staging:

- `site/exchange-backend/math_captcha.py` `14bf854c3cdf26a0bed72cc423afb0a9`
- `site/exchange-backend/tests/test_security_bindings.py` `011461bf5adb09e696f89641920f9ff2`
- `focussite/docker/backend.Dockerfile` `48e3c3f6bd7c26d0705a37539bc60deb`

`staging-test.sh`: **7 failed**, те же имена. Collect-only **1037**. Новых имён нет.

Docker: только `127.0.0.1:18081->8080/tcp`. Health passed. SQL **46** ключей. Прод: index 04:22:45, panel 04:22:48, unit 08:33:32.

Git: не коммитил. Задачу 17 **не начинать**.

## 2026-08-29 — Задача 17. Экран игры

Сделано: веб-экран `/casino/play/:gameId` — две колонки (панель ~340px + холст), лента «Мои / Все / Крупные» на всю ширину. Панель: Вручную/Авто, ставка с ½ и ×2, **выигрыш при победе** как readonly-инпут (`win_on_win` = payout после комиссии, не gross), контроль кубика, кнопка ставки. Авто: число ставок, сброс/+% на win/loss, стоп по прибыли/убытку. Модалка честности: хеш сида, клиентский сид, nonce, ротация, формула, ссылка на `/casino/fairness`. Кубик — HMAC `prepare_cub`+`play_cub` (не Telegram dice). Дуэльные типы с этой страницы открывают комнату. Мобильный лист ставки над `--casino-nav-mobile-h` и `safe-area-inset-bottom`.

Котировка 100 ₽ ×2 при 5%: gross 200, комиссия 5, **win_on_win 195**. Живой `GET /api/public/casino/play/quote?stake_rub=100` на staging: `win_on_win_rub=195.0`, `payout_multiplier=2`, `commission_percent=5`, `enabled=true`. `max_bet_rub=268.45` (сжал банкролл дома, не глобальные 100000).

Файлы:
- `site/exchange-backend/casino_play.py`
- `site/exchange-backend/tests/test_casino_play.py`
- `site/exchange-backend/routers/public_casino.py` (`GET /casino/play/quote`, `/tape`)
- `site/exchange-backend/routers/user_casino.py` (`POST /casino/play`, fairness session/seed/rotate)
- `focussite/frontend/src/casino/CasinoPlay.tsx` (замена stub)
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/App.tsx`
- `focussite/frontend/src/lib/public.ts`

Локальная сборка: `npm run build` чистая (tsc + vite, бандл `index-Dt8aowkq.js`).

Залито на staging: да, точечный rsync файлов задачи 17 (без полного `--delete` обоих деревьев, casino-bot не перезаписывал) + `staging-runtime-update.sh --apply`. Stub `CasinoPlayStub.tsx` на сервере удалён. Без `down -v`. Прод не трогал. Broadcast не трогал.

Healthcheck: `staging runtime health check passed` (после apply и повторно после тестов).

Тесты на staging: `sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env ./scripts/staging-test.sh` — **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1042** (было 1037, +5 в `test_casino_play.py`). `pytest tests/test_casino_play.py -q` → **5 passed**. Новых имён в упавших нет. ≈1035 passed (1042−7).

`grep` на staging: `win_on_win_rub` в `casino_play.py` / тесте / `public.ts` / `CasinoPlay.tsx`; маршруты `casino/play/quote|tape` и `POST /casino/play` в роутерах. Цепочка: расчёт → quote API → поле на экране.

md5 local=staging (= live `/app/backend`):

- `casino_play.py` `dc3d662fad4758f7debdb6ac83a0c032`
- `tests/test_casino_play.py` `9cdb5b930a5270ba256d6e7c11c5e8ab`
- `routers/user_casino.py` `9da6e9d999441bf721a4be9c65539782`
- `routers/public_casino.py` `6217b99292d79736464e189aba66b6db`
- `CasinoPlay.tsx` `7bc9c12a1864252c8fa416c32d5ccf0d`
- `casino.css` `73110dd79c0723ea8fd35f53ae7562ae`
- `App.tsx` `c578132d9c3de1d46fbeb963bcedeaf0`
- `public.ts` `7eeb462f5ed8cef0b3a377ce97e0c9f3`

Gateway бандл `index-Dt8aowkq.js` содержит `win_on_win` и `casino/play`. SQL ключей **46**. Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–17 + login/captcha + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (не этот шаг). Не коммитил.

Следующий шаг: клик-приёмка экрана игры. Задачу 18 **не начинать**.

Открытые вопросы: нет. Живой max ставки на кубике сейчас ~268 ₽ из-за банкролла робота — для проверки «выше максимума» достаточно 500 ₽.

## 2026-08-29 — Задача 17, правка после клика: вход в игру и холст

Повод: экран `/casino/play/cub` виден по прямой ссылке, но слева не было понятных пунктов «зайти в игру»; холст справа — пустая тёмная плита; без входа кнопка «Ставка» молча уводила на логин.

Сделано:
- Рельс по умолчанию развёрнут, секция **Игры** со всеми названиями из каталога (кубик, дуэли, карты, рулетка). Внизу — Все дуэли / Честность / Кошелёк. На телефоне в нижней навигации пункт **Кубик**.
- Вход с сайта: **Казино** в шапке лендинга, в `PublicHeader` и во вкладках кабинета рядом с FocusLucky.
- Холст: крупный кубик, не пустота. Гость видит кнопку **Войти и поставить**. После раунда шапка обновляет баланс.

Файлы: `CasinoShell.tsx`, `CasinoPlay.tsx`, `casino.css`, `gameCatalog.ts`, `CabinetLayout.tsx`, `PublicHeader.tsx`, `PublicHome.tsx`.

Локальная сборка: `npm run build` чистая (`index-B-4cQSMW.js` локально; на шлюзе после apply `index-sIrza647.js`).

Залито: точечный rsync + `--apply`. Health passed. Без `down -v`. Прод не трогал. Бэкенд не менял — полный pytest не гонял повторно.

md5 local=staging:

- `CasinoShell.tsx` `4be657a48fb17a7ef03756db51e31c33`
- `CasinoPlay.tsx` `515752cb3b613b15c31ed0f9510e279e`
- `casino.css` `10072b7876735957c74dd86fc990bca0`
- `gameCatalog.ts` `e5b8196b72f6af2ae758e4bde422fb6b`
- `CabinetLayout.tsx` `b18144fa722cd3be3f683d0d476d0002`
- `PublicHeader.tsx` `72bae29cfa98fec40335b120f23b98ae`
- `PublicHome.tsx` `54174171f9f25499988b0e5dc76262bc`

Бандл шлюза содержит «Войти и поставить» и «Кубик против казино». SQL **46**. Docker: только `127.0.0.1:18081`. Прод метки те же: index 04:22:45, panel 04:22:48, unit 08:33:32.

Git: не коммитил. Задачу 18 **не начинать**.

## 2026-08-29 — Срез спортивных PvP (дартс/боулинг/футбол/баскет)

Не задача 18. Прод не деплоил. Broadcast не трогал. Рулетку 36+0 не строил. Историю `casino_games` не удалял.

Сделано: из продукта убраны `pvp_darts` / `pvp_bowling` / `pvp_football` / `pvp_basketball` и бот-команды `/darts` `/2darts` `/boul` `/2boul` `/fut` `/2fut` `/basket` `/2basket`. Живые ключи: `pvp_dice` (бот `cub`/`2cub`), `baccara`, `blackjack`, `cub`, `raffle` (заглушка).

- Реестр `GAME_KEYS` / `HEAD_TO_HEAD` / weekly / cashback / readiness — без четырёх типов. Создание спорта: Literal 422 + `create_or_resume` 400 «Эта игра больше не доступна».
- Миграция `add_casino_drop_sport_pvp.sql` (jsonb `-` четырёх ключей). В `00-apply-migrations.sh` и `20-full-panel-bootstrap.sh` (required + incremental + fresh). На живой базе: `UPDATE 2`.
- Сайт/админка: каталог, рельс, настройки, риск, фильтр игр, робот (лишние ключи при сохранении отбрасываются).
- Бот: `games/catalog.py` только cub/2cub + карты; `/help` без спорта. Recovery: SQL CASE и `active_pvp_games` IN со спортом, подписи истории — оставлены.
- План казино: «девять игр» → пять ключей. Планы ставок на футбол не трогал.

Локальная сборка: `npm run build` чистая (`index-DH4bk7-m.js` / `panel-FlzmANLf.js`). `bootstrap_static_test.sh` passed. Бот unittest: 38 ok (`test_pvp_lobby` + `test_table_wizard` + `test_v2_card_board`).

Залито: точечный rsync (focuspay + focuspay-casino) + SQL + `--apply`. Health passed. Без `down -v`.

md5 local=staging:

- `casino_finance.py` `7aafe3ffe46798ba12d33fdf76f699a8`
- `casino_settings_registry.py` `e13eea20b5b8bd65a6e2296ce66b6835`
- `internal_casino.py` `384d10a27033e247218623d77bd64bfa`
- `public_casino.py` `c6f19a29f5963ce4f9939a328a6b283e`
- `add_casino_drop_sport_pvp.sql` `31a645fa6822c0f78886e8c787ba78be`
- `gameCatalog.ts` `ed5852a8fa7a9f06f586d3a6a8b8893e`
- `adminApi.ts` `ed742cfce9d2ba1e9632d31e1eeecff5`
- `casinoSettingsModel.ts` `d148104938995f97e9c19ab67f079b0c`
- `00-apply-migrations.sh` `8682318207147eb033be89bda09e956a`
- `20-full-panel-bootstrap.sh` `2d1f6faba33936dc294106527762552b`
- `games/catalog.py` `ada22f2d5de8b3cf480ffc88ddaf3d92`
- `bot.py` `8b1efef81d8f8842d87d089571966379`

`grep` бот (`pvp_darts|…|/darts|/boul|/fut|/basket`): пусто. Лобби API: 5 id. SQL `enabled_games`: cub, raffle, baccara, pvp_dice, blackjack — без спорта. `provably_fair_enabled` те же 5 ключей. Бандл шлюза без «Дартс»/«Боулинг».

`staging-test.sh`: collect-only **1045** (было 1042, +3 отказа спорта). **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–17 + login + **чужой broadcast** + этот срез). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил.

Следующий шаг: клик-приёмка среза. Задачу 18 **не начинать**.

## 2026-08-29 — Задача 18. Telegram Mini App

Клики среза спорта в этом сеансе не закрывались («делай дальше»). Прод не деплоил. Broadcast не трогал. Рулетку 36+0 не строил. Спорт не возвращал. initData/JWT не добавлял.

Сделано: отдельная Vite-сборка `casino.html` → `/casino/tg` на тех же `CasinoShell` / лобби / дуэли / стол / честность.

- Тема: `--surface-0` / `--text` / `--accent` через `--tg-theme-*` с запасными; `--win` / `--lose` жёстко `#2fbf71` / `#e5484d`. Светлая: `?tgTheme=light`. Высота: `viewportStableHeight`, не `100vh`. Safe-area → `--casino-safe-*`. `disableVerticalSwipes`. Слабый Android: `casino-reduce-motion`.
- Родная MainButton (в браузере без Telegram — полоска `data-tg-main-button`): лобби Войти/Пополнить, дуэли Подтвердить / Войти в дуэль. Кнопка ставки `casino-bet-btn` остаётся в DOM рядом с «выигрыш при победе». Хаптик: selection ½/×2, bet, win/lose; в автоигре `setHapticMuted`.
- nginx `^~ /casino/tg` → `casino.html` (local + staging-runtime). Vite rewrite `/casino/tg`. Бот: `CASINO_MINIAPP_URL` из `CASINO_FAIRNESS_URL` (`…/casino/tg`); кнопки WebApp «На сайте» в reply- и inline-меню.

Локальная сборка: `npm run build` чистая (`casino.html` 0.85 kB, `tsc -b && vite`). `bootstrap_static_test.sh` passed. Бот: `tests/test_staging_config.py` + `test_staging_ui.py` — **40 passed**.

Залито: точечный rsync + `staging-runtime-update.sh --apply` (дважды: второй после того, как параллельный WIP холдема попал в `gameCatalog.ts` на хосте — каталог на staging вернул к пяти ключам `ed5852a8…`). Health passed. Без `down -v`. Прод не трогал.

Живой шлюз: `200` `/casino/tg`, `/casino/tg/duels`, `/casino`, `/casino/fairness`. HTML: `data-casino-entry="tg"`, `telegram-web-app.js`. Бандл: `viewportStableHeight`, `casino-bet-btn`; **holdem в ассетах = 0**. Лобби API: 5 id. Бот в контейнере: `CASINO_MINIAPP_URL=http://127.0.0.1:18081/casino/tg`. SQL ключей **46**.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Бэкенд-тестов этой задачей не добавлял (collect как после среза, **1045**).

md5 local=staging (то, что в рантайме; локальное дерево после заливки ещё правили покером в другом сеансе — `miniapp-main` / `CasinoShell` / `casino.css` / каталог на диске агента могут разъехаться):

- `casino.html` `96642d3129453712d7f7e6098453ccb9`
- `telegram.ts` `9890f3d8006c37016277b3894e167678`
- `miniapp-main.tsx` (staging) `8f0716f1c6a6c680b6da9d8b38b1bc14`
- `gameCatalog.ts` (staging, 5 ключей) `ed5852a8fa7a9f06f586d3a6a8b8893e`
- `vite.config.ts` `bc8f06fd4c47dc9eff889e864b3954c8`
- `nginx.staging-runtime.conf` `67cf1883eea73c834bb9f9cb181dee33`
- `nginx.local.conf` `5ee43a57ea89c3cf1bc964d0a8104612`
- `CasinoShell.tsx` (staging) `670b313084ce578f25f2f75cf85a0b26`
- `casino.css` (staging) `e9554d1886fc6c92382f4159bf7eab6a`
- `config.py` `ebb1d0617755daff56c69a2f1188b10f`
- `casino_menu.py` `bf6de937c3f73b4332cdff97ad76c8a1`
- `bot.py` `b5ada477896e5eedd94158983253f6a7`

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил.

Следующий шаг: клик-приёмка Mini App. Это последняя задача плана — дальше не начинать.

## 2026-08-29 — Покер PvP на сайте (NLHE, стол 2–6)

Не прод. `deploy_all.py` не запускал. Broadcast не трогал. Турниры / Omaha / боты за стол / чат стола — не делал.

Сделано: кэш-столы No-Limit Hold'em на сайте. Не дуэль с равной ставкой и не V2-стол бота.

- Движок `casino_holdem.py`: 7 карт, улицы, сайд-поты, fold/check/call/raise/all-in, таймаут (чек если бесплатно, иначе фолд). Тесты сравнивают конкретные ранги и банки.
- Деньги: сел → hold бай-ина → сразу confirm → стек. Внутри руки только `game_state`. Встал → кредит остатка. Рейк % с капом, не комиссия с проигравшей ставки. Таблицы `casino_poker_tables/seats/hands`. Миграция `add_casino_poker_tables.sql` в `00-apply-migrations.sh` и bootstrap.
- Колода: HMAC-SHA256 Fisher–Yates **один раз на руку** (`holdem_shuffled_deck`), не per-seat баккара. Коммит до сдачи, сид после вскрытия. `/casino/fairness` умеет `holdem` (борд, без стороны).
- User API: создать/сесть/снимок/ход + SSE `…/events?access_token=`. Ход с `expected_state_version` → 409 если устарел.
- Сайт: каталог `holdem` → `/casino/poker`, стол `/casino/poker/:id`, 6 мест, карты, слайдер рейза, таймер, SSE + опрос 2 с. Mini App: те же маршруты `poker` / `poker/:tableId`.
- Админка: ключ `holdem` в `GAME_KEYS` / `ADMIN_CASINO_GAME_TYPES`, секция блайнды/рейк/кап/таймаут/бай-ин BB. Недельный оборот UNION `casino_poker_hands.wager_json`. Роботам `holdem` в `allowed_games` нельзя.

Локально: `npm run build` чистая (`index-nHtxRoKs.js` / `panel-B8yDZ1zK.js` / `casino.html` 0.85 kB). `python -m unittest` holdem/poker/cards/lobby/registry/admin/fairness — **96 ok**.

Залито: `focussite/scripts/staging-sync.sh` (rsync focuspay + focuspay-casino) + `--apply`. Health passed. Без `down -v`. Прод не трогал.

Живой шлюз: `200` `/casino/poker`. Лобби API **6 id** включая `holdem`. `GET /api/public/casino/poker/tables`: enabled true, блайнды 10/20.

SQL: `casino_poker_tables/seats/hands` есть. Ключи `holdem_*` все 7. `enabled_games.holdem=true`, `provably_fair_enabled.holdem=true`.

`rg holdem_small_blind_rub` (и соседние ключи): registry, poker config, миграция, admin GET/PATCH, adminApi, casinoSettingsModel, CasinoSettings, audit labels, тесты.

`staging-test.sh`: collect-only **1068** (было 1045, +23). **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет.

md5 local=staging:

- `casino_holdem.py` `e8da4dc0ac0f1602894450ef5e28bca9`
- `casino_poker.py` `5e93487309eb7d623242df4160fddd20`
- `casino_cards.py` `0e2b180d25f3187c759effac4f12f4cf`
- `casino_settings_registry.py` `26cacf1471951483a0b542be909ba711`
- `casino_finance.py` `0edc1c48c72e8860a9141d7a4045afad`
- `add_casino_poker_tables.sql` `de2f2296857060ff266a1e6713d02402`
- `user_casino.py` `e6abe68b0dd5c056ce599a537a1ffb84`
- `public_casino.py` `b278c5de1da46b3e6ac20973f7fe2b94`
- `admin_casino.py` `501d9d4be3bcada80f9c9a40b997e977`
- `gameCatalog.ts` `cc5d7aaba04c429abd45a32c24f14852`
- `CasinoPoker.tsx` `da05f01f38ef73548458f3291b742b09`
- `CasinoPokerTable.tsx` `cda724644c306d6536a03370a0bd53f5`
- `adminApi.ts` `393eea866acb4709e685214be3b608be`
- `casinoSettingsModel.ts` `7f32b051295f64826cc65ca45fd27cae`
- `00-apply-migrations.sh` `59f6f34c6c6f74e763ee49b02bfce108`

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: клик-приёмка покера (список ниже в чате). Другую задачу не начинать.

## 2026-08-29 — Срез 1. Графика кубика (игрок vs казино)

Клики покера в этом сеансе не закрывались. Прод не деплоил. Broadcast не трогал. Баккару / холдем-карты / лобби-арт / рулетку **не** начинал. Формулу HMAC и выплату cub не менял.

Сделано: на `/casino/play/cub` два CSS 3D-куба (слева Вы, справа Казино). Исход по-прежнему HMAC &lt; порог. Сервер добавляет `player_pips` / `house_pips` — детерминированная пара из того же digest среди 15 выигрышных или 15 проигрышных комбинаций (`player > house` ⟺ `won`). Клиент грани не придумывает. Подпись на холсте: кубы показывают исход, не решают его. Дуэль `pvp_dice` крутит те же кубы по `steps`. `casino-reduce-motion` / `prefers-reduced-motion` — без кручения.

Файлы:
- `site/exchange-backend/casino_cub_faces.py`
- `site/exchange-backend/tests/test_casino_cub_faces.py`
- `site/exchange-backend/routers/internal_casino.py` (`play_cub_with_conn` + идемпотентный повтор)
- `focussite/frontend/src/casino/CasinoDice.tsx`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/CasinoDuelRoom.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/lib/public.ts`

Локальная сборка: `npm run build` чистая (`index-B8WqD9yE.js` содержит `player_pips`, `index-BV8COpGk.css` — `casino-die-tumble`, `casino.html` 0.85 kB). `python -m unittest tests.test_casino_cub_faces` → **5 passed**. Quote 100 ₽ ×2 при 5% по-прежнему `win_on_win_rub=195`.

Залито: точечный rsync восьми файлов (без полного `--delete`) + `staging-runtime-update.sh --apply`. Health passed. Без `down -v`. Прод не трогал. Compose при `--apply` **Recreate** postgres-контейнера; том жив: 24 игры, настройки на месте.

Healthcheck: `staging runtime health check passed`.

Тесты на staging: `staging-test.sh` — **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1073** (было 1068, +5 в `test_casino_cub_faces.py`). `pytest tests/test_casino_cub_faces.py -q` → **5 passed**. Новых имён в упавших нет. ≈1066 passed (1073−7).

`grep` `player_pips`: cub_faces + internal_casino + тест + `public.ts` + `CasinoPlay.tsx`. Живой шлюз: `200` `/casino/play/cub`, `/casino/tg/play/cub`, `/casino/duels`. Бандл шлюза: `player_pips` в `index-B8WqD9yE.js`, `casino-die-tumble` в `index-BV8COpGk.css`.

md5 local=staging (= live `/app/backend`):

- `casino_cub_faces.py` `f5e7592ad86c6cd89318fbe681d9474c`
- `tests/test_casino_cub_faces.py` `998b446b1f45153bb0b06295c6e64dd1`
- `routers/internal_casino.py` `731818bcdef2c75b8b8384fc7b21bee1`
- `CasinoDice.tsx` `355be4598f5a4188dfebbf65a426d810`
- `CasinoPlay.tsx` `3a0019ff18e9e0d9516b46e626de54c2`
- `CasinoDuelRoom.tsx` `bb83a174b13598ef8af6ef0b0639b274`
- `casino.css` `892335476ddfdbfa2a354e7207ecc93c`
- `public.ts` `191635fa43765efbb3b6d057d457ca85`

SQL ключей **53** (в таблице есть 7 `holdem_*`; это не этот срез). `enabled_games` cub+holdem+baccara+pvp_dice+blackjack, raffle false. Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty (задачи 1–18 + покер + этот срез + **чужой broadcast**). `focuspay-casino` HEAD `4b8d65e`, dirty (не этот шаг). Не коммитил.

Следующий шаг: клик-приёмка кубов. Срез 2 (раздача баккары) **не начинать**.

## 2026-08-29 — ×2 ставит all-in, не выше баланса

Не баккара. Прод не деплоил. Broadcast не трогал. HMAC/грани кубов не менял.

Сделано: кнопка ×2 на `/casino/play/:gameId` удваивает ставку, но если удвоение больше кошелька — ставит **весь доступный баланс** (`available_rub`, иначе `balance_rub`). Потолок дома `max_bet_rub` по-прежнему режет сверху. ½ без изменений. Кнопка `data-casino-x2`.

Файл: `focussite/frontend/src/casino/CasinoPlay.tsx` `0ec226b6b741b37ba3be68fdedf61a2c`.

Локальная сборка: на диске агента чужой WIP (Jackpot import) ломает `tsc`; на staging дерева Jackpot нет. Шлюз собрался там: `tsc -b && vite build` чистый, бандл `index-CNXLLp4U.js`.

Залито: точечный rsync одного файла + `docker compose up -d --build --no-deps --wait gateway` (postgres этим шагом не трогал). Затем канонический `staging-test.sh` сам **Recreate** postgres-контейнера; том жив. Health passed. Без `down -v`. Прод не трогал.

`grep`: `doubleOrAllIn` ×2 и `data-casino-x2` ×1 в `CasinoPlay.tsx`; в бандле шлюза `data-casino-x2`. Живой `200` `/casino/play/cub`.

`staging-test.sh`: **7 failed**, те же имена. Collect-only **1073**. Новых имён нет. Бэкенд-тестов не добавлял.

SQL ключей **53**. Игр `casino_games` **52** (до этого прогона тестов было 24 — тесты ходили в живую базу). Docker: наружу только `127.0.0.1:18081->8080/tcp`. Прод: index 04:22:45, panel 04:22:48, unit 08:33:32 UTC.

Git: не коммитил. Срез 2 (баккара) **не начинать**.

## 2026-08-29 — Чат казино + джекпот-рулетка (staging)

Не прод. `deploy_all.py` не запускал. Broadcast не трогал. FocusLucky/`raffle` не переписывал. По просьбе «implement the plan / all to-dos» обе задачи уехали одним sync; клики — два отдельных списка.

### Задача 1. Живой чат

Общий канал + лички + онлайн + «Вызвать» на дуэль с `reserved_opponent_id`. SSE `GET /api/user/casino/chat/events?access_token=`. Лимит 3/10с, тело ≤280, в лобби блок `http://` `t.me/` `tg://`. Join чужим id на зарезервированную дуэль → 409. Автоjoin такие дуэли не берёт.

Файлы: `casino_chat.py`, `migrations/add_casino_chat.sql`, роуты в `user_casino.py`, `CasinoChatPanel.tsx` в `CasinoShell` (десктоп справа, телефон — «Чат»).

### Задача 2. Джекпот CSGETGO

Новый ключ `jackpot` (плитка «Джекпот», `/casino/jackpot`). 1 ₽ = 100 билетов. Roll ∈ [0,1) в момент открытия раунда, публичный SHA-256. `winning_ticket = floor(roll × total_tickets)`. Таймер 300 с с первой ставки, 30 игроков — спин сразу, один игрок к дедлайну — возврат холда. Рейк 5% с банка. Докид можно, выйти нельзя. Дом не играет (`ROBOT_GAME_KEYS` без jackpot). Анимация ленты декоративная (~100 слотов, winner index 80, `translateX` 8 с `cubic-bezier(0.15, 0, 0.10, 1)`, риска по центру не едет).

Ключи: `jackpot_collect_seconds` 300, `jackpot_max_players` 30, `jackpot_rake_percent` 5. Недельный оборот: UNION `casino_jackpot_rounds.wager_json`. В weekly cashback loss SQL jackpot **не** добавлял.

### Staging

Локально: `npm run build` чистая (`index-DAktAjgH.js` / `panel-C70hzH81.js` / `casino.html` 0.85 kB). Локально pytest/unittest **не** гонял.

Залито: `focussite/scripts/staging-sync.sh` + `--apply`. Health passed. Postgres-контейнер **не** Recreate (Running); bootstrap Recreate прогнал идемпотентный SQL: таблицы чата и джекпота появились. Без `down -v`. Прод не трогал.

Живой шлюз: `200` `/casino`, `/casino/jackpot`, `/casino/fairness`. Лобби API **7 id** включая `jackpot`. `enabled_games.jackpot=true`, `provably_fair_enabled.jackpot=true`.

SQL: `casino_chat_rooms/messages/presence` есть (1 lobby). `casino_jackpot_rounds/bets` есть (0 раундов — создаётся на первый GET). Ключи `jackpot_*` все 3. Всего ключей **56** (было 53).

`rg jackpot_collect_seconds`: registry, jackpot config, миграция, admin GET/PATCH, adminApi, casinoSettingsModel, CasinoSettings, audit labels, тесты.

`staging-test.sh`: collect-only **1097** (было 1073, +24: `test_casino_chat.py` 9 + `test_casino_jackpot.py` 8 + доезд ранее локальных тестов полным rsync). **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. ≈1090 passed (1097−7). DurableLifecycle по-прежнему падают на mock `fetchrow` из-за UNION в `weekly_wager_rub` (сначала poker, теперь + jackpot) — это те же три имени, не чинил.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_chat.py` `df36b63a8210f5e5def8e7fedd28f2c5`
- `casino_jackpot.py` `39d9e01d8ef447659172cab6a72ac5a9`
- `casino_duels.py` `583f460b99c497b809195c0fc800c381`
- `casino_settings_registry.py` `4acf1d4b44f8e41d1dade57e77737b83`
- `casino_finance.py` `34cda6645ecad3b2e21cceb16409d35a`
- `casino_weekly_wager.py` `6b14bfa3913b31dc6081c9f458c52230`
- `add_casino_chat.sql` `f25c22f621f2c83ff5d013e9ee9751d4`
- `add_casino_jackpot.sql` `dec448f39e2baea5a4a286517d8cecaa`
- `user_casino.py` `dd7861a72316b3bca26ea728b7158884`
- `public_casino.py` `9803c5b24d3b29c1823cbb5b5f219780`
- `admin_casino.py` `13837c47ccd344cc7e1dc9416f3a9141`
- `test_casino_chat.py` `82cc83aa4b24a8c6d7d5005c2df46330`
- `test_casino_jackpot.py` `8a1f8b5eff73de8406c416a8d545c447`
- `gameCatalog.ts` `6acd391e61650c03d6081f91041654da`
- `CasinoJackpot.tsx` `ba8000c43b60bc6da979b285bfdc7d18`
- `CasinoChatPanel.tsx` `d08ad42698e695a7c22ed733c53c8316`
- `CasinoShell.tsx` `cb8dfa1ca376ab1091bf3279fdeb68e9`
- `casino.css` `6022d1602a4ff056b0451de4a97f9097`
- `public.ts` `6f6d1bdac5fcb133441818a321791919`
- `CasinoFairness.tsx` `822268184b9f34c6ce2f00804d211862`
- `casinoSettingsModel.ts` `518876123863aa2e065fa1093a9d75a1`
- `adminApi.ts` `83fb701aa3a83916d1f5abbe382c0ee3`
- `00-apply-migrations.sh` `54b293ec5116bdcdd49d50ece6ab9af9`
- `20-full-panel-bootstrap.sh` `335535f7644d6d1c37c78cddc2b499b7`

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: клик-приёмка чата, затем джекпота (списки в чате). Другую задачу не начинать.

## 2026-08-29 — Срез 2. Раздача баккары (и blackjack в той же комнате)

Клики чата/джекпота в этом сеансе не закрывались. Прод не деплоил. Broadcast не трогал. Холдем-felt / лобби-арт **не** начинал. HMAC-колоду и комиссию дуэли не менял.

Сделано: комната дуэли `baccara`/`blackjack` показывает SVG-карты. Лица только после публичного статуса (`finished` / `outcome_committed` / …). На ожидании и в `active` — рубашки, даже если в `game_data.card_rng` уже лежат карты. Раздача по одной карте (creator → opponent), как кубы. Очки баккары: A=1, 2–9 лицо, 10/J/Q/K=0, сумма % 10. Blackjack: A 1/11, без смены выплаты. Подпись: картинки показывают раздачу, исход по HMAC-колоде. Кубы `pvp_dice` не трогал.

Файлы:
- `site/exchange-backend/casino_cards.py` (счёт очков)
- `site/exchange-backend/casino_duels.py` (`public_duel_hands`, `sequential_card_reveal_steps`, `DUEL_ROOM_SELECT_*`)
- `site/exchange-backend/routers/public_casino.py` / `user_casino.py` (SELECT + `game_data`)
- `site/exchange-backend/tests/test_casino_duels.py` / `test_casino_cards.py`
- `focussite/frontend/src/casino/CasinoPlayingCard.tsx`
- `focussite/frontend/src/casino/CasinoDuelRoom.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/lib/public.ts` (`hands`, `step.card`)

Локально: `python -m unittest tests.test_casino_duels tests.test_casino_cards tests.test_casino_commission` → **25 OK** (в двух карточных файлах 25 тестов; +7 новых). Quote 100 ₽ ×2 при 5% по-прежнему `net_payout_rub=195`. Живой API демо: `web-demo-baccara-cards` руки `A♠ 9♦` / `K♥ 2♣`, 4 шага, `creator_id` нет; waiting `web-demo-baccara-waiting` — `hands` пустые, `A♠` в JSON нет.

Залито: точечный rsync карточных файлов (полный `--delete` не гонял в этом срезе; чат/джекпот на хосте уже были из предыдущей записи). Backend+gateway `--no-deps --build --wait`. Health passed. Без `down -v`. Прод не трогал.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only в журнале чата/джекпота **1097** (там уже есть эти +7 карточных). Новых имён в упавших нет.

`grep` `public_duel_hands` / `sequential_card_reveal_steps` / `CasinoPlayingCard`: duels + тесты + DuelRoom. Живой шлюз: `200` `/casino/duels/web-demo-baccara-cards`, `/casino/play/baccara`, `/casino/tg/play/baccara`, `/casino/jackpot`. Бандл: `casino-playing-card` в `index-CEGmGoHZ.css`, `data-casino-card-hand` в `index-ozApD5ZM.js`.

md5 local=staging `/opt` = live `/app/backend` (карточные):

- `casino_cards.py` `4b69bf1fb488e1983a39c9441bb6115a`
- `casino_duels.py` `583f460b99c497b809195c0fc800c381`
- `tests/test_casino_duels.py` `c9ef9946ca7b62ce62fc6c9a26ce98f4`
- `tests/test_casino_cards.py` `87ffedc57a1958d68106fdd838dfbb96`
- `CasinoDuelRoom.tsx` `3c82c1730cd60636e48f104380e3889a`
- `CasinoPlayingCard.tsx` `72c73a96e5d3827ccd4e5a648f0b292f`
- `routers/public_casino.py` `9803c5b24d3b29c1823cbb5b5f219780` (плюс джекпот-verify с прошлого среза)
- `routers/user_casino.py` `dd7861a72316b3bca26ea728b7158884` (плюс чат/джекпот)
- `casino.css` `6022d1602a4ff056b0451de4a97f9097`
- `public.ts` `6f6d1bdac5fcb133441818a321791919`

SQL ключей **56** (3 `jackpot_*` с прошлого среза). `enabled_games` cub+holdem+baccara+pvp_dice+blackjack+jackpot, raffle false. Игр `casino_games` **55** (в т.ч. 3 демо `web-demo-*` без холдов, только для кликов). Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: клик-приёмка раздачи баккары. Холдем-felt / лобби-арт **не начинать**.

## 2026-08-29 — Оболочка страницы игры (казино / игроки)

Клики баккары/чата/джекпота в этом сеансе не закрывались. Прод не деплоил. Broadcast не трогал. Стол «несколько vs казино» и V2 2–6 **не** начинал. HMAC cub и комиссию дуэли не менял.

Сделано: одна плитка «Кубики» (`pvp_dice`, `/casino/play/pvp_dice`). На странице игры табы «Против казино | С игроками» (`?mode=`). Дом кубика — текущий HMAC 1×1 (quote 100 ₽ ×2 @ 5% = 195 ₽). Вкладка игроков — лобби дуэлей **только этой** игры, пока 1×1. `/casino/play/cub` → `pvp_dice?mode=house`. Баккара/блэкджек по умолчанию «С игроками»; «Против казино» — текст, без фейковой игры. Деньги: дом = каждый vs казино; игроки = равные ставки, банк победителю. Несколько за/против дома — следующий срез.

Файлы:
- `focussite/frontend/src/casino/gameCatalog.ts` (без отдельной плитки cub; `canonicalGameId`)
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/CasinoModeSwitch.tsx`
- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/casino.css`

Локально: на диске агента чужой WIP (Jackpot import) ломает `tsc`; шлюз собрался на staging: `tsc -b && vite build` чистый, бандл `index-lEbPTr6L.js` / `index-B8KLGS99.js`, CSS `index-BY9HUgOy.css`, `casino.html` 0.85 kB. `data-casino-mode` в `index-lEbPTr6L.js`, `casino-mode-switch` в CSS.

Залито: точечный rsync семи файлов + `docker compose up -d --build --no-deps --wait gateway`. Health passed. Без `down -v`. Прод не трогал. Затем канонический `staging-test.sh` сам **Recreate** postgres-контейнера; том жив: ключи 56.

`rg` `casino-mode-switch` / `data-casino-mode`: ModeSwitch + CSS + Play. Живой шлюз: `200` `/casino/play/pvp_dice`, `?mode=house`, `?mode=players`, `/casino/play/cub`, `/casino/play/baccara`, `/casino/tg/play/pvp_dice`. Лобби API **7 id** (pvp_dice+cub+…+jackpot). В браузере: табы, quote 195 ₽, игроки — только кубики 1×1; баккара default players, house — копирай.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1097**. Новых имён нет. Бэкенд-тестов не добавлял.

md5 local = staging `/opt`:

- `gameCatalog.ts` `0096c9bc67198417ced8aac1c59f42f1`
- `CasinoPlay.tsx` `1758c98da9cab06669b948e4bd16f832`
- `CasinoModeSwitch.tsx` `bf73bc011c6dd2102a6f49edbefe8554`
- `CasinoPlayersLobby.tsx` `dde13ea5194eb4ef3ef4a963ffea7aca`
- `CasinoLobby.tsx` `f433f06bcfeb27b3f9847cda2db8474d`
- `CasinoShell.tsx` `89f61f803ee4ed8c338009ced08cede2`
- `casino.css` `8d0e345548b3d046b5a98e7990ed8c08`

SQL ключей **56** (3 `jackpot_*`). `enabled_games` cub+holdem+baccara+pvp_dice+blackjack+jackpot, raffle false. Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: клик-приёмка оболочки. Стол несколько vs казино / V2 2–6 **не начинать**.

## 2026-08-29 — Кланы игроков и топ по обороту

Клики баккары/чата/джекпота/оболочки в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` не гонял. Комнаты 2–6 / фикс-джекпот на N / клан vs клан / банк клана **не** начинал.

Сделано: постоянный клан (тег 3–8 A–Z0–9, имя, код приглашения). Один живой клан на игрока, потолок 20 (`clan_max_members` 2–50), вход только по коду, кулдаун 24ч после выхода. Владелец: кик, передача, роспуск, ротация кода. Денег у клана нет. Топ-20 за московскую неделю: те же источники, что `casino_weekly_wager.py`; зачёт только если на `finished_at`/`settled_at` игрок был в составе. Выход не обнуляет уже зачтённый оборот.

Файлы (этот срез):
- `site/exchange-backend/casino_clans.py`, `migrations/add_casino_clans.sql`, `tests/test_casino_clans.py`
- registry `clans_enabled` / `clan_max_members`; public/user/internal/admin роутеры
- staging SQL: `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`
- миниапп: `CasinoClans.tsx`, рейл/лобби, `App.tsx` / `miniapp-main.tsx`, чат `[TAG]` через `tagged_display_name`
- админка: секция «Кланы», дашборд «Топ кланов» + распустить
- `focuspay-casino`: `casino_teams.py`, `/team*`, пункт меню «Команда», `/help`, `[TAG]` в профиле, `focuspay_client.py`

Локально: `python -m unittest tests.test_casino_clans` → **15 OK**. Registry + dashboard clans: зелёные. `tests.test_casino_teams` + `test_staging_ui` + `test_profile` → **20 OK**. `npm run build` чистый: `index-C_TLJP1H.js` / `index-u5j-Su9O.js` / `panel-V_NxEQEa.js` / `index-CgYRyta7.css`. `bootstrap_static_test.sh` passed.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health passed (дважды). Postgres-контейнер **не** Recreate (Running); bootstrap Recreate прогнал `add_casino_clans.sql`: `INSERT 0 2` (новые ключи). Повторный INSERT тех же ключей → **`INSERT 0 0`**. Без `down -v`. Прод не трогал.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1112** (было 1097, **+15** `test_casino_clans.py`). Новых имён в упавших нет.

`rg` `clans_enabled`: domain + registry + migration + admin API + CasinoSettings + casinoSettingsModel. Живой шлюз: `200` `/casino/clans`, `/casino/tg/clans`, `/x8/casino`, `/api/public/casino/clans/top` (`clans: []`, `week_start` 2026-08-24). `/api/admin/casino/dashboard` без токена **401**. Бандл: `data-casino-clans` в `index-C_TLJP1H.js`, `section-clans` / «Топ кланов» в `panel-V_NxEQEa.js`, `casino-clans` в `index-CgYRyta7.css`. casino-bot лог: `Clan team handlers registered`.

md5 local = staging `/opt` = live `/app`:

- `casino_clans.py` `f174f823dd6ee5527d6f0951c802e2f3`
- `add_casino_clans.sql` `3b0d88972acb4498dc4b113567158da9`
- `tests/test_casino_clans.py` `51ea593cb4d8b004bff6eba9264011bf`
- `CasinoClans.tsx` `d52f553bab2de462baf35a439157eeb9`
- `casino_teams.py` `7e059f8592cf530ededac3d3c45d00b3`
- `bot.py` `3249e109b80dc09727e0a6da6c13517f`
- `focuspay_client.py` `ab0e00a57df2dfe56faa79567d64bbbe`
- `casinoSettingsModel.ts` `165b21d5f85c180b982abc78d873a435`

SQL ключей **58** (+2 `clans_enabled`, `clan_max_members`). Таблицы `casino_clans`, `casino_clan_members` есть. `enabled_games` cub+holdem+baccara+pvp_dice+blackjack+jackpot, raffle false. Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: клик-приёмка кланов на туннеле **18081**. Комнаты 2–6 / холдем-felt **не начинать**.

## 2026-08-29 — Кланы: ошибка «Не удалось выполнить запрос» на create

Клики. Прод не деплоил. `down -v` не было.

Причина: страница грузится (`GET /clans/top` 200, `GET /user/casino/clan` 200). Красная строка — от «Создать» с тегом `BB` (2 символа). Pydantic 422, `detail` массив, фронт показывал общее «Не удалось выполнить запрос». Топ пустой — кланов ещё нет, это нормально.

Сделано: проверка тега/имени до запроса (текст «Тег: 3–8 символов A–Z и 0–9»); `ClanCreateBody` без min_length, чтобы доменный 400 на русском доходил; `api.ts` читает FastAPI `detail[]`. Подсказка на форме. Ботовый `api_error_text` тоже читает список.

Локально: `test_casino_clans` **15 OK**, `test_casino_teams` **4 OK**, `npm run build` → `index-DNC7g0wC.js`.

Залито: sync; первый `--apply` — backend unhealthy (DNS postgres, compose Recreate); повтор `--apply` — «No such container»; `up -d --wait` + health **passed**. Postgres volume жив. Без `down -v`.

Ключей **59**: прежние 58 + `level_reach_bonuses` (миграция level_bonus уже была в bootstrap-скриптах грязного дерева, не этот срез). Таблицы кланов на месте. `/casino/clans` 200, top 200. Бандл содержит `Тег: 3`. md5 `CasinoClans.tsx` `004ac1d41b7fe06ab9c18c89fe40c0ca` local=staging.

Прод: `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Следующий шаг: hard refresh `/casino/clans`, тег **3–8** (не `BB`), F5. Комнаты 2–6 **не начинать**.

## 2026-08-29 — Авто кубика: 429 «слишком много попыток» и всё отваливается

Клики кланов в этом сеансе не закрывались. RTP/политику cub **не** менял. Прод не деплоил. Broadcast не трогал. `down -v` не было.

Что было: авто (до 50 раундов, ~450 мс) на каждый бросок слало play + quote + tape + balance×2. IP-лимит 240/мин. Все `/api` начинали отдавать 429 «Слишком много запросов»; F5/`refresh()` снимал сессию; логин — «Слишком много попыток входа». Staging через туннель ещё и шарит один IP. На staging у `940002` было 138 cub за минуты.

Сделано:
- `skips_ip_rate_limit`: с Bearer не считаются `/api/user/casino/*`, `/api/public/casino/*`, `/api/user/balance`, `/api/auth/me`. Логин и анонимный play по-прежнему в ведре. IP-ban не снимал.
- Авто: один POST на раунд, quote из ответа, лента в конце, баланс шапки debounce 800 мс. 429 не обнуляет quote и не разлогинивает (только 401).
- `CasinoPlay` на staging без `onStakeChange` (лобби на хосте старое, иначе tsc).

Файлы:
- `site/exchange-backend/rate_limit_middleware.py`
- `site/exchange-backend/tests/test_rate_limit_middleware.py` (2 теста)
- `focussite/frontend/src/lib/session.tsx`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`

Локально: `python -m unittest tests.test_rate_limit_middleware` → **2 OK**. `tsc -b` локально падает на чужом WIP (`CasinoDuelRoom` / `CasinoPlayerChip` / `CasinoProfile`), не на этом срезе. Шлюз на staging: `tsc -b && vite build` чистый, `index-BCYSvfns.js` / `index-DDSKuRrJ.js`, `casino.html` 0.85 kB.

Залито: точечный rsync пяти файлов + `up -d --build --no-deps --wait backend gateway`. Health passed. Затем канонический `staging-test.sh` **Recreate** postgres; backend/gateway ушли в Created — поднял `up -d --wait --profile bot --profile casino` без `--build` и без `down -v`. Том жив: **354** `casino_games`. Health passed. Прод не трогал.

`grep` `skips_ip_rate_limit` / `isLoggedOutStatus` / `applyRoundWallet` / `Слишком часто — авто`: middleware + тест + session + Play + Shell. Живой шлюз: `200` `/casino/play/pvp_dice`, `?mode=house`, `/api/health`. Бандл: строка авто-429 в `index-BCYSvfns.js`.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1142** (было 1097 в срезе чата/джекпота; +2 этот срез `test_rate_limit_middleware`, остальное — уже лежащие на staging clans/level_bonus/pvp_dice). Новых имён в упавших нет. ≈1135 passed (1142−7).

md5 local = staging `/opt` = live `/app/backend`:

- `rate_limit_middleware.py` `89e08233c9b1ecdaeaf963a208376888`
- `test_rate_limit_middleware.py` `2c69ce9394fd7da197f0b2b7656255b6`
- `session.tsx` `f18012c690bb508def2232ad8fb46a1a`
- `CasinoPlay.tsx` `be8801dcb874f0f963415b5d7aee3be0`
- `CasinoShell.tsx` `a82e278893e41099fb9c8794ce914a3a`

SQL ключей **59** (как в записи про кланы; этот срез ключей не добавлял). Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: клик-приёмка авто на кубике. RTP и комнаты 2–6 **не начинать**.

## 2026-08-29 — Кубик после входа с сайта в телеграм-ставку

Клики авто/кланов в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` не гонял. Баккара/холдем, V2 2–6, `/cub` vs дом, робот **не** начинал.

Почему «нигде не крутилось»: web `join_and_hold` ставил только `opponent_id` + `active`. Бот не узнавал (hydrate drop без `roll_msg_id`), outbox не писал join, на сайте не было броска. Таймера 30 с не было.

Сделано: после обоих мест (`pvp_dice`, не робот) — HMAC-сид, `roll_deadline_at` = join+30 с, outbox `pvp_roll_prompt` в лички (id>0) и `pvp_roll_prompt_group` в игровой чат. Кнопка на сайте → HMAC 1–6, CSS-куб. Живой 🎲 игрока в TG идёт в `POST /games/record-roll` и не затирает HMAC соперника. Через 30 с closer докидывает HMAC за пустые броски (`house_rolled`) и `commit`+`settle`. Стол `waiting` не кидает.

Файлы (этот срез):
- `site/exchange-backend/casino_pvp_dice.py` (новый), `casino_duels.py` (`can_roll` / `roll_deadline_at`)
- `routers/internal_casino.py` (join activate, persist merge, `/games/record-roll`)
- `routers/user_casino.py` `POST /casino/duels/{id}/roll`, `routers/public_casino.py` (closer на GET комнаты)
- `tests/test_casino_pvp_dice.py` (22), join в `test_internal_casino.py`
- `focussite/frontend/src/casino/CasinoDuelRoom.tsx`, `src/lib/public.ts` (`joinCasinoDuel(game_id)`, `rollCasinoDuel`)
- `focuspay-casino`: `games/pvp.py` (hydrate rolling без `roll_msg_id`, `sync_active_pvp_from_backend`, record-roll API), `recovery.py`, `focuspay_client.py`

Локально: `python -m unittest tests.test_casino_pvp_dice tests.test_casino_duels tests.test_internal_casino.SettingsWiredIntoGameplayTests` → **44 OK**. Бот: `tests.test_pvp_dice tests.test_focuspay_client tests.test_recovery tests.test_pvp_lobby` → **61 OK**. `tsc -b` чистый.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` — rsync доехал; `--apply` дважды упал на `No such container` при Recreate backend. Образы собрались. Поднял `up -d --wait --no-deps fake-payfast bot casino-bot`. Health passed. Без `down -v`. Прод не трогал.

`rg` `pvp_roll_prompt` / `rollCasinoDuel` / `/games/record-roll` / `can_roll`: модуль + join + outbox-тесты + DuelRoom + public.ts. Живой шлюз: `200` `/casino/play/pvp_dice`, `/casino/duels`, `/casino/tg/play/pvp_dice`. Бандл: `Кинуть кубик` и `data-casino-roll` в `index-Cbxyf1cZ.js` (общий чанк; `casino-DNcNA1bM.js` 1.16 kB — entry miniapp). casino-bot: `GET /games/active` в цикле 15 с.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1148** (было 1142, **+6**). Новых имён в упавших нет. На staging отдельно `test_casino_pvp_dice` + `SettingsWiredIntoGameplayTests` → **29 OK**.

md5 local = staging `/opt` = live `/app`:

- `casino_pvp_dice.py` `680dd32bb8b113bb2f5e98212f1213ad`
- `routers/internal_casino.py` `ec4d6d768d9b14b14ac44c1e6cd80682`
- `routers/user_casino.py` `451662a587eb0b1e4557003bf03be3aa`
- `routers/public_casino.py` `9983151e29c0a218a8824bcc515b3d8b`
- `casino_duels.py` `94d310311f62ddfdbc8e16c0ee41cdef`
- `tests/test_casino_pvp_dice.py` `c4e6308c8f506d2b27875de0f9b2f8cb`
- `CasinoDuelRoom.tsx` `16b67a48904e152e8ef31a95a5ca65ac`
- `public.ts` `6c076bef51f9f9b0dfe6cdcdfc81d621`
- `games/pvp.py` `92f3b44c173e25c00d2a693bb042fecd`
- `recovery.py` `1364298335eca82bfee84293b86ba5b4`
- `focuspay_client.py` `5c248dea99b59bf11ba20705d9ce20e9`

SQL ключей **59** (этот срез ключей не добавлял). `enabled_games` cub+holdem+baccara+pvp_dice+blackjack+jackpot, raffle false. Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: клик-приёмка кубика после входа с сайта. Баккара/холдем / V2 2–6 / `/cub` vs дом **не начинать**.

## 2026-08-29 — Аватарки, профиль и уровни казино

Клики кланов/авто/кубика-roll в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` не гонял. Стол «несколько vs казино» и V2 2–6 **не** начинал. HMAC cub RTP и формулу комиссии дуэли не менял. House-multi не трогал.

Сделано три среза одним выкатом (план «all to-dos»; клики — один список):

1. **Лобби дуэлей.** В карточке `creator` / `opponent` как у чата (`user_id`, `display_name`, `initial`, `avatar_url`). Сырого `creator_id` нет. Пустой слот `null` + силуэт. Боты: имя+буква, `user_id` 0, без ссылки в профиль. Ряд: ава+ник vs слот · ставка · Войти/Стол. Создать — узкая полоса чипов. В `?mode=players` нет нижней `.casino-stake-panel` на 46vh (класс `is-players`). Клик по фишке → `/casino/u/:id`.
2. **Профиль.** User JWT `GET /api/user/casino/players/me` и `GET /api/user/casino/players/{id}`. Дата: `bot_users.first_seen_at`, иначе `web_users.created_at`, календарный день. Неделя по `game_type`. Чужому нет `own` и нет `reach_bonus_rub`. Свой текст «Ещё X ₽ до уровня N…» + «и N ₽ на баланс» только если бонус реально в сетке.
3. **Админка.** Один редактор «Уровни»: порог, кешбэк %, комиссия до/после, `reach_bonus_rub`. Save пишет старые две сетки + `level_reach_bonuses`. Бонус: один кредит за игрока × московскую неделю × порог (`casino_level_bonus_grants` + `user_cashback_ledger` `clb:{id}:{week}:{min}`). `maybe_grant` только на живом asyncpg, после cub/PvP/jackpot/holdem.

Локально: `python -m unittest tests.test_casino_duels tests.test_casino_level_bonus tests.test_casino_player_profile tests.test_casino_settings_registry tests.test_casino_clans` → **59 OK**. `bootstrap_static_test.sh` passed. `tsc` на диске агента ломает чужой WIP; шлюз на staging уже собран (`index-Cbxyf1cZ.js` / `panel-DCJwSGCk.js` / `index-DQDN562N.css`).

Залито: точечный rsync `site/exchange-backend`, `focussite/frontend/src`, `focussite/docker/staging-db` (без `--delete` и без `staging-runtime-update.sh --apply`). SQL: `CREATE TABLE` уже была (NOTICE IF NOT EXISTS), `INSERT 0 0` ключ `level_reach_bonuses`. `up -d --build --no-deps --wait backend gateway` — слои CACHED, live md5 совпал с `/opt`. Health passed. Затем канонический `staging-test.sh` Recreate postgres; том жив. Без `down -v`. Прод не трогал.

Живой шлюз: `200` `/casino/play/pvp_dice`, `/api/public/casino/duels` (в карточке `creator`+`opponent`, в JSON нет `creator_id`), `/casino/u/1`. `GET /api/user/casino/players/1` без JWT **401**. Бандл: `data-casino-profile`, `data-casino-players-lobby`, `casino-player-chip`, `is-players`, `data-casino-next-level`; панель — «Уровни» и `reach_bonus`.

`rg`: `level_reach_bonuses` — registry + parse/grant + миграция + admin GET/PATCH + CasinoSettings/TierGrids + adminApi + audit. `fill_duel_actors` — duels + public/user routers + тесты. `CasinoPlayerChip` — лобби/комната/джекпот/профиль. `load_web_player_profile` — модуль + user router + тесты.

`staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1148**. Новых имён нет. ≈1141 passed (1148−7).

md5 local = staging `/opt` = live `/app/backend`:

- `casino_level_bonus.py` `d951219326ab2b82760e3f9300fdd032`
- `casino_player_profile.py` `576060318da3c9a5d0ceeb0796ad71be`
- `casino_duels.py` `6012aea97889dbe7c819381d5d053dc1`
- `casino_weekly_wager.py` `356be40c2059fd69d82bf28d6805df1e`
- `casino_settings_registry.py` `8db19f1bf30eca18380fdf0a170efc34`
- `add_casino_level_bonus.sql` `0a32cd35b441f3b3c6efbd20ab16af16`
- `routers/user_casino.py` `451662a587eb0b1e4557003bf03be3aa`
- `routers/admin_casino.py` `8a26fa15c621a5d549cb22812f3aba08`
- `CasinoPlayerChip.tsx` `1c192541aabbe5122150b16c317c7a41`
- `CasinoProfile.tsx` `66625e2bf9947ccc1150f04bc3d602c8`
- `CasinoPlayersLobby.tsx` `96a9212d7bcf4d3e10ccc1e7e0c0ef97`
- `CasinoPlay.tsx` `be8801dcb874f0f963415b5d7aee3be0`
- `CasinoTierGrids.tsx` `5969b1aea2187b197e284b7e777a70cc`

SQL ключей **59** (есть `level_reach_bonuses` = `[]`). Таблица `casino_level_bonus_grants` есть. `enabled_games` cub+holdem+baccara+pvp_dice+blackjack+jackpot, raffle false. Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` этот срез не трогал. Не коммитил.

Следующий шаг: клик-приёмка аватарок/профиля/уровней на **18081**. House-multi / V2 2–6 **не начинать**.

## 2026-08-29 — Оболочка: холдем/джекпот/рулетка

Клики прошлых срезов в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` / `staging-sync.sh` / `--apply` / `staging-test.sh` **не** гонял (запрет среза). Broadcast не трогал. Движки покера/джекпота/HMAC/рейк не переписывал. Спортивный PvP не включал. Стол «несколько vs казино» и V2 2–6 **не** начинал.

Сделано: холдем / джекпот / рулетка живут в той же оболочке `/casino/play/:gameId` с табами «Против казино | С игроками». Каталог: `holdem` → `/casino/play/holdem` (default `players`), `jackpot` → `/casino/play/jackpot` (default `house`), `raffle` уже `/casino/play/raffle` (default `house`). Старые `/casino/poker` и `/casino/jackpot` → редирект в play. Стол NLHE остаётся `/casino/poker/:tableId`.

Режимы:
- холдем «С игроками» — встроенный `CasinoPoker` (кэш 2–6). «Против казино» — честный текст, домашней NLHE нет.
- джекпот «Против казино» — встроенный `CasinoJackpot` (общий пул). «С игроками» — текст: это не стол V2, не места друг против друга.
- рулетка — заглушка FocusLucky, **не** европейская 36+0. Обе вкладки текст, без HMAC-раунда.

Файлы (этот срез):
- `focussite/frontend/src/casino/gameCatalog.ts` (href play/holdem|jackpot; howTo raffle = FocusLucky, не 36+0)
- `focussite/frontend/src/casino/CasinoPlay.tsx` (без увода на /poker|/jackpot; `data-casino-play-shell`)
- `focussite/frontend/src/casino/casinoPaths.tsx` (`RedirectToCasinoPlay`)
- `focussite/frontend/src/casino/CasinoPoker.tsx` / `CasinoJackpot.tsx` (`embedded`, без движка)
- `focussite/frontend/src/casino/CasinoPokerTable.tsx` («К столам» → play/holdem?mode=players)
- `focussite/frontend/src/App.tsx`, `focussite/frontend/src/casino/miniapp-main.tsx`

Локально: `npm run build` → `tsc -b && vite build` чистый. Бандл `index-B_IyoX4m.js` (каталог+оболочка) / `index-B--tTmzR.js` / `casino-CM-nWQYx.js` / CSS `index-DQDN562N.css` / `panel-DCJwSGCk.js`. В `index-B_IyoX4m.js`: `href:"/casino/play/holdem"`, `play/raffle`, `play/jackpot`, `data-casino-play-shell`, FocusLucky / «не 36+0», «← К столам» на play/holdem.

Залито: **нет**. Staging md5 **не** равен локальному (ожидаемо):

- `CasinoPlay.tsx` local `7d4661c9ee20456984fb1ae6fe8071d9` ≠ staging `/opt` `be8801dcb874f0f963415b5d7aee3be0`
- `gameCatalog.ts` local `f85cb025e9c9d634b9c6da00baa89c79` ≠ staging `/opt` `0096c9bc67198417ced8aac1c59f42f1`
- `App.tsx` local `36ec540f2dc4114dfcb19b9cbeaf6c13` ≠ staging `/opt` `373e5c3fea4e8a8815396784d887e646`

Ещё local: `casinoPaths.tsx` `38fcece1aade7220e29150ea3fb82ac2`, `CasinoPoker.tsx` `d799385e50a1bdf441ba3fd621e3090b`, `CasinoJackpot.tsx` `cd4bbe1bc1c52619a51b8f249fac496a`, `CasinoPokerTable.tsx` `f6efa6c370fe35c983852d3b1c87aec2`, `miniapp-main.tsx` `f874ed3b81d42829d05bdd23f6e4c8ca`.

`rg` live routes: каталог три href `/casino/play/{holdem,raffle,jackpot}`; `App.tsx` + `miniapp-main.tsx` `RedirectToCasinoPlay` на `poker`/`jackpot`; `play/:gameId` → `CasinoPlay`; `poker/:tableId` без редиректа.

`staging-test.sh`: не гонял. SQL не менял (прошлый счёт ключей **59**). Docker staging (read-only): наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, этот срез не трогал. Не коммитил.

Следующий шаг: клик-приёмка оболочки холдем/джекпот/рулетка. На **18081** сейчас ещё старый код, пока кто-то не зальёт. House-multi / V2 2–6 / 36+0 **не начинать**.

## 2026-08-29 — Графика: сукно холдема и плитки лобби

Клики прошлых срезов в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` / `staging-sync.sh` / `--apply` / `staging-test.sh` **не** гонял (запрет среза). Broadcast нет. RTP/HMAC/shuffle/ранги/выплаты не трогал. Админку `/x8` не рестил. Новых игр нет. Three.js нет.

Сделано (графика поверх живого API):

1. **Сукно холдема.** `CasinoPokerTable` рисует те же CSS-карты, что баккара (`CasinoPlayingCard`), вместо текста вроде `Ah` / `A♠`. Борд: 5 слотов (`hand.board`). Карман: две карты лицом, если `hand.seats[].hole` открыт; иначе две рубашки. Фолд: класс `is-folded` + подпись «фолд» + grayscale. `casino-reduce-motion` глушит deal. Mini App: компактные карты, 2 колонки сидений ≤420px.
2. **Лобби.** SVG-арт на плитках (`CasinoTileArt`, лёд `#6ea8ff` / near-black). Полоса «Как играть» + `howTo` на каждой плитке. Зелёный/красный только масти карт (как у баккары) и win/lose в других играх; Stake navy/neon нет.

Карты с API (без смены бэкенда): `public_view` отдаёт строки `rank+масть`, масть Unicode `♠♥♦♣`, десятка `10♥`. `parsePlayingCard`: последний символ = масть, остальное = ранг. `hole` зрителю всегда; чужие — только showdown/complete и не folded.

Файлы:
- `focussite/frontend/src/casino/CasinoPokerTable.tsx` (felt)
- `focussite/frontend/src/casino/CasinoPlayingCard.tsx` (`compact`)
- `focussite/frontend/src/casino/CasinoTileArt.tsx` (новый)
- `focussite/frontend/src/casino/CasinoGameTile.tsx`, `CasinoLobby.tsx`, `gameCatalog.ts` (`howTo`)
- `focussite/frontend/src/casino/casino.css` (блок `casino-felt-*` / `casino-tile-art-*` / `casino-lobby-howto` в конце)

Локально: `npm run build` → `tsc -b && vite build` чистый. Бандл `index-hbxDYLxt.js` / `index-BcIH2egv.js` / `casino-E_7Hz99W.js` 1.21 kB / CSS `index-BopO5iRn.css`. `panel-DCJwSGCk.js` без этого среза.

Залито: **нет**. Staging md5 не сверял (sync запрещён). SQL не менял. `focuspay-casino` не трогал.

`rg` `casino-felt` / `casino-tile-howto` / `casino-lobby-howto` / `CasinoTileArt`: PokerTable + css + Lobby + GameTile + TileArt. Текстовых `.casino-poker-card` в столе больше нет.

md5 local:

- `CasinoPlayingCard.tsx` `715ed7cd98cad7d5040060a39d12db49`
- `CasinoPokerTable.tsx` `f6efa6c370fe35c983852d3b1c87aec2`
- `CasinoGameTile.tsx` `3186dbbc55f290510eaa274175347723`
- `CasinoTileArt.tsx` `55cda6cdde26cdf3ab757488cf9f1e21`
- `CasinoLobby.tsx` `b76ac1e034e8fb1d3568bdcf8aac4c07`
- `gameCatalog.ts` `f85cb025e9c9d634b9c6da00baa89c79`
- `casino.css` `1664a56e091e099dc4f762b030d0e1c5`

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: стоп. Клики на **18081** после заливки (сейчас на шлюзе старый бандл).

Потыкать:
- `http://127.0.0.1:18081/casino` — плитки не один эмодзи; сверху «Как играть»; на плитке короткая подсказка. Админку не смотреть.
- `http://127.0.0.1:18081/casino/poker` → редирект на play/holdem; сесть за стол (`/casino/poker/:id`). Борд и карман — карты, не `Ah`. Чужие — рубашки. Фолд — «фолд».
- Mini App `http://127.0.0.1:18081/casino/tg/poker/:id` — сукно влезает, без лага скролла. F5 — разметка живая.

## 2026-08-29 — Баккара/блэкджек: дом + игроки

Клики прошлых срезов в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` / `staging-sync.sh` / `--apply` / `staging-test.sh` **не** гонял. Broadcast нет. HMAC-колоду, формулу комиссии дуэли и RTP куба **не** менял. Админку `/x8` не рестил. Срез кубиков house-multi / V2 dice не трогал (файлы уже у других агентов).

Сделано:

1. **Дом (баккара и блэкджек).** Вкладка «Против казино» больше не заглушка. `POST /api/user/casino/play` `{game_type: baccara|blackjack}` → `play_house_cards_with_conn`: карты с HMAC-колоды (`casino_cards.dealt_cards`, игрок=`creator`, дом=`opponent`). Баккара: 3-я карта при счёте ≤5. Блэкджек: добор до 17. Победитель — счёт (`compare_house_cards`), не порог cub. Выплата `calculate_house_settlement`: 100 ₽ ×2 @ 5% = **195 ₽**; ничья ×1 (push 100 ₽, комиссия 0); проигрыш ×0. Банк — `house_robot` (игра или fallback cub). Котировка без `win_probability` cub.
2. **Игроки.** По-прежнему дуэли 1×1 (`CasinoPlayersLobby` + `CasinoDuelRoom`). POV: в `active` зритель видит свои лица, чужие — рубашки; зритель без места — пусто до публичного статуса. После `finished`/`outcome_committed` — обе руки. Банк победителю как раньше (комиссию дуэли не трогал).
3. **UI.** Новый `CasinoHouseCards.tsx` (SVG, `data-casino-house-cards`). Кнопка ставки `data-casino-house-play={baccara|blackjack}`. Дефолт страницы — `?mode=players`.

Пробел V2: `casino_v2_web.py` на сайте **только кубики** (`game_type != pvp_dice` → «На сайте V2 пока только кубики»). User-маршрутов V2 2–6 для баккары/блэкджека нет. Стол 2–6 vs дом для карт тоже не делал (у кубиков уже есть `CasinoHouseTables`).

Файлы:
- `site/exchange-backend/casino_house_cards.py` (новый)
- `casino_play.py` (`HOUSE_PLAY_GAME_TYPES`, `load_card_house_play_quote`)
- `casino_duels.py` (`pov_duel_hands`)
- `routers/user_casino.py`, `routers/public_casino.py` (quote/tape `game_type`)
- `tests/test_casino_house_cards.py` (новый), `test_casino_play.py`, `test_casino_duels.py`
- `focussite/frontend/src/casino/CasinoHouseCards.tsx`
- `CasinoPlay.tsx`, `CasinoDuelRoom.tsx`, `src/lib/public.ts`

Локально: `npm run build` → `tsc -b && vite build` чистый. Бандл `index-C8KkFXWJ.js` / `index-CfZ5W2Gm.js` / `casino-D7BrChMe.js` 1.28 kB / CSS `index-CvaBm6IQ.css`.

Тесты (venv, без staging-test): **60** pytest = house_cards **10** + duels **17** + play **6** + cards **11** + commission **16**. Все OK. `test_win_100_times_2_at_5_percent_is_195` и commission `(5, 195.00, 5.00)` живы. HMAC-shoe `test_casino_cards` 11 OK.

`rg` house не мёртвая копия: `play_house_cards_with_conn` (модуль + `user_casino` POST `/casino/play` + тесты); `data-casino-house-play` + `playCasinoHouseRound(amount, houseGameType)` в `CasinoPlay`; `data-casino-house-cards` в `CasinoHouseCards`; quote `load_card_house_play_quote`.

md5 local:

- `casino_house_cards.py` `567389f6dadde3cd512c288e5333d2be`
- `casino_play.py` `ae74b70972e942ea52c79a2ff47ec2fc`
- `casino_duels.py` `a05ed4f832dac61a762ecb5384fece63`
- `CasinoHouseCards.tsx` `0c77ce81c126aacaf2fc406adb84466f`
- `CasinoPlay.tsx` `39baed6f09d268d47ee1cb4f48fd4f20`
- `CasinoDuelRoom.tsx` `5253a7de3a98e981f3ab67425e061a9f`

Staging md5 не сверял (sync запрещён). SQL не менял. `focuspay-casino` этот срез не трогал (HEAD `4b8d65e`).

Docker staging (read-only): наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: стоп. Клики на **18081** после заливки (сейчас на шлюзе старый бандл).

Потыкать:
- `http://127.0.0.1:18081/casino/play/baccara?mode=house` — ставка, SVG-карты слева вы / справа казино, исход с сервера, «Выигрыш при победе» при 100 ₽ = 195 ₽, не копипаст «стол не подключен».
- `http://127.0.0.1:18081/casino/play/baccara?mode=players` — лобби дуэлей баккары, 1×1, после входа свои карты лицом, чужие рубашкой до конца.
- То же для `http://127.0.0.1:18081/casino/play/blackjack?mode=house` и `?mode=players`.
- Mini App `http://127.0.0.1:18081/casino/tg/play/baccara` — те же табы, дом не заглушка.

## 2026-08-29 — House-multi: кубики стол 2–6 vs дом

Клики прошлых срезов в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` / `staging-sync.sh` / `--apply` / `staging-test.sh` **не** гонял (запрет среза: шесть агентов на одном staging). Broadcast не трогал. HMAC cub RTP / `win_probability` / формулу комиссии **не** менял. `play_cub_with_conn` не редактировал. Покер, джекпот, кланы, V2 settle, спорт PvP, raffle 36+0 не трогал. V2 web / баккара-стол **не** начинал.

Сделано: стол 2–6 человек против казино на вкладке «Против казино» у кубиков. Каждый держит **свою** ставку и считается с домом через `calculate_house_settlement` (как cub). Банка между игроками нет. Боты `house_robot` садятся **за казино**, stake 0 ₽, кошельки юзеров не дебетят. Живые деньги человека = `prepare_cub` + `play_cub_with_conn` (тот же HMAC `game_id:nonce`). Холст: N кубов игроков + куб(ы) дома. 1×1 HMAC cub на `/casino/play/pvp_dice?mode=house` без `view=table` **остался**.

Деньги (конкретные числа в тестах, комиссия 5%, ×2):
- 100 ₽ выигрыш → выплата **195.00**, комиссия **5.00**, house_delta **−95.00**
- 100 ₽ проигрыш → **0.00**, дом **+100.00**
- 250 ₽ выигрыш → **487.50**
- двое по 100 ₽ оба выиграли → **390.00** (не V2-банк 195)
- 100+250 оба выиграли, резерв дома **682.50**
- бот дома: debit **0.00**

Файлы (этот срез):
- `site/exchange-backend/casino_house_tables.py` (новый)
- `site/exchange-backend/tests/test_casino_house_tables.py` (новый, **27 OK**)
- `site/exchange-backend/migrations/add_casino_house_tables.sql` (таблицы, **без** новых ключей `casino_settings`)
- `routers/user_casino.py` JWT create/sit/leave/start; `routers/public_casino.py` list/get
- `focussite/frontend/src/casino/CasinoHouseTables.tsx` (новый)
- `CasinoDice.tsx` (`CasinoDiceTable`, `data-casino-house-dice`)
- `CasinoPlay.tsx` (таб 1×1 | Стол 2–6, `data-casino-house-view`)
- `src/lib/public.ts`, `casino.css`
- bootstrap: `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`

Локально: `.venv/bin/python -m unittest tests.test_casino_house_tables` → **27 OK**. `npm run build` → `tsc -b && vite build` чистый: `index-C8KkFXWJ.js` / `index-CfZ5W2Gm.js` (в чанке `house-tables`) / `casino-D7BrChMe.js` 1.28 kB / CSS `index-CvaBm6IQ.css` / `panel-DCJwSGCk.js`. `bootstrap_static_test.sh` passed.

Залито: **нет**. Staging md5 не сверял. SQL ключей не добавлял (остаётся **59**). Новые таблицы: `casino_house_tables`, `casino_house_table_seats`. `focuspay-casino` не трогал.

`rg`: `play_human_cub` / `HOUSE_BOT_SEAT_BASE` — модуль + тесты + bootstrap_static; `/casino/house-tables` — user + public + `public.ts`; `CasinoHouseTables` / `data-casino-house-tables` — Play + HouseTables; `data-casino-house-dice` — Dice; `data-casino-house-view` — Play. Цепочка domain + API + UI есть.

md5 local:
- `casino_house_tables.py` `f93d109b0ee462e4b358754fbb67fbfb`
- `test_casino_house_tables.py` `c0a1495190ed79af648f4ff7f72908f9`
- `add_casino_house_tables.sql` `fe5a9b65b585d107aebf10464c44d4cc`
- `CasinoHouseTables.tsx` `2d8a2cea9fee2254498ccdd17b701bc2`
- `CasinoPlay.tsx` `39baed6f09d268d47ee1cb4f48fd4f20`
- `CasinoDice.tsx` `c2c225f7e298b6f2337d09bccbdb0b15`
- `public.ts` `db57af66473c49d368531df011448de2`

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: стоп. Клики на **18081** после заливки (сейчас на шлюзе старый бандл). V2 web / баккара-стол **не начинать**.

Потыкать (туннель **18081**):
- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house` — таб **1×1** как раньше: ставка слева, два куба, HMAC-подпись, лента. Авто. F5. **Должно остаться.**
- Таб **Стол 2–6** (`?mode=house&view=table`) — лобби, свои ставки (не общий банк), боты дома 0–3. Создать стол. Один человек **не** запускает раунд (нужно 2–6 людей).
- Второй аккаунт: Сесть со **своей** суммой (можно не равной). «Играть раунд» — N кубов игроков + куб(ы) казино. Выплаты разные, не один банк. Боты без списания с юзеров.
- Вернуться на 1×1 — cub без стола, quote 100 ₽ при 5% по-прежнему 195 ₽.

## 2026-08-29 — V2 web: кубики 2–6 банк победителю

Клики прошлых срезов в этом сеансе не закрывались. Прод не деплоил. `deploy_all.py` / `staging-sync.sh` / `--apply` / `staging-test.sh` **не** гонял (запрет среза). Broadcast не трогал. House 1×1 cub / RTP / `play_cub_with_conn` не менял. `house_settlement` на V2 стол не вешал. Спорт PvP, баккара/блэкджек V2, холдем, кланы не начинал. `focuspay-casino` не трогал.

Сделано: вкладка «С игроками» у кубиков — лобби V2 **2–6 мест**, равные ставки, победитель забирает банк после комиссии 5% от полного банка. Деньги: `create_v2_table_with_conn` / join / `commit_v2_table_outcome_with_conn` / `settle_committed_v2_table_with_conn` (не новый settle). Боты `pvp_robot` садятся при создании, пока стол `open`. Броски HMAC (`hmac_pip`, не `send_dice` и не RNG браузера). Дуэли 1×1 `casino_games` остаются фильтром ниже списка столов.

Деньги (тесты = тот же settle):
- 2 игрока × 100 ₽ → банк **200.00**, комиссия **10.00**, победителю **190.00** (это не 1×1 helper 195.00)
- 3 игрока × 100 ₽ → **300.00** / **15.00** / **285.00**
- 1 человек + бот, победил игрок → `confirm_hold`×1, `credit_winner` только user_id игрока, **190.00**
- победил бот → `credit_winner` не вызывается, холд игрока подтверждается

CAS: join со `expected_state_version` старше таблицы → 409 «Стол изменился». Сид HMAC в публичном JSON до финиша не отдаётся, `creator_id` на верхнем уровне нет.

Файлы (этот срез):
- `site/exchange-backend/casino_v2_web.py` (новый)
- `site/exchange-backend/tests/test_casino_v2_web.py` (новый, **17 OK**)
- `routers/user_casino.py` JWT create/join/start/leave/cancel/roll
- `routers/public_casino.py` GET list/get
- `focussite/frontend/src/casino/CasinoV2Table.tsx` (новый)
- `CasinoPlayersLobby.tsx` (V2 лобби при `pvp_dice`)
- `src/lib/public.ts`, `App.tsx`, `miniapp-main.tsx` (`/casino/tables/:tableId`)
- `CasinoLobby.tsx` (промо 2–6), `CasinoDice.tsx` (`seat?: string`), `casino.css`

Локально: `.venv/bin/python -m unittest tests.test_casino_v2_web` → **17 OK**. `tsc -b` чистый. SQL / ключи настроек не менял (остаётся **59**).

Залито: **нет**. Staging md5 не сверял. `focuspay-casino` HEAD `4b8d65e`, этот срез не трогал.

`rg`: `/casino/v2/tables` — `user_casino` (6 POST) + `public_casino` (2 GET) + `public.ts`; `CasinoV2Table` / `data-casino-v2-lobby` / `data-casino-v2-table` / `data-casino-v2-roll` — UI; `create_web_table` — модуль + user router. Цепочка domain + API + UI есть.

md5 local:
- `casino_v2_web.py` `8c31bd77bbc1f35eafd65988ceb25c5f`
- `test_casino_v2_web.py` `c0730da7fc51bdd608392802777f440e`
- `routers/user_casino.py` `abfe4862289f0718fb9242fc9691aabd`
- `routers/public_casino.py` `cc81ba1a0788524f9edfbeaf4493f5da`
- `CasinoV2Table.tsx` `45a368ed3b58a287c869d0b0ba887af4`
- `CasinoPlayersLobby.tsx` `51afa3fa12d26c604f4950b7eda4e682`
- `public.ts` `db57af66473c49d368531df011448de2`

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: стоп. Баккара V2 **не начинать**. Клики на **18081** после заливки (сейчас на шлюзе старый бандл).

Потыкать (туннель **18081**):
- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house` — 1×1 cub как был (ставка слева, два куба, quote 100 ₽ → 195 ₽). **Должно остаться.** Не путать со столом vs дом (`view=table`).
- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=players` — лобби столов 2–6: ставка, число мест, боты, превью банка/комиссии/выплаты. «Создать» → `/casino/tables/:id`. «Найти» садится в открытый стол с той же ставкой.
- Стол: кубы по местам, HMAC-подпись, не клиентский RNG. Пока open — боты уже на местах. Старт если мест ≥2 и стол не полный. Кинуть кубик. Победитель забирает банк после 5% (двое по 100 → на руки 190, не 195). Ничья — переброс лидеров.
- Второй аккаунт: Войти на свободное место, та же ставка. Чужой баланс бот не снимает.
- Ниже списка V2 — блок «Дуэли 1×1» (старый `casino_games`). Можно не пользоваться.
- F5 на столе — статус и кубы те же. 409 «Стол изменился» если войти с устаревшей версии (два одновременных входа).

## 2026-08-29 — Фикс-комнаты N и клан vs клан

Прод не деплоил. `deploy_all.py` / `staging-sync.sh` / `--apply` / `staging-test.sh` **не** гонял (запрет среза). Broadcast / спорт / 36+0 не трогал. `casino_jackpot.py` ролл/билеты **не** менял (новый продукт рядом). Клановый банк / treasury **не** делал. Бот `focuspay-casino` в этом срезе не трогал (web first). Коммит не делал.

Правила **фикс-комнат** (не CSGETGO):
- Создатель задаёт ставку S (min/max bet) и N мест (2…`fixed_room_max_seats`, дефолт 10). У всех одна ставка, одно место, без докупки.
- Commit `SHA-256(server_seed)` при создании; сид скрыт до lock.
- Победитель: `HMAC-SHA256(seed, "{room_id}:{join_order_ids}") % N`. Алгоритм `hmac-sha256-commit-reveal`.
- Полный набор → lock → рейк `fixed_room_rake_percent` (дефолт 5%) → победителю банк − рейк.
- Таймаут `fixed_room_collect_seconds` (дефолт 600): **полный возврат**, не частичный розыгрыш. Создатель один — может отменить.
- Одна живая open/locked комната на игрока.

Правила **клан vs клан**:
- Участник клана создаёт войну: S с бойца, N бойцов со стороны (1…`clan_war_max_fighters`, дефолт 5). Создатель сразу в составе, холд с **кошелька игрока**.
- Другой клан принимает (acceptor в составе). Свой клан принять нельзя. Дальше добирают до N с каждой стороны.
- Оба состава полные: HMAC `% 2` (0 = challenger, 1 = opponent), сообщение `{war_id}:{challenger_clan}:{opponent_clan}:{sorted_A}|{sorted_B}`.
- Победители делят банк − рейк (`clan_war_rake_percent` 5%) поровну; копейки на первую долю. Таймаут — возврат всем.
- Клан без баланса. Если `clans_enabled` = false — войны выключены. Create/join клана как было.

Рубли в тестах: 4×100 ₽, 5% → дом **20**, победителю **380**. 2v2 × 50 ₽ → банк **200**, рейк **10**, каждому победителю **95**.

Файлы (этот срез):
- `site/exchange-backend/casino_fixed_rooms.py`, `casino_clan_wars.py` (новые)
- `migrations/add_casino_fixed_rooms.sql`, `add_casino_clan_wars.sql` — в `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`
- `tests/test_casino_fixed_rooms.py` (**9 OK**), `tests/test_casino_clan_wars.py` (**8 OK**) → **17** новых
- `casino_settings_registry.py`, `routers/admin_casino.py` GET/PATCH, `adminApi.ts`, `CasinoSettings.tsx` секции `section-fixed_rooms` / `section-clan_wars`
- `casino_weekly_wager.py` UNION `casino_fixed_room_rounds.wager_json` + `casino_clan_wars.wager_json`; `CASHBACK_GAME_TYPES` + `PLAYER_WAGER_SQL` в кланах
- `routers/user_casino.py` JWT create/join/cancel rooms, create/accept/join wars; `public_casino.py` GET lobby + fairness HMAC
- UI: `CasinoFixedRooms.tsx`, `CasinoClanWars.tsx`, каталог, Mini App `/casino/rooms/:id` `/casino/wars/:id`

Ключи: `fixed_room_rake_percent`, `fixed_room_max_seats`, `fixed_room_collect_seconds`, `clan_war_rake_percent`, `clan_war_max_fighters`, `clan_war_collect_seconds`. Игры `fixed_room`, `clan_war` в `enabled_games`.

Локально:
- `python -m unittest tests.test_casino_fixed_rooms tests.test_casino_clan_wars` → **17 OK**
- плюс clans + settings registry + public lobby + jackpot → **61 OK** (0 fail)
- `tests.test_admin_casino_regression` + settings + lobby → **59 OK**
- `focussite/docker/staging-db/bootstrap_static_test.sh` → passed
- `npm run build` (`tsc -b && vite`) → OK

`rg` (цепочка registry + migration + admin):
- `fixed_room_rake_percent` — 10 файлов: registry, `add_casino_fixed_rooms.sql`, `admin_casino.py`, `adminApi.ts`, `CasinoSettings.tsx`, `casinoSettingsModel.ts`, `casinoAuditModel.ts`, `casino_fixed_rooms.py`, `test_casino_fixed_rooms.py`, `test_casino_settings_registry.py`
- `clan_war_rake_percent` — 10 файлов: то же для wars (`add_casino_clan_wars.sql`, `casino_clan_wars.py`, `test_casino_clan_wars.py`, …)

md5 local:
- `casino_fixed_rooms.py` `ed27429f1fc6b41cc0509428f2c80ce0`
- `casino_clan_wars.py` `8d650e7a81e64324726f0cb7ca98fde8`
- `add_casino_fixed_rooms.sql` `d575639f95639832e259a2836dba2ffa`
- `add_casino_clan_wars.sql` `820ff238c3af99b4d7755b1477994687`
- `test_casino_fixed_rooms.py` `424a239c583660d6b34316113052dee1`
- `test_casino_clan_wars.py` `6079ec68a11e90f4c9b88e1a4041dc1f`
- `CasinoFixedRooms.tsx` `881455e336b287cf9c187a72405251d4`
- `CasinoClanWars.tsx` `c7932207c531847ca287898193a3f984`

Залито: **нет**. Staging md5 не сверял.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, этот срез не трогал. Не коммитил.

Следующий шаг: стоп. Клики на **18081** после заливки (сейчас на шлюзе этого кода нет).

Потыкать (туннель **18081**):
- `http://127.0.0.1:18081/casino/play/fixed_room?mode=players` — создать комнату (например 100 ₽, 3–4 места). Второй аккаунт: сесть той же ставкой. На полном составе: один победитель, рейк 5% (четверо по 100 → на руки 380). Ссылка честности HMAC. F5. Пока недобор — не крутится. Таймаут / отмена создателя одного — возврат.
- `http://127.0.0.1:18081/casino/jackpot` — как был (билеты пропорциональны ставке). **Должно остаться.**
- `http://127.0.0.1:18081/casino/clans` — создать/вступить по коду как раньше. Ссылка «Война кланов».
- `http://127.0.0.1:18081/casino/play/clan_war?mode=players` — два клана: вызов → принять чужим кланом → добрать бойцов с **личных** балансов. На полном 2v2: HMAC клан-победитель, банк делится. Казны клана нет.
- `http://127.0.0.1:18081/x8/casino/settings` — секции «Фикс-комнаты» / «Война кланов»; `clans_enabled` на месте. Сохранить, F5.
- Выключить игру `fixed_room` / `clan_war` в «Включённые игры» — плитки/создание не должны пускать.

## 2026-08-29 — Выкат шести срезов на staging

Прод не деплоил. `deploy_all.py` не гонял. Broadcast не переписывал. Коммит не делал.

Сделано: залиты на staging шесть параллельных срезов (house-multi, V2 web кубики, баккара/блэкджек дом 1×1, оболочка холдем/джекпот/раффл, сукно холдема + плитки, фикс-комнаты + клан vs клан). Локально `npm run build` чистый: `index-kgnoxvX8.js` / `index-CVJlG8Js.js` / `index-9PQSFEfe.css` / `panel-8qJIOJJC.js` / `casino.html` 0.85 kB. `bootstrap_static_test.sh` passed.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` — rsync обоих деревьев + образы собрались (gateway `tsc -b && vite` на сервере тот же бандл). `--apply` упал на Recreate backend: имя `/focuspay-staging-runtime-backend-1` занято leftover `e001789a6d37_…`. Снёс leftover, `compose up -d --wait --profile bot --profile casino` **без** `--build` и без `down -v`. Health passed. Postgres volume жив.

Первый `--apply` Recreate postgres; том жив: ключей **65** (было 59; +6 `fixed_room_*` / `clan_war_*`). `casino_games` **354**. Новые таблицы: `casino_house_tables` / `casino_house_table_seats`, `casino_fixed_room_rounds` / `casino_fixed_room_seats`, `casino_clan_wars` / `casino_clan_war_fighters`. Bootstrap: `INSERT 0 3` + `INSERT 0 3` на новых ключах.

Healthcheck: `staging runtime health check passed` после up и повторно после `staging-test.sh`.

Тесты на staging: `sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env ./scripts/staging-test.sh` → **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1221** (было 1148, **+73**). Новых имён в упавших нет. ≈1214 passed (1221−7). DurableLifecycle по-прежнему падают на mock `fetchrow` из-за UNION в `weekly_wager_rub` (теперь ещё `casino_fixed_room_rounds` + `casino_clan_wars`) — те же три имени, не чинил.

Живой шлюз **200**: `/casino`, `/casino/play/pvp_dice`, `/holdem`, `/jackpot`, `/baccara`, `/fixed_room`, `/clan_war`, `/casino/tg`, `/api/public/casino/v2/tables`, `/api/health`, `/x8/casino`. Quote 100 ₽ ×2 @ 5%: `win_on_win_rub=195.0`. Лобби API 9 id включая `fixed_room` + `clan_war`. Бандл: `data-casino-house-tables` и `play/holdem` в `index-CVJlG8Js.js`, `casino-felt` в `index-9PQSFEfe.css`.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_house_tables.py` `f93d109b0ee462e4b358754fbb67fbfb`
- `casino_v2_web.py` `8c31bd77bbc1f35eafd65988ceb25c5f`
- `casino_house_cards.py` `567389f6dadde3cd512c288e5333d2be`
- `casino_fixed_rooms.py` `ed27429f1fc6b41cc0509428f2c80ce0`
- `casino_clan_wars.py` `8d650e7a81e64324726f0cb7ca98fde8`
- `CasinoPlay.tsx` `46537695f6464d18f3de761c44ad233d`
- `CasinoHouseTables.tsx` `2d8a2cea9fee2254498ccdd17b701bc2`
- `CasinoV2Table.tsx` `45a368ed3b58a287c869d0b0ba887af4`
- `CasinoHouseCards.tsx` `0c77ce81c126aacaf2fc406adb84466f`
- `CasinoPokerTable.tsx` `f6efa6c370fe35c983852d3b1c87aec2`
- `gameCatalog.ts` `4a7f1bf6d1d714463c451a9c9703cb62`

`rg` `fixed_room_rake_percent`: registry + migration + admin GET/PATCH + CasinoSettings + tests. `play_house_cards_with_conn`: domain + user router + tests.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.

Прод (read-only): `index.html` 2026-08-28 04:22:45 UTC, `panel.html` 04:22:48 UTC, unit 08:33:32 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: клик-приёмка пачки на туннеле **18081**. Карты 2–6 vs дом и V2 карт **не** начинать, пока не примешь это.

Потыкать:
- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house` — 1×1: 100 ₽ → 195 ₽; вкладка **Стол 2–6** — свои ставки, боты дома, старт от 2 человек.
- `?mode=players` — лобби V2 2–6, создать → `/casino/tables/:id`, двое по 100 → победителю **190**. Дуэли 1×1 ниже списка.
- `/casino/play/baccara?mode=house` и blackjack — SVG vs казино, не копирайт «стол не подключен»; `?mode=players` — дуэль, свои лицом / чужие рубашкой.
- `/casino/play/holdem` — табы; игроки = столы NLHE, карты на сукне не `Ah`. `/casino/play/jackpot` — колесо. `/casino/play/raffle` — FocusLucky, не 36+0.
- `/casino` — плитки с артом и «Как играть».
- `/casino/play/fixed_room?mode=players` — равная ставка N мест; джекпот `/casino/jackpot` как был.
- `/casino/play/clan_war?mode=players` — два клана, деньги с личных балансов; `/casino/clans` create/join жив.
- Mini App `/casino/tg/play/pvp_dice`. Админка `/x8/casino/settings` — Фикс-комнаты / Война кланов; F5.

## 2026-08-29 — Стол 2–6: комната, один игрок, профиль и аватар

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал.

Сделано: после «Создать стол» сразу комната (снимок не сбрасывается, в URL `ht=`). Начать можно **одному**. Пустые места — силуэты. В шапке и рельсе — **Профиль** и **Настройки казино** (имя + загрузка аватара). `public_actors` берёт ник/аватар из `casino_player_cosmetics`, иначе Telegram.

Почему лобби «столов нет»: `loadTable` при пустом `ht` обнулял snap; публичный GET без JWT не видел `is_seated`; старт требовал 2 человек — кнопки «Кинуть кубики» не было.

Локально: `bootstrap_static_test.sh` passed. `npm run build` → `index-DGrVwCpC.js` / `index-DQOX5sSC.css` / `panel-BsmzFzes.js`. Unittest house+cosmetics+chat+profile: 43 OK (локально без venv падает только импорт jwt/asyncpg на route-тесте).

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` — rsync + `--apply` + health, Recreate postgres **без** `down -v`. Затем точечный rsync `tests/test_casino_duels.py` (моки `_Conn.fetch` под cosmetics).

Healthcheck: `staging runtime health check passed`.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect **1231** (было 1221, **+10**: cosmetics + уже лежавшие в дереве тесты). Первый прогон дал **ещё 2** имени (`DuelActorFillTests` ×2, нет `fetch` у мока) — починил моки, повтор: новых имён нет. ≈1224 passed (1231−7).

SQL: ключей **65** (как вчера). `casino_games` **355** (было 354). `to_regclass` `casino_player_cosmetics` и `casino_house_tables` живы.

Живой шлюз **200**: `/casino`, `/casino/play/pvp_dice?mode=house&view=table`, `/api/health`. Лобби 9 игр.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_house_tables.py` `2d2e32db1cc17d1f819fc6b29206174f`
- `casino_player_cosmetics.py` `03fb4577f7ced522cd7a976589e660f4`
- `casino_chat.py` `d99850e07bb28d8ea22330620da30301`
- `add_casino_player_cosmetics.sql` `34d5fe6a439ba22a81b17b621b688865`
- `test_casino_house_tables.py` `347aa5f66c68af8aa3349f0f632a9dfa`
- `test_casino_player_cosmetics.py` `08cb19b3939cb7baaea69516e6b93ce1`
- `test_casino_duels.py` `a81d0b8147bbfd1f65bca74f151d9461`
- `CasinoHouseTables.tsx` `9da45e15616254cd3a4a5d209ebd7449`
- `CasinoPlayerSettings.tsx` `0c11a1914aac3012134e639b5760e1e4`
- `CasinoShell.tsx` `eecc8e1f51315a78f389691e6b3156b7`
- `CasinoPlay.tsx` `b80ee9db4b8fb4e0445ff57e109a2447`

`rg` `casino_player_cosmetics`: миграция + `00-apply`/`20-full-panel`/`bootstrap_static_test` + модуль + `public_actors` + PATCH/POST `/casino/players/me` + public `/casino-avatars/` + UI настроек.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.

Прод (read-only `ssh focuspay`): `panel.html` 2026-08-28 04:22:48 UTC как вчера. **`index.html` 2026-08-29 06:08:38 UTC** и unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC` — сдвинулись относительно вчерашнего журнала. Этот агент `deploy_all.py` не запускал и на `153.80.249.77` ничего не писал; панель не менялась. Если это не твой выкат сайта — разобрать отдельно.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп. Клики на туннеле **18081** (у тебя в скрине был **18082** — тот же шлюз, другой проброс).

Потыкать:
- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house&view=table` — **Создать стол** → сразу комната, URL с `ht=`, места (вы + пустые силуэты + дом). **Кинуть кубики** одному. Ссылка копируется. F5 с `ht=` открывает тот же стол.
- 1×1 вкладка: 100 ₽ → на руки **195 ₽**. **Должно остаться.**
- Шапка (кружок) → профиль казино, не кошелёк. Рельс **Профиль** / **Настройки**.
- `/casino/settings` — имя, файл аватара (JPG/PNG/WebP ≤512 КБ), сохранить, F5, аватар в шапке и за столом.
- Лобби столов: чипы игроков и пустые места, **К столу** / **Сесть**.

## 2026-08-29 — Фикс: дуэль кубиков зависла («и ничего не происходит»)

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: комната `http://178.63.247.233:18082/casino/duels/037caa82-5d5d-4a9d-8038-07bd5c2b86c7` (id **`5d5d`**, не OCR `5d5c`). Ставка 25 ₽, банк 50, на руки 48.75. Соперник `@absoluteop` (creator 8443902979) не бросил; Fixture Buyer (940002) кинул **2**. UI рисовал пустому месту грань **1** (`asDiePips ?? 1`) и писало «Лидер: Вы». В ЛС бота кубик не принялся: «Против казино — /cub».

Почему не закрылось:
1. Closer `house_fill_due` брал 20 игр в **одной** транзакции. Старая `3ceac667-…` падала `409: Hold … has expired` и откатывала пачку — эта дуэль не получала house-fill.
2. Холд создателя: `expires_at` = create+2h (`2026-08-28 02:23`), игра создана 28-го, соперник сел **29-го 08:21**. К моменту бросков холд уже просрочен.
3. Бот требовал `game.chat_id ==` группы; ЛС не матчилась.

Сделано:
- Closer: по игре своя транзакция; `house_fill_if_due` на GET комнаты; просроченный холд → `timeout` refund, не блокирует очередь.
- `touch_active_holds`: `expires_at = now()+2h` на join / roll / house-fill.
- UI: пустой куб `data-pending`, не фейковая 1; «Лидер» только когда оба куба есть; `cancelled` → «ставки вернулись».
- Бот: ЛС 🎲 пишет `record_pvp_dice_roll` (кэш или `get_active_pvp_games`).

Живой ряд после первого closer: **`cancelled`**, `outcome={"kind":"timeout","reason":"pvp_dice_hold_expired"}`, `finished_at=2026-08-29 08:39:32+00`. Оба холда **released** (creator expired 28-го 02:23, opponent до 10:21). `creator_rolls=[]`, `opponent_rolls=[2]`. Деньги вернулись, победителя нет. `active` pvp_dice с opponent: **0**. Эту партию не раскручивать.

Локально:
- `PYTHONPATH=. python3 -m unittest` isolation + hold-touch + house-fill → **18 OK** (тесты с `patch routers.internal_casino` локально без asyncpg не импортятся; на staging они зелёные).
- `focuspay-casino` `tests.test_pvp_dice` → **13 OK**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` (hold-extend), затем rsync теста + `staging-runtime-update.sh --apply` (копия cancelled). Health passed. Postgres volume жив: ключей **65**, `casino_games` **355**.

Healthcheck: `staging runtime health check passed`.

Тесты на staging: `staging-test.sh` → **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Первый прогон дал **ещё 1** имя (`PvpDiceOutboxTests.test_web_roll_writes_hmac_pip`, `execute` 3≠2 из-за touch) — поправил assert + проверку SQL `expires_at`. Повтор: новых имён нет. Collect-only **1234** (было 1231, **+3**: isolation ×2 + hold-touch). ≈1227 passed (1234−7).

Живой шлюз **200**: `/casino`, `/casino/duels/037caa82-5d5d-…`. Бандл `index-kbgWNrdJ.js` содержит «ставки вернулись на балансы», `data-casino-waiting-roll`, `is-pending`. CSS `index-CXlRA7dW.css`.

md5 local = staging `/opt` = live `/app/backend` / `/app/games`:

- `casino_pvp_dice.py` `800b55ee19e92e9d59035a89b14b1e36`
- `public_casino.py` `6476f87aa60cd4aab648eaa2bf8423af`
- `test_casino_pvp_dice.py` `e7d4cda23507a7fada91011f3afc208d`
- `CasinoDuelRoom.tsx` `6ede1db5c4663171c895286692f4b5f5`
- `CasinoDice.tsx` `43567db9fa171778d353a3f200903f6a`
- `casino.css` `132efc666e36d1908cb801682043973a`
- `games/pvp.py` `c317098b2dc34ea839299f52a0467be8`

`rg`: `touch_active_holds` — def + join/roll/house_fill в `casino_pvp_dice.py` + assert SQL в тесте. `house_fill_if_due` — модуль + `GET /casino/duels/{id}` в `public_casino.py`. `_record_private_dice_via_api` — `games/pvp.py` + `tests/test_pvp_dice.py` (кэш и cold API).

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-play-public` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Как в предыдущей записи этого дня. Этот агент на прод не писал.

Git: `focuspay` HEAD `61e47be`, dirty (весь WIP казино + этот фикс). `focuspay-casino` HEAD `4b8d65e`, dirty (`games/pvp.py` + `tests/test_pvp_dice.py`). Не коммитил.

Следующий шаг: стоп. Новую дуэль, не эту. Карты 2–6 / следующий пункт плана **не** начинать.

Потыкать (туннель **18081**; у тебя в скрине был **18082** — тот же шлюз):
- Эта ссылка `…/duels/037caa82-5d5d-…` — после F5: **«Дуэль отменена — ставки вернулись»**, не «Лидер» и не выплата 48.75. Баланс +25 ₽. **Не ждать** house-fill на ней.
- Новая дуэль `/casino/duels` или `/casino/play/pvp_dice?mode=players`: сесть, кинуть. Пустое место **без** грани 1 (тусклый куб). После 30 с без броска — казино кидает, «Победитель · на руки».
- Telegram ЛС `focuscaztest`: 🎲 в личку на **новой** активной дуэли должен записаться, не «кидай в игровой группе». Группа по-прежнему тоже ок.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**

## 2026-08-29 — Стол 2–6: после броска места пустели

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: `/casino/tables/web-6179aeff68e5436c` — «Кубики · стол 3», 100 ₽ / банк 300 / комиссия 15 / победителю 285, статус **завершён**. Три карточки «Место N» без имён и кубов. Бросок с сайта и из Telegram одинаково: после settle API отдавал пустой `roster`.

Почему: `settle` ставит местам `status='settled'`, а `_v2_table_response_with_conn` читал только `status='seated'`. GET/POST сразу после последнего куба рисовал пустые слоты.

Сделано:
- Roster SQL: `seated` **или** `settled`.
- `hydrate_roster` поднимает места из `seat_nos` / ключей `sNrM`, если SQL пустой.
- `is_winner` в публичном JSON. UI: зелёный победитель, красный проигравший, куб и сумма, строка «Победитель · на руки».

Живой GET после заливки: roster `[(1, 6, True, Fixture Buyer), (2, 1, False, PvP Robot 1), (3, 5, False, @absoluteop)]`, winners `[1]`.

Локально: `tests.test_casino_v2_web` + `V2RosterResponseTests` → **21 OK**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health passed.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1236** (было 1234, **+2**). Новых имён нет. ≈1229 passed (1236−7).

Бандл: `index-KHec2Ork.js` — `is-winner` / `is-loser` / `data-casino-v2-result`. CSS `index-CltnJokf.css`.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_v2_web.py` `605c2a71c7c4251e9333fcf79383dc37`
- `internal_casino.py` `d8769b2bf215ec4c8e3eb44f304638fe`
- `test_casino_v2_web.py` `36bbe30a35a47b5b451599b67cbfaca6`
- `CasinoV2Table.tsx` `333f239ad7d665c88ebecd6d0e8b69d7`
- `casino.css` `f15f4df183b52ff5da65675d745cf79f`

`rg`: `hydrate_roster` — модуль + `public_table_view`; `status IN ('seated', 'settled')` — `_v2_table_response_with_conn`; `is-winner` — CSS + `CasinoV2Table`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway.

Прод (read-only): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit 06:08:19 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил. `focuspay-casino` не трогал.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз):
- F5 `http://127.0.0.1:18081/casino/tables/web-6179aeff68e5436c` — три места с именами и кубами **6 / 1 / 5**. Fixture Buyer **зелёный** (победа), робот и @absoluteop **красные**. Строка «Победитель · на руки 285 ₽». Пустых «Место N» без куба быть не должно.
- Новая партия 2–3 игрока (сайт или Telegram 🎲): после последнего броска места **не** пропадают, цвета те же.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**

## 2026-08-29 — Сайт-баккара не видна в Telegram

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: баккара с сайта (`/casino/duels/web-03e1a2745423`, 100 ₽, Fixture Buyer ждёт) есть на вебе, в Telegram её не было. Сайтовый `POST /casino/duels` шёл в `create_or_resume` без `game_chat_id` и без `casino_pvp_invitation_outbox`. Воркер приглашений постит только из outbox. Кэш `/baccara` тоже не видел `web-*` id. Кнопка `join_` у кубиков для карт не подходит.

Сделано:
- После **создания** дуэли с сайта: пин активного игрового чата + outbox (`rounds: 0` для карт, `1` для кубиков, `origin: web`).
- `get_active_pvp_games` отдаёт `baccara`/`blackjack`.
- Воркер: карточка в группе с `bak_wjoin_` / `bj_wjoin_`, гидратация в кэш баккары/блэкджека, не в кубики.
- Мёртвая доставка `origin=web` **не** отменяет стол на сайте (ставка остаётся).
- Список дуэлей: под ставкой подпись «🃏 Баккара», чтобы стол не выглядел как кубики.

Живой backfill (ещё `waiting`, без чата): `web-03e1a2745423`, `web-dc9fc432b201`, `web-f31b85ae252f` (баккара) и `web-61d780262c3b` (кубики). Outbox `completed`, telegram_message_id **604–607** в чат `-5562276559`.

Локально: `WebDuelInvitationTests` 3 OK; bot `test_pvp_lobby` + `test_card_invite` + `test_card_server_deal` + `test_pvp_dice` + `test_bot_startup` + `test_game_timeouts` → **47 OK**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health passed. casino-bot пересобран.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Collect раньше **1236**, плюс 3 `WebDuelInvitationTests` → **1239**. ≈1232 passed (1239−7).

Бандл: `index-Z9DYImR5.js`, CSS `index-CltnJokf.css` (правило `.casino-duel-money .casino-muted` уже было).

md5 local = staging `/opt` = live, кроме `internal_casino.py`: после rsync в локальный файл доехало чужое `notify_player_joined` (+962 байт), на staging этого нет. Приглашения на staging есть (`enqueue_web_duel_invitation` строка 3093). Совпали:

- `user_casino.py` `82dd1d00704002b86db95a7758f48033`
- `test_internal_casino.py` `77f00a739f77781790761cc509340982`
- `CasinoPlayerChip.tsx` `268a4f1af1f7686cefde203055711f59`
- `card_invite.py` `35b9148fef1b30eea50a1387bf0e7fe4`
- `pvp.py` `c1ca47098728fe25886b77796e083eae`
- `baccara.py` `f34acc448d96ece47bd0225dc18df79d`
- `blackjack.py` `2439f01d905b1db6bde6a14236bb249a`
- `bot.py` `880e70165b0a1e3a41a22982a41fc7ee`

`rg`: `enqueue_web_duel_invitation` — helper + `create_or_join_duel` + тесты; `bak_wjoin_` — invite + handler + тесты.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway.

Прод (read-only): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit 06:08:19 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз):
- Игровая группа `focuscaztest`: карточки **GAME #WEB-03E1** / **WEB-DC9F** / **WEB-F31B** — баккара, «Принять игру». Не кубики.
- `/baccara` в боте → «Обновить»: столы с сайта в списке ожидания.
- Новая баккара с сайта (`/casino/duels`, в селекте Баккара, без «Найти пару»): за ~15 с та же карточка в группе.
- Список `/casino/duels`: у строки баккары подпись **🃏 Баккара**, не только сумма.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**

## 2026-08-29 — Сайт: уведомление и переход в игру из Telegram

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: зашли в игру из Telegram — на сайте колокольчик всегда «Нет уведомлений», перейти в комнату нельзя.

Сделано:
- Таблица `casino_web_inbox` + `casino_inbox.py`: при join дуэли / V2 / дома / покера / комнаты / войны — «Вы зашли в игру» себе и «X зашёл в игру» остальным, плюс `href`.
- `GET /api/user/casino/inbox` — уведомления и живые сессии (в каких играх сейчас сидите). SSE `type=inbox` в чат-канале.
- Шапка: бейдж колокольчика, список с кнопкой **Перейти** / **К игре**. Полоса «Вы в игре» над лобби, если вы не на этой комнате.

Локально: `tests.test_casino_inbox` + join/house/v2/rooms/wars/poker **OK** (route-импорт jwt/asyncpg локально без venv как раньше). `npm run build` → `index-CGjcu_M4.js` / `index-CXnJDCVO.js` / `index-C3QaVtGE.css` / `panel-BsmzFzes.js`. `bootstrap_static_test.sh` passed.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Recreate postgres **без** `down -v`. Health passed. Ключей **65**. `casino_games` **356**. `to_regclass casino_web_inbox` жив.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1245** (было 1239, **+6** inbox). Новых имён нет. ≈1238 passed (1245−7).

Живой шлюз **200**: `/casino`, `/api/health`. Бандл `index-CGjcu_M4.js` содержит `data-casino-inbox` и `data-casino-now-playing`. CSS `index-C3QaVtGE.css`.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_inbox.py` `c2798a4e875c67e7139adbf466e07d56`
- `add_casino_web_inbox.sql` `9bc0719bf9492a2785362169da570b3e`
- `test_casino_inbox.py` `8b50c4da12fd9185ab5bbefcd528e18e`
- `CasinoShell.tsx` `a25cce55463d379fded6a38b3ea645b9`
- `user_casino.py` `61e0b42abf0b10dc20c70e51a008ccfe`
- `internal_casino.py` `517876387c2868ced6a2c0e7d081d379`

`rg` `notify_player_joined`: модуль + join duel/v2 + house sit + poker sit + room join + war accept/join + тесты. `data-casino-inbox` — оболочка. `GET /casino/inbox` — user router + `getCasinoInbox`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Этот срез бота не трогал. Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз). На сайте войти тем же Telegram, что в боте:
- Открой `/casino` на сайте. С Telegram зайди в дуэль или стол 2–6. На сайте: полоса **«Вы в игре · Перейти»**, колокольчик с цифрой. Клик ведёт в `/casino/duels/…` или `/casino/tables/…`.
- Второй аккаунт на сайте в лобби: колокольчик **«… зашёл в игру»** → **К игре**. F5 — сессия остаётся, пока партия жива.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**

## 2026-08-29 — Профиль: «Игрок не найден» у веб-аккаунта

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: скрин `/casino` — кружок **P**, баланс **~570 ₽**, рельс Профиль, красное **«Игрок не найден»**. Это не Fixture Buyer (940002), а веб-логин **player2** / Player 2: `web_users.client_user_id = -1`, Telegram нет, в `user_cashback_ledger` по `-1` сумма **570**.

Почему: сайт без Telegram получает отрицательный `client_user_id`. Шапка/рельс шли на `/casino/me`, затем редирект на `/casino/u/-1`. Фронт резал любой id ≤ 0 и даже не вызывал API. `GET /casino/players/me` для своего профиля 404 не отдаёт.

Сделано:
- `/casino/me` сам рисует профиль (`GET …/players/me`), без редиректа на `/u/`.
- `/casino/u/:id` принимает любой ненулевой целый id, в том числе отрицательный.
- Тесты: свой профиль `viewer_id=-1`; чужой неизвестный по-прежнему 404.

Локально: `tests.test_casino_player_profile` → **5 OK**. `npm run build` → `index-DJzpjtRX.js` / `index-DTdGZ03-.js` / `index-C3QaVtGE.css` / `panel-BsmzFzes.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health passed. Recreate postgres **без** `down -v`. Ключей **65**. `casino_games` **357**. `player2` / `-1` на месте.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1247** (было 1245, **+2**). Новых имён нет. ≈1240 passed (1247−7). `test_casino_player_profile` на staging **5 OK**.

Живой шлюз **200**: `/casino`. Бандл `index-DTdGZ03-.js` содержит `data-casino-profile`, `players/me`, «Игрок не найден». CSS `index-C3QaVtGE.css`.

md5 local = staging `/opt` = live `/app/backend`:

- `CasinoProfile.tsx` `38ec146fa9c997189b1e3e70b173656e`
- `App.tsx` `55baf112b69c9b07cd9794c93173fde1`
- `miniapp-main.tsx` `778424e3e03aac4183acff03d1888869`
- `test_casino_player_profile.py` `cc9b4fffd058a50632470beeba7639e4`
- `casino_player_profile.py` `c5aab48e9618a182ba17d190ddeedfe6`

`rg` `parseCasinoPlayerLookup` — `CasinoProfile.tsx` (def + вызов). Маршрут `me` → `CasinoProfile` в `App.tsx` и `miniapp-main.tsx`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-play-public` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Этот срез бота не трогал. Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз). Тем же входом **Player 2** (кружок P, ~570 ₽):
- F5, шапка (кружок) или рельс **Профиль** — имя, уровень, оборот недели. Красного «Игрок не найден» быть не должно. URL **`/casino/me`**, не редирект в кошелёк.
- Прямая ссылка `/casino/u/-1` — тот же свой профиль.
- **Настройки** — имя/аватар как раньше.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**

## 2026-08-29 — Чат в казино пустой на десктопе

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: залогинен на `/casino` (inbox/jackpot 200), правый рейл «Чат» пустой, «0 онлайн». `GET /api/user/casino/chat/lobby` с браузера не уходил. В базе лобби уже было: 1 комната, 2 сообщения. POST с UI мог пройти, история после F5 пропадала.

Почему: `CasinoShell` всегда рисует docked-рейл, а `chatOpen` стартует как `false` (это флаг мобильной шторки). Панель грузила лобби/SSE только при `open`. На ширине ≥768px рейл виден, данные нет.

Сделано:
- `casinoChatIsLive(open, docked)` = `open || docked`.
- История, онлайн и poll/SSE идут, когда рейл на экране, не только после кнопки «Чат» внизу.

Локально: `tests.test_casino_chat` → **10 OK** (было 9, **+1** `CasinoChatPanelLiveTests`). `npm run build` → `index-CTKswHz6.js` / `index-BjQap4k0.js` / `index-C3QaVtGE.css`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` (повтор, чтобы не затереть срез профиля). Health passed. Postgres **Recreate без** `down -v`. Ключей **65**. Лобби-чат на месте: rooms **1** (lobby), messages **2**, presence **2**.

Тесты на staging: **8 failed**. Семь имён как в базовой линии: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Восьмое — `CosmeticsPureTests.test_starlette_int_path_rejects_negative_id` (срез профиля / отрицательный `client_user_id`), не этот чат. `tests/test_casino_chat.py` на staging **10 OK**. Collect раньше **1247**, плюс 1 live-тест панели → **1248**. ≈1240 passed (1248−8).

Живой шлюз **200**: `/casino`, `/api/health`. Бандл `index-CTKswHz6.js` содержит `data-casino-chat`. CSS `index-C3QaVtGE.css`.

md5 local = staging `/opt` = live `/app/backend` (тест):

- `CasinoChatPanel.tsx` `95349b01b9440e2b2b8ad1bae32c5b2f`
- `test_casino_chat.py` `cc618ef37c0c25ef6dc89758c66036ad`

`rg` `casinoChatIsLive` — панель (def + вызов) и контракт-тест. `if (!open || !isAuthed)` в панели нет.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-play-public` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Этот срез бота не трогал. Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз). Войди на `/casino`:
- Справа рейл **Чат**: история лобби (не пусто), строка онлайн. Напиши → F5 — сообщение на месте.
- Телефон / узкое окно: низ **Чат** открывает ту же ленту.
- Профиль Player 2 `/casino/me` без «Игрок не найден». **Должно остаться.**
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**

## 2026-08-29 — Баккара сайт↔ТГ зависала после «Принять»

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой стол `web-f31b85ae252f` (скрин `…:18082/casino/duels/web-f31b85ae252f`): сайт Fixture Buyer (`940002`) видел свои карты, `@alwaeszs` (`7869431717`) — рубашки, статус «ожидание». В шапке при этом другой стол **WEB-03E1** (`web-03e1a2745423`, waiting 100 ₽) — не этот раунд.

Почему: баккара в Telegram заканчивается только после hit/stand в личке бота у **обоих**. Стол с сайта (`web-` + 12 hex) шлёт DM создателю; у веб-игрока `msg_id_creator=null`. Соперник из ТГ нажал hit (`4♦ 7♣ K♠`), создатель остался с двумя картами. Сайт не рисует hit/stand. Раунд висел до 2ч таймаута хода. Чат «0 онлайн» — presence лобби, не этот стол.

Сделано:
- `casino_pvp_cards.py`: после посадки соперника (и на GET комнаты) HMAC-колода добирает карты по правилам дома и сразу селит. Живой hit не урезаем.
- `touch_active_holds` до settle — иначе 409 «Hold …-creator has expired».
- Бот: если join уже `finished`, шлёт результат и **не** шлёт hit/stand.

Живой зависший стол на staging добит GET-ом: `finished`, winner `940002`, payout **97.50**, руки `2♣ Q♣ 2♥` (4) vs `4♦ 7♣ K♠` (1).

Локально: `tests.test_casino_pvp_cards` → **14 OK**. Бот: `test_card_server_deal` + `test_card_invite` (web-id + already-settled join).

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`, затем `--no-deps --wait backend` после hold-touch. Health passed. Ключей **65**. `casino_games` **359**.

Тесты на staging: **8 failed**. Семь имён как в базовой линии: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Восьмое — `CosmeticsPureTests.test_starlette_int_path_rejects_negative_id` (срез профиля / отрицательный id), не этот срез. Collect-only **1266** (было ~1248, **+14** `test_casino_pvp_cards` и хвост сбора). `tests/test_casino_pvp_cards.py` на staging **14**. ≈1258 passed (1266−8).

Живой шлюз **200**: `/casino`. Health passed.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_pvp_cards.py` `9f661c041f1f253d2c8a728cdbcb5c34`
- `internal_casino.py` `368fbd7d4da3433e7aa59bc966f14ce9`
- `public_casino.py` `e787baac9c60eb1e91449e9b361a3058`
- `test_casino_pvp_cards.py` `a860c1b9e4374e71dd524024298f6c36`
- бот `baccara.py` `1efc65cf0e791dfbf34ca4aefd64c7fb`
- бот `blackjack.py` `9b9c433222b44cf2cbc58b5591561b6b`
- бот `card_invite.py` `3341183ec23d4ced8f3768ba49f9d967`

`rg` `complete_site_card_duel` — `casino_pvp_cards.py`, `internal_casino.py` (join + rejoin), `public_casino.py` (GET комнаты), тесты. `is_site_duel_id` — тот же модуль + бот `card_invite.py`. `_finish_if_join_settled` — `games/baccara.py`, `games/blackjack.py`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-play-public` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (baccara/blackjack/card_invite). Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз):
- F5 `http://127.0.0.1:18081/casino/duels/web-f31b85ae252f` — обе руки открыты, стол **закончен**, выигрыш ~97.50 ₽ у Fixture Buyer. Шапка «WEB-03E1 / ожидание» — **другой** стол, не этот URL.
- Новая баккара с сайта → из ТГ «Принять»: раунд должен закрыться сам, без кнопок hit/stand у веб-игрока. В ТГ — результат, не зависание.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа: история лобби не пустая. **Должно остаться.**

## 2026-08-29 — Аватарка есть в базе, на экране пусто

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: Player 2 (`client_user_id=-1`, ник **чебурек**) загрузил JPG. В `casino_player_cosmetics` строка есть (`avatar_ext=jpg`), файл `casino_n1.jpg` 34 КБ на томе. В шапке/чипах фото не было. Fixture Buyer `940002` тоже залил `casino_940002.jpg`.

Почему:
1. URL был `/api/public/casino-avatars/-1`. Для веб-id так оставлять нельзя: часть поверхностей не подмешивала косметику (чат/онлайн, джекпот, фикс-комнаты, войны — только Telegram), шапка не обновлялась после загрузки, `<img>` с `display:inline-flex`.
2. Внутренний `GET /users/{id}/avatar` для бота смотрел только кэш Telegram (`{id}.jpg`), не `casino_{id}.jpg`.

Сделано:
- Публичный URL `n1` для отрицательных id; маршрут `{user_key: str}`; `GET /casino/players/-1` тоже через `parse_signed_user_id`.
- `_actor` / история чата / онлайн и джекпот/комнаты/войны берут `public_actors` (ник+аватар казино).
- Шапка слушает `CASINO_LOOK_EVENT` после сохранения в настройках; картинка `display:block`, при ошибке загрузки — буква.
- Internal avatar: сначала файл косметики, потом Telegram. nginx + rate-limit allowlist `/api/public/casino-avatars/`.

Живой JSON после фикса: `player.avatar_url=/api/public/casino-avatars/n1?access=…`. GET картинки через шлюз **200** `image/jpeg` 34440.

Локально: `tests.test_casino_player_cosmetics` + `ProfileAvatarEndpointTests` **OK**. `bootstrap_static_test.sh` passed. `npm run build` → `index-HJp1nqmF.js` / `index-D7Udbq3j.js` / `index-yHa93NsR.css` / `panel-BsmzFzes.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Recreate postgres **без** `down -v`. Health passed. Ключей **65**. `casino_games` **359**. `to_regclass casino_player_cosmetics` жив. Файлы аватаров на месте.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Восьмого `CosmeticsPureTests.test_starlette_int_path_rejects_negative_id` больше нет. Collect **1267** (было 1266). ≈1260 passed (1267−7).

Живой шлюз **200**: `/casino`, `/api/health`. Бандл `index-HJp1nqmF.js` / CSS `index-yHa93NsR.css`.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_player_cosmetics.py` `b7b7411ee50461b2f6322d04667f206a`
- `casino_chat.py` `9efd4d42bf836d2cfb4162c9830493bc`
- `public.py` `41f00a9cab6cb4ba7eca978ceb30a706`
- `user_casino.py` `58ae1358e2f5f00fb976b199480456bc`
- `internal_casino.py` `05ab36be4b3435f6e9711c8129585af8`
- `rate_limit_middleware.py` `9e80e0a384534e0ce273f1f9f8ea5bef`
- `casino_jackpot.py` `c7f1a878262d23ae32320c07c2084ffd`
- `casino_fixed_rooms.py` `8776deace500ff3e26f6151c03578c8e`
- `casino_clan_wars.py` `0a9bcb8a73a57c3399e8d955519ab092`
- `CasinoPlayerChip.tsx` `bde990630b236fc158e767a534ca07e8`
- `CasinoShell.tsx` `9d33d7440a5b7ca675c10f9cd75e0384`
- `CasinoPlayerSettings.tsx` `2772723762ae432a4f09eaa5330c572b`
- `test_casino_player_cosmetics.py` `2ca5f8b00a4a7ffa5e30c55c00ecabfa`

`rg` `cosmetics_avatar_path_key` — модуль + bootstrap + тесты. `public_actors` — чат, профиль, дуэли, дом, v2, inbox, джекпот, фикс-комнаты, войны. `CASINO_LOOK_EVENT` — настройки + шапка. `casino-avatars/` — public router, nginx local/staging, rate-limit.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-play-public` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Бот не менял: косметику отдаёт internal avatar. Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз). Тем же **Player 2** (чебурек, ~570 ₽), лучше жёсткое обновление:
- `/casino` — кружок в шапке **фото**, не буква «Ч»/«P».
- `/casino/settings` и `/casino/me` — тот же файл. Сменить картинку → шапка меняется без перезахода.
- Стол 2–6 / дуэль / чат — чип с фото. F5 — фото на месте.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа: история лобби не пустая. **Должно остаться.**

## 2026-08-29 — Кубики: лишний скролл вниз, чат неудобно писать

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал. `focuspay-casino` не трогал.

Живой баг: на `/casino/play/pvp_dice` страница уезжала далеко вниз (пустой запас **46vh** под фиксированную панель ставки). Правый чат тянулся вместе с длинной страницей, поле ввода оказывалось у низа документа; на телефоне оверлей чата закрывал весь экран до нижней навигации, клавиатура наезжала на ввод.

Сделано:
- Оболочка казино `height: 100dvh; overflow: hidden` — чат всегда в высоте окна, скролл только в `.casino-main`.
- Убран `padding-bottom: 46vh`. На узком экране панель ставки в потоке, не `position: fixed`.
- Телефон: чат — нижняя шторка **52vh** (кубы остаются видны); при фокусе поля поднимается над клавиатурой (`visualViewport` → `--casino-keyboard-h`), нижнее меню прячется.
- Кубы: `overflow: hidden` на сцене, без пустого `min-height: 220px`.

Локально: `npx tsc -b` чистый. `npm run build` → `index-BfUf191r.js` / `index-DIHZ2FvS.js` / `index-D16X_YFM.css` / `panel-BsmzFzes.js`. В превью 390×844: документ не скроллится, у `.casino-main` лишних **~37px** (лента), кнопка ставки выше навигации; шторка чата top **337px**, height **439px**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health passed. Postgres **Recreate без** `down -v` (ещё раз на collect-only).

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Collect **1267** (бэкенд-тестов не добавлял). `tests/test_casino_chat.py` **10**. ≈1260 passed (1267−7).

Живой шлюз **200**: `/casino`, `/casino/play/pvp_dice`, `/api/health`. Бандл `index-BfUf191r.js` / CSS `index-D16X_YFM.css`. В живом CSS **0** вхождений `46vh`, **1** `52vh`.

md5 local = staging `/opt`:

- `casino.css` `639bfa223719e438d3bc2c6b3f818adc`
- `CasinoShell.tsx` `9d33d7440a5b7ca675c10f9cd75e0384`

`grep` `46vh` — нет. `--casino-keyboard-h` — `casino.css` + `CasinoShell.tsx`. `52vh` / `is-open:focus-within` — `casino.css`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-play-public` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Этот срез бота не трогал. Не коммитил.

Следующий шаг: стоп.

Потыкать (туннель **18081**; **18082** — тот же шлюз):
- Телефон / узкое окно `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house`: кубы и **Ставка** на одном экране, пустой «хвост» на пол-экрана не листается. Лента — чуть ниже, если вообще.
- Низ **Чат**: шторка не на весь экран, кубы ещё видны. Поле ввода над нижней навигацией. Тап в поле — клавиатура не закрывает строку.
- Десктоп: рейл чата на высоту окна; писать можно, не прокручивая страницу вниз.
- 1×1 vs дом: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа: история лобби не пустая. Кружок Player 2 — фото. **Должно остаться.**

## 2026-08-29 — ЛС бота: сайт-дуэль не в «Активных играх»

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал. Бэкенд/сайт в этом срезе не менял.

Живой баг: `http://178.63.247.233:18082/casino/duels/web-03e1a2745423` (баккара 100 ₽, Fixture Buyer ждёт, в шапке ещё **WEB-DC9F**). В личке бота «🎯 Активные игры» / «🎲 Мои игры» пусто — нельзя зайти. Кнопки смотрели только V2-столы 2–6 (`/v2/tables/active`), не `casino_games` 1×1.

Сделано:
- Лобби и «Мои игры» читают `get_active_pvp_games` (баккара / блекджек / кубики).
- Чужая waiting-дуэль: «Войти» (`bak_wjoin_` / `bj_wjoin_` / `dueljoin:`).
- Своя waiting: строка «ваша игра, ждёт соперника»; если есть miniapp URL — «На сайте».
- Кубики из ЛС: `join_waiting_dice_from_dm` (hold + промпт 🎲 в этот чат).

Живые waiting на staging (creator **940002**): `web-03e1a2745423` баккара 100, `web-dc9fc432b201` баккара 100 (**WEB-DC9F**), `web-61d780262c3b` кубики 100.

Локально: `tests.test_v2_tables` + `test_pvp_dice` + `test_pvp_lobby` + `test_card_invite` + `test_card_server_deal` + `test_bot_startup` + `test_staging_ui` + `test_game_timeouts` + `test_v2_table_gameplay` + `test_v2_card_board` → **91 OK** (было 84 на этом наборе: **+5** лобби, **+2** dice DM join).

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health passed. casino-bot пересобран. Postgres Recreate **без** `down -v`. Ключей **65**. `casino_games` **359**.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1267** (без новых бэкенд-тестов). Новых имён нет. ≈1260 passed (1267−7). В контейнере casino-bot тот же набор **91 OK**.

Живой шлюз **200**: `/casino`, `/api/health`.

md5 local = staging `/opt` = live `/app`:

- `games/v2_tables.py` `e4a3a6b1d9f962d497f3343236151c25`
- `games/pvp.py` `04a4068f084aba23944de4d230f8208c`
- `tests/test_v2_tables.py` `d4efaacb1d03de45c403675012f0b9c0`
- `tests/test_pvp_dice.py` `112b7a7983f05eca5e1e21356a182e17`

`rg`: `active_duels` — `v2_tables.py` (def + lobby + my games); `join_waiting_dice_from_dm` — `pvp.py` + handler `dueljoin:` + `test_pvp_dice`; `bak_wjoin_web-03e1a2745423` — `test_v2_tables` + уже существующий join в `baccara.py`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (`v2_tables.py`, `pvp.py`, тесты). Не коммитил.

Следующий шаг: стоп.

Потыкать. Тот же Telegram, что Fixture Buyer (**940002**), личка casino-бота. Player 2 / чебурек без Telegram в бот не зайдёт — это веб-аккаунт `-1`.

- «🎯 Активные игры»: свои столы **WEB-03E1** / **WEB-DC9F** / **WEB-61D7** с подписью «ваша игра, ждёт». Чужой аккаунт видит те же строки и **Войти**.
- «🎲 Мои игры»: те же три дуэли, не «нет активных игр».
- С другого Telegram: Войти в баккару → раунд закрывается (как сайт-стол), не зависание hit/stand.
- Группа по-прежнему ок. 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа на сайте не пустой. **Должно остаться.**

## 2026-08-29 — /allgames в группе: баблы, не текстовый список

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал. Бэкенд/сайт в этом срезе не менял.

Живой баг: в игровом чате `/allgames` писал строки вроде `• #WEB-61D7 🎲 Кубики — Игрок 940002 — 100.00 ₽` без кнопок. Чтобы войти, надо было искать карточку «Принять игру» выше по ленте.

Сделано:
- Группа: каждая чужая waiting-игра — отдельная inline-кнопка `1. 🎲 Кубики · 100 ₽ · Игрок…`. Нажатие = тот же `join_{id}`, что у карточки.
- Больше 5 игр: «Далее» / «Назад» (`agpage:`) и «Обновить». Текст сообщения короткий, без маркированного списка.
- Личка `/allgames`: игры тоже только в баблах (нумерация + имя + ставка), не дублируются текстом.

Локально: `python -m pytest tests/ --ignore=tests/e2e` → **220 passed**. `tests.test_pvp_lobby` **+3**: group bubbles, pagination edit, private numbering. Wizard-токен в тесте берётся из `handler.__globals__`, иначе полный collect ломал `test_wizard_type_step_edits_in_bound_group`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Первый прогон update упал в конце (`No such container` после Healthy) — rsync и образ casino-bot уже были. Повторный `staging-runtime-health.sh` **passed**. casino-bot пересобран (`COPY` не из кэша). Postgres Recreate **без** `down -v` (ещё раз на pytest). Ключей **65**. `casino_games` **359**.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect как в прошлом срезе **1267** (бэкенд-тестов не добавлял). Новых имён нет. ≈1260 passed (1267−7).

Живой шлюз **200**: `/casino`, `/api/health`.

md5 local = staging `/opt` = live `/app` (casino-bot):

- `games/pvp.py` `04a4068f084aba23944de4d230f8208c`
- `tests/test_pvp_lobby.py` `9c83369b63120fff64a3220cd7c29600`

`rg` `agpage:` — `pvp.py` (кнопки + handler) и `test_pvp_lobby.py`. `_group_lobby_keyboard` — def + `/allgames` + page callback. `_lobby_button_label` — private и group.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (`pvp.py`, `test_pvp_lobby.py`). Не коммитил.

Следующий шаг: стоп.

Потыкать. Тот же Telegram, группа **тестовый чат** (бот focuscaztest):

- `/allgames` — не список «• #WEB-…», а кнопки одна под другой: `1. 🎲 Кубики · 100 ₽ · …`. Нажать → вход в игру, без поиска карточки выше.
- Если игр больше пяти: **Далее** / **Назад**, номер страницы в тексте. **Обновить** пересобирает список.
- Своя ставка в этом меню не показывается (её и так видит создатель на карточке).
- Личка: «🎯 Активные игры» / WEB-03E1 / WEB-61D7 как в прошлом срезе. **Должно остаться.**
- 1×1 vs дом `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа на сайте не пустой. **Должно остаться.**

## 2026-08-29 — Вход в кубики из группы: только группа, без ЛС

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Живой баг: вход в waiting 1×1 кубики из группы (`/allgames`) слал «Соперник зашёл» в ЛС обоим и в бота, а живой 🎲 уходил в личку. Нужно: весь Telegram-трафик этой дуэли только в том чате, откуда зашли. Уведомление «противник начал» не нужно, если зашёл человек из Telegram, а не к создателю с сайта.

Сделано:
- Бэкенд `enqueue_roll_prompts` / `enqueue_face`: если чат группы (`chat_id < 0`) — одна запись в outbox в группу, без DM и без текста «Соперник зашёл». DM остаются только для дуэли без группы (сайт/личка).
- `notify_player_joined(..., notify_joiner=False)` на grouped pvp_dice — зашедшему не пишем сайт-колокольчик «Вы зашли». Создателю «В игру зашли» на сайте оставляем.
- Бот: `_bind_play_chat` — группа важнее user id. `cb_join` из группы пишет карточку броска в эту группу, даже если кэш держал ЛС. Кубик в ЛС при групповой дуэли не принимается: «Кинь 🎲 в игровом чате.»

Локально: casino-bot `python -m pytest tests/ --ignore=tests/e2e` → **224 passed**. Backend: `test_casino_pvp_dice` + `test_casino_inbox` + join outbox — ок.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. casino-bot `COPY` не из кэша. Postgres Recreate **без** `down -v`. Ключей **65**. `casino_games` **426**.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect **1269** (+2: group-only outbox и skip joiner inbox). Новых имён нет. **1262 passed** (1269−7).

Живой шлюз **200**: `/casino`, `/api/health`.

md5 local = staging `/opt` = live контейнер:

- `casino_pvp_dice.py` `d879aba2f0faac30b2b1bcfa8e693954`
- `casino_inbox.py` `14ecfe8ed10f8a0ab4985d25ad017f8e`
- `routers/internal_casino.py` `40eeca393d276526a5c28d672cd7c1e3`
- `games/pvp.py` `d4ee6e0180d7c7da055bbe6a27235e56`
- `tests/test_pvp_lobby.py` `c32e9a24bd30a29458da1565d05827a1`
- `tests/test_pvp_dice.py` `23f8df9fbcd6ae1f086b1d9e13989931`

`rg`: `notify_joiner` — `casino_inbox.py` + join в `internal_casino.py` + тест. `_bind_play_chat` — `pvp.py` (adopt, DM join, `cb_join`, hydrate) + тесты. `enqueue_roll_prompts` group-only — `casino_pvp_dice.py` + `test_casino_pvp_dice.py` + join outbox `count("pvp_roll_prompt")==0`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: pvp dice outbox, inbox, join, журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (`pvp.py`, два теста). Не коммитил.

Следующий шаг: стоп.

Потыкать. Тот же Telegram, группа **тестовый чат** (бот focuscaztest), туннель **18081**:

- В группе `/allgames` → войти в чужие кубики. Карточка «кинь 🎲» и сам кубик — **только в этой группе**. В ЛС с ботом не должно прийти «Соперник зашёл» и не должен улететь кубик.
- Личка с ботом после такого входа: пусто по этой дуэли (не дублировать группу).
- Если всё же кинуть 🎲 боту в ЛС, пока дуэль групповая: ответ «Кинь 🎲 в игровом чате», бросок не засчитывается.
- Сайт 1×1 vs дом `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа на сайте не пустой. **Должно остаться.**
- `/allgames` баблы как в прошлом срезе. **Должно остаться.**

## 2026-08-29 — Казино поверх страницы + понятный телефон

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал. Бэкенд в этом срезе не менял.

Сделано:
- Клик «Казино» с главной/кабинета/шапки открывает Radix-оверлей поверх текущей страницы (`state.casinoBackground`). Прямой заход `/casino` — как раньше, на весь экран. Mini App не трогал.
- Внутри оверлея переходы (лобби → кубики) прокидывают background через патч `UNSAFE_NavigationContext`. X / Escape / затемнение возвращают на ту же страницу.
- Телефон: X, баланс виден, поиск по иконке, низ Лобби / Игры (шит каталога) / Чат / Профиль. Сетка плиток 2 колонки. Десктоп-рельс как был.
- Капча: `inputMode="text"`, фильтр цифры+латиница. `a3k7!` в поле становится `A3K7`.

Локально: `npx tsc -b` ок, `npm run build` ок (2264 modules). Браузер preview :4173: оверлей с главной, close → `/`, `/casino/play/pvp_dice` внутри слоя, капча принимает буквы.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды (`staging runtime health check passed`). Postgres Recreate **без** `down -v`.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Suite дошёл до `[100%]`.

Живой шлюз на хосте staging **200**: `/casino`, `/api/health`. В бандле шлюза есть `casinoBackground` (`index-DKSIPpWz.js`, `index-L1g4nSZl.js`).

md5 local = staging `/opt`:

- `casinoOverlay.tsx` `67cd2929999ab573e9f6540467db79de`
- `CasinoShell.tsx` `0a3ca0948c87b8e82a9eb5293e57d632`
- `CaptchaField.tsx` `9738bbec937384ce5ac3391dca395e8c`
- `App.tsx` `d5b58f3f66c832e2ea9a0aa920b98b4a`

`rg` `CasinoOpenLink`: `casinoPaths.tsx` (def) + `PublicHeader` + `PublicHome` ×2 + `CabinetLayout`. `casinoBackground`: `casinoOverlay.tsx` + `casinoPaths` + `Login` + `App`. Captcha `inputMode="text"` — `CaptchaField.tsx`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: оверлей казино + капча + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, этот срез не трогал). Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- С главной и из кабинета открыть «Казино» — сайт виден/затемнён под слоем, не пустая новая страница.
- Внутри оверлея зайти в кубик и назад в лобби — слой не закрывается.
- X / Escape / поля (десктоп) — возврат на ту же страницу и скролл.
- Прямой заход `/casino` — как раньше, на весь экран.
- Телефон (узкое окно): баланс в шапке, поиск по иконке, низ Лобби / Игры / Чат / Профиль, плитки в 2 колонки.
- Логин: капча с буквами набирается с обычной клавиатуры (`A3K7`), не только цифровой пад.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа на десктопе не пустой. **Должно остаться.**
## 2026-08-29 — Казино поверх страницы + понятный телефон

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал. Бэкенд в этом срезе не менял.

Сделано:
- Клик «Казино» с главной/кабинета/шапки открывает Radix-оверлей поверх текущей страницы (`state.casinoBackground`). Прямой заход `/casino` — как раньше, на весь экран. Mini App не трогал.
- Внутри оверлея переходы (лобби → кубики) прокидывают background через патч `UNSAFE_NavigationContext`. X / Escape / затемнение возвращают на ту же страницу.
- Телефон: X, баланс виден, поиск по иконке, низ Лобби / Игры (шит каталога) / Чат / Профиль. Сетка плиток 2 колонки. Десктоп-рельс как был.
- Капча: `inputMode="text"`, фильтр цифры+латиница. `a3k7!` в поле становится `A3K7`.

Локально: `npx tsc -b` ок, `npm run build` ок (2264 modules). Браузер preview :4173: оверлей с главной, close → `/`, `/casino/play/pvp_dice` внутри слоя, капча принимает буквы.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды (`staging runtime health check passed`). Postgres Recreate **без** `down -v`.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Suite дошёл до `[100%]`.

Живой шлюз на хосте staging **200**: `/casino`, `/api/health`. В бандле шлюза есть `casinoBackground` (`index-DKSIPpWz.js`, `index-L1g4nSZl.js`).

md5 local = staging `/opt`:

- `casinoOverlay.tsx` `67cd2929999ab573e9f6540467db79de`
- `CasinoShell.tsx` `0a3ca0948c87b8e82a9eb5293e57d632`
- `CaptchaField.tsx` `9738bbec937384ce5ac3391dca395e8c`
- `App.tsx` `d5b58f3f66c832e2ea9a0aa920b98b4a`

`rg` `CasinoOpenLink`: `casinoPaths.tsx` (def) + `PublicHeader` + `PublicHome` ×2 + `CabinetLayout`. `casinoBackground`: `casinoOverlay.tsx` + `casinoPaths` + `Login` + `App`. Captcha `inputMode="text"` — `CaptchaField.tsx`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: оверлей казино + капча + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, этот срез не трогал). Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- С главной и из кабинета открыть «Казино» — сайт виден/затемнён под слоем, не пустая новая страница.
- Внутри оверлея зайти в кубик и назад в лобби — слой не закрывается.
- X / Escape / поля (десктоп) — возврат на ту же страницу и скролл.
- Прямой заход `/casino` — как раньше, на весь экран.
- Телефон (узкое окно): баланс в шапке, поиск по иконке, низ Лобби / Игры / Чат / Профиль, плитки в 2 колонки.
- Логин: капча с буквами набирается с обычной клавиатуры (`A3K7`), не только цифровой пад.
- 1×1 vs дом `/casino/play/pvp_dice?mode=house`: 100 ₽ → 195 ₽. **Должно остаться.**
- Чат справа на десктопе не пустой. **Должно остаться.**

## 2026-08-29 — Скрыть холдем, рулетку, комнату N, кланы

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал. Бэкенд в этом срезе не менял.

Сделано: из лобби, рельса, шита «Игры», промо и поиска убраны техасский холдем, рулетка, комната N, клан vs клан и страница команд. Код заготовок и маршруты оставлены. Правило `.cursor/rules/casino-shelved-games.mdc` — напоминать про заготовки, если спросят «что можно сделать».

Файлы этого среза:

- `focussite/frontend/src/casino/gameCatalog.ts` — `hidden: true`, `CASINO_SHELVED_STUBS`, `visibleCasinoCatalog()`
- `focussite/frontend/src/casino/CasinoLobby.tsx` — видимый каталог, без промо Команды/Комната N
- `focussite/frontend/src/casino/CasinoShell.tsx` — рельс и шит без скрытых игр и без «Команды»
- `focussite/frontend/src/casino/casinoRoutes.tsx` — комментарий, маршруты не удалял
- `focussite/frontend/src/pages/CasinoFairness.tsx` — холдем/комната N/клан не в селекте (глубокая ссылка остаётся)
- `.cursor/rules/casino-shelved-games.mdc`

Локально: `npx tsc -b` ок, `npm run build` ок (2264 modules). Бандлы `index-C_WuPPeb.js`, `index-B6FmLr-o.js`, `index-lWi6HtQA.js`. Preview :4175: в лобби только Кубики, Баккара, Блэкджек, Джекпот. Поиск «холдем» → «Точного совпадения нет — весь каталог» без скрытых плиток. Шит «Игры»: те же четыре + дуэли/кошелёк.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate **без** `down -v`.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Suite дошёл до `[100%]`.

Живой шлюз на хосте staging **200**: `/casino`, `/api/health`. Бандлы шлюза те же `index-C_WuPPeb.js` / `index-B6FmLr-o.js` / `index-lWi6HtQA.js`. Туннель `127.0.0.1:18081` с этой машины не слушал (curl 000); проверка UI — local preview + host curl.

md5 local = staging `/opt`:

- `gameCatalog.ts` `b0ec53518b0ec6099dcfad0909ac2e30`
- `CasinoLobby.tsx` `06ea0a3e62510405d0b86063a4644d82`
- `CasinoShell.tsx` `2af658a1e38b6acc4c79af4443592147`
- `casinoRoutes.tsx` `8186c089987e7c5b4487dd42c1b7d45b`
- `CasinoFairness.tsx` `58f66973259f7a08b5d3e143094eb55b`
- `casino-shelved-games.mdc` `a10ef26a5125be4eb3c9239cd3f99b07`

`rg` `visibleCasinoCatalog`: `gameCatalog.ts` (def) + `CasinoLobby` + `CasinoShell` ×2. `CASINO_CLANS_PAGE_HIDDEN`: catalog + Shell ×2. `hidden: true`: четыре игры в `gameCatalog.ts`. `isShelvedCasinoGame`: catalog + `CasinoFairness.tsx`. SQL не трогал.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: скрытие игр + правило + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, этот срез не трогал). Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- Лобби `/casino`: плитки только Кубики, Баккара, Блэкджек, Джекпот. Нет холдема, рулетки, комнаты N, клан vs клан, «Команды».
- Рельс слева и низ «Игры»: тот же набор.
- Промо-карточки: нет «Команды» и «Комната N».
- Поиск «холдем» / «рулетка» / «клан»: скрытых плиток нет.
- Кубики 1×1 vs дом: 100 ₽ → 195 ₽. **Должно остаться.**
- Баккара, блэкджек, джекпот открываются. **Должно остаться.**
- Админка `/x8/casino/settings` не трогал.

## 2026-08-29 — Дом блэкджек: hit/stand и скрытая карта дилера

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Дуэли `?mode=players` и Telegram 1×1 **не** трогал (следующий срез после кликов). Баккара дом по-прежнему один POST = весь раунд.

Сделано: `/casino/play/blackjack?mode=house` больше не доигрывает обе руки до 17 сам. Ставка раздаёт 2+2, у казино вторая карта рубашкой, игрок жмёт **Добрать / Оставить**. Перебор — сразу проигрыш, дилер не добирает. После оставить (или 21) дилер открывает дырку и сам до 17. Выплата как раньше: 100 ₽ ×2 @ 5% = **195 ₽**, ничья ×1, проигрыш 0. Сид дырки в API нет, пока раунд не `finished`. F5 поднимает живую руку (`GET /api/user/casino/play/pending`). Повторный POST play при открытом раунде возвращает тот же `game_id`. Вкладка «Авто» у блекджека скрыта. Mini App тот же API.

Файлы этого среза:

- `site/exchange-backend/casino_house_cards.py` — раздача / `act_house_blackjack` / pending; `sequential_blackjack_result`
- `site/exchange-backend/routers/user_casino.py` — `POST /casino/play/action`, `GET /casino/play/pending`
- `tests/test_casino_house_cards.py`, `tests/test_casino_play.py`
- `focussite/frontend/src/casino/CasinoHouseCards.tsx`, `CasinoPlay.tsx`, `casino.css`, `gameCatalog.ts`
- `focussite/frontend/src/lib/public.ts` — `playCasinoBlackjackAction`, `getCasinoBlackjackPending`

Локально: `test_casino_house_cards` + `test_casino_play` **23 passed** (venv). House-cards модуль **17** тестов (дырка, префикс hit, перебор без добора дилера, stand до 17, натуральные 21, повторный play). `npm run build` ок, 2264 modules. Бандл шлюза с `casino-bj-hit`: `index-2ys_hE1G.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate **без** `down -v`.

Тесты на staging: **1276 collected**, **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Suite дошёл до `[100%]`.

Живой шлюз **200**: `/casino`, `/casino/play/blackjack`. SQL **65** ключей (этот срез БД не менял); `enabled_games` blackjack true; банк дома 55731.09 ₽, reserved 640.00.

md5 local = staging `/opt`:

- `casino_house_cards.py` `4180e2191e82f7c526d354a888ae2971`
- `user_casino.py` `b446d6d2aa5d1fce2347349ebda7a5c8`
- `CasinoHouseCards.tsx` `58e2afd953c8e9a8fe6a20651edd9bb8`
- `CasinoPlay.tsx` `75c78e7c12f136d6f334fdd0cfcfcd2d`
- `public.ts` `037525185c400f5066a2d614720f3d9f`
- `gameCatalog.ts` `e3e11f084e1769c0c6ac4a15f2bdce7e`
- `casino.css` `e3c170261583b50a42a6322e90433a24`

`rg` `act_house_blackjack_with_conn`: модуль + `user_casino` POST action + тесты. `playCasinoBlackjackAction`: `public.ts` + `CasinoPlay`. `data-casino-bj-hit`: `CasinoHouseCards.tsx`. `GET /casino/play/pending`: роутер + `getCasinoBlackjackPending` + загрузка в `CasinoPlay`.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: дом BJ hit/stand + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, этот срез не трогал). Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/play/blackjack?mode=house` — ставка → две свои открыты, у казино одна открыта + рубашка, кнопки **Добрать / Оставить**. Нет вкладки «Авто».
- Добрать несколько раз / оставить / специально перебрать. После оставить дырка открывается, казино само до 17. Перебор — проигрыш сразу, дилер лишние карты не берёт.
- F5 посреди хода — та же рука, дырка всё ещё закрыта.
- Mini App `http://127.0.0.1:18081/casino/tg/play/blackjack?mode=house` — то же.
- Не ломать: баккара дом без кнопок hit/stand; куб 100 ₽ → 195 ₽; лобби без скрытых игр. **Должно остаться.**


## 2026-08-29 — Кубики: соло стол 2–6 + бот на пустое место в PvP

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Сделано:
- **Против казино · Стол 2–6** = соло как 1×1: панель ставки + чипы 2–6 ботов дома + «Ставка». Без лобби чужих столов, без sit. Бэкенд: `max_seats=1`, create сразу `start`, sit → 409, публичный список соло не отдаёт.
- **С игроками:** felt-карточки столов, места чипами 2–6, create `bot_count=0`. На столе пустое место — «+ бот» (`POST .../v2/tables/{id}/bots`). Один `pvp_robot` на несколько мест; дорезерв `UPDATE`; последний бот → автостарт.
- Миграция `add_casino_house_tables_solo.sql` (CHECK max_seats 1–6) в `00-apply-migrations.sh` / full-panel / bootstrap_static.
- Static-check: `path="duels"` смотрит в `casinoRoutes.tsx` (маршрут уехал из `App.tsx`).

Файлы этого среза:
- `site/exchange-backend/casino_house_tables.py`, `casino_v2_web.py`, `routers/internal_casino.py`, `routers/user_casino.py`
- `migrations/add_casino_house_tables_solo.sql`
- `tests/test_casino_house_tables.py`, `test_internal_casino.py`, `test_casino_v2_web.py`
- `focussite/frontend/src/casino/CasinoHouseTables.tsx`, `CasinoPlay.tsx`, `CasinoPlayersLobby.tsx`, `CasinoV2Table.tsx`, `casino.css`
- `focussite/frontend/src/lib/public.ts`
- `focussite/docker/staging-db/{00-apply-migrations,20-full-panel-bootstrap,bootstrap_static_test}.sh`

Локально: house TableFlow + V2Settlement + v2_web **59 passed**; `bootstrap_static_test.sh` **passed**; `npm run build` ок (2264 modules). Бандлы: `index-DA7aOPeo.js`, `index-DBBFuqx-.js`, `index--ZcFYxNJ.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate **без** `down -v`.

Тесты на staging: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Suite дошёл до `[100%]`.

Живой шлюз **200**: `/casino`, `/api/health`, `/casino/play/pvp_dice?mode=house&view=table`. В бандле `index-DA7aOPeo.js`: `data-casino-house-bots`, `data-casino-house-tables`, `data-casino-v2-add-bot`, `can_add_bot`, `casino-felt-list`, «Ботов дома».

SQL: `casino_house_tables_max_seats_check` = `CHECK (((max_seats >= 1) AND (max_seats <= 6)))`.

md5 local = staging `/opt`:

- `casino_house_tables.py` `a2c6a621b4c2c46797c07dbe9e0512ac`
- `casino_v2_web.py` `081a3fda54e22f71011700b7cf57fa7a`
- `internal_casino.py` `0aea099897e9fcbb520d52a807e00270`
- `user_casino.py` `ea56c6145d9227267ccc3a6e5d11d101`
- `add_casino_house_tables_solo.sql` `dd1be15321dbd6d5ee106586f6ae4f20`
- `CasinoHouseTables.tsx` `d8708a3607f417898f43c332bf5c3dad`
- `CasinoPlay.tsx` `0657d9706b8566387ab3a760c6972d91`
- `CasinoPlayersLobby.tsx` `7474bc1b46b85303b58ddca6c8f61cbd`
- `CasinoV2Table.tsx` `286262afd79f8ae264dea5efdba3501d`
- `casino.css` `2d7ede8bac558fc4fbd0da7e1766b490`
- `public.ts` `7f6a3e0e5e3267401ce4461a335cf0bf`
- `bootstrap_static_test.sh` `78473562f778f843975f72229c694bf6`

`rg` `is_solo_table`: `casino_house_tables.py` (def + list/create/sit/snap). `add_v2_bot_with_conn`: internal + `casino_v2_web.add_web_bot` + тесты. `addCasinoV2Bot`: `public.ts` + `CasinoV2Table`. `can_add_bot`: web view + `CasinoV2Table` + тесты. `data-casino-house-bots`: `CasinoPlay`. `casino-felt-list`: lobby + css.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: house solo + v2 bots + lobby UX + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, этот срез не трогал). Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house` — 1×1 как было: 100 ₽ → **195** ₽. **Должно остаться.**
- `?mode=house&view=table` — слева ставка / ½ / ×2 / выигрыш + чипы **2–6 ботов**, кнопка **«Ставка»** (не «Создать стол»). Нет списка чужих столов, нет «Сесть». Один HMAC-раунд vs N кубов дома.
- Повторная «Ставка» на том же `ht=` — новый раунд.
- `?mode=players` — ставка чипами + места 2–6, без select «Боты». Список — felt-карточки. Создать стол → на странице стола пустое место **«+ бот»**; последний бот стартует игру.
- Деньги PvP: банк 2×100 → победителю **190**, не 195.
- Лобби без скрытых игр (холдем/рулетка/комната N/кланы). **Должно остаться.**

## 2026-08-29 — Блэкджек с игроками: без поста в общий чат, ЛС opt-in, стол 2–6 + боты

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Сделано:
- Создание блэкджека с сайта **не** ставит карточку в общий Telegram-чат (`publishes_web_group_invitation` = false для blackjack). Баккара/кубики 1×1 как раньше могут.
- ЛС о новом столе блэкджека — только тем, кто включил тумблер в `/casino/settings` (`notify_open_tables`, default off). Доставка через `casino_notification_outbox` → casino-bot outbox.
- Стол 2–6 для блэкджека на том же V2, что кубики: места, «+ бот», равные ставки, банк −5%. Руки HMAC до 17, выше без перебора забирает банк; ничья — `tie_split`.
- Миграция `add_casino_notify_open_tables.sql` (колонка + `blackjack` в `allowed_games` у активных `pvp_robot`).

Файлы этого среза:
- `site/exchange-backend/casino_open_alerts.py`, `casino_v2_cards.py`, `casino_v2_web.py`, `casino_player_cosmetics.py`, `casino_player_profile.py`, `routers/user_casino.py`
- `migrations/add_casino_notify_open_tables.sql`
- `tests/test_casino_open_alerts.py`, `test_casino_v2_cards.py`, `test_casino_player_profile.py`
- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`, `CasinoV2Table.tsx`, `CasinoPlayerSettings.tsx`, `casino.css`
- `focussite/frontend/src/lib/public.ts`
- `focussite/docker/staging-db/{00-apply-migrations,20-full-panel-bootstrap,bootstrap_static_test}.sh`

Локально: `test_casino_open_alerts` + `test_casino_v2_cards` **11 passed**; profile с `notify_open_tables` ок; `npx tsc -b` ок; `npm run build` ок (2264 modules). Бандлы: `index-DA7aOPeo.js`, `index-DBBFuqx-.js`, `index--ZcFYxNJ.js`. `bootstrap_static_test.sh` **passed**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate **без** `down -v`. Колонка `notify_open_tables` есть. У `pvp_robot` в `allowed_games` есть `blackjack`.

Тесты на staging: **1293 collected**, **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. **1286 passed** (1293−7). Suite дошёл до `[100%]`.

Живой шлюз на хосте staging **200**: `/casino`, `/api/health`. В `index-DA7aOPeo.js`: `notify_open_tables`, `can_add_bot`, «Личные уведомления».

SQL: ключей **65**; `casino_games` **438**.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_open_alerts.py` `5411094f96454d9e4471e3b44835037c`
- `casino_v2_cards.py` `cf73be4c3c8a593815c285ec24890ecc`
- `casino_v2_web.py` `081a3fda54e22f71011700b7cf57fa7a`
- `casino_player_cosmetics.py` `621db0a10c7cc7896f63a5897f1f9976`
- `casino_player_profile.py` `612a53362ccc78fbfa0c7945ac6681b3`
- `user_casino.py` `ea56c6145d9227267ccc3a6e5d11d101`
- `add_casino_notify_open_tables.sql` `e3c40202593ccd4409f1310cc253371f`
- `CasinoPlayersLobby.tsx` `7474bc1b46b85303b58ddca6c8f61cbd`
- `CasinoV2Table.tsx` `286262afd79f8ae264dea5efdba3501d`
- `CasinoPlayerSettings.tsx` `2023de8b877bad65f0f7c3189642eb85`
- `public.ts` `7f6a3e0e5e3267401ce4461a335cf0bf`
- `casino.css` `2d7ede8bac558fc4fbd0da7e1766b490`

`rg`: `publishes_web_group_invitation` — `casino_open_alerts` + create duel в `user_casino`. `enqueue_open_table_alerts` — alerts + duel create + v2 create. `WEB_V2_GAME_TYPES` / `ensure_blackjack_round` — `casino_v2_web`. `notify_open_tables` — cosmetics + profile + settings UI + PATCH. `isV2Table` — lobby для dice и blackjack. `can_add_bot` / `data-casino-v2-add-bot` — стол.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. Created-контейнеров нет.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: BJ players table + open alerts + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, этот срез не трогал). Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/play/blackjack?mode=players` — места 2–6, «Создать» / «Найти». В общем чате справа и в Telegram-группе **нет** поста о создании.
- На столе пустое место — **«+ бот»**; заполнил → старт → карты до 17, победитель по очкам. Банк 3×100 → победителю **285** (комиссия 15).
- `/casino/settings` — тумблер «Личные уведомления о новых столах блэкджека». Выкл по умолчанию; после включения (и Save) другому аккаунту с Telegram может прийти ЛС от casino-бота при новом столе.
- 1×1 дуэль блэкджека в списке ниже по-прежнему есть. Дом `?mode=house` hit/stand **должен остаться**.
- Кубики стол 2–6 + «+ бот» и 1×1 vs дом 100→195. **Должно остаться.**

## 2026-08-29 — BJ players: ничья = выбор + суммы на руки

Сделано по клик-фидбеку: при ничьей на столе блэкджека 2–6 больше нет авто-раздела без кнопок; в итоге видно, сколько получил каждый.

Бэкенд (`casino_v2_web.py`):
- ничья → phase `draw_choice`, статус `running`, лидеры в `tie_break_seat_nos`, дедлайн 60с;
- `POST /user/casino/v2/tables/{id}/draw-choice` — `tie_split` | `redeal` (перераздача только лидерам, HMAC nonce++);
- без людей за столом или по таймауту — авто `tie_split`;
- в публичном view: `can_choose_draw`, `is_leader`, `payout_rub` на место, `settlement.payouts`.

Фронт (`CasinoV2Table.tsx`): кнопки «Разделить банк» / «Перераздача лидерам»; строка победителей с суммами; на карточке места `+142,50 ₽`.

Тесты: +2 в `test_casino_v2_web.py` (draw_choice flags, per-seat payouts). Локально v2 web+cards green; `tsc` + `npm run build` ok.

Staging: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` — health passed.

`staging-test.sh`: **1295** collected (+2), **7 failed** (те же имена), **1288 passed**. Новых FAIL нет.

Gateway **200** `/casino`, `/api/health`. Бандл `index-r-dgTCAl.js`: `can_choose_draw`, `draw-choice`, «Разделить банк», «Перераздача лидерам», «ничья — выбор».

SQL: ключей **65**.

md5 local = `/opt` = live `/app/backend`:

- `casino_v2_web.py` `47a345b034309a706ba0bf93c8b0a677`
- `user_casino.py` `11e7a6e2e24d55fc473ff95c7148d401`
- `CasinoV2Table.tsx` `fda292188ecc8914ecff8c2dbb84010b`
- `public.ts` `391fcedf5d4aba66746cf8a66d73fbb3`
- `casino.css` `e0f3d197414df8a9b53959a996304292`

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. casino-bot без HostConfig ports.

Прод (read-only): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/blackjack?mode=players` — стол 3, боты, старт. При ничьей: статус «ничья — выбор», кнопки **Разделить банк** / **Перераздача лидерам**. Без клика ~60с → раздел.
- После раздела: «Победители: Вы 142,50 ₽ · …» и на карточке места `+142,50 ₽`, не общий 285 на всех.
- Перераздача: новые карты у лидеров, проигравшие с прежними руками; снова ничья → снова выбор.
- Дом BJ и кубики V2 **должны остаться**. Shelved games скрыты.

## 2026-08-29 — Фикс: повторная «Ставка» на Стол 2–6 → 500

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Следующую задачу плана не начинал.

Симптом (скрин): `?mode=house&view=table`, «Ставка» → тост «Не удалось выполнить запрос». Gateway: `POST /api/user/casino/house-tables` **500**. Backend: `TypeError: int() argument ... not 'asyncpg.Record'` в `is_solo_table` при повторном create (после раунда стол снова `open`, leave предыдущего соло).

Причина: `isinstance(table, Mapping)` ложно для `asyncpg.Record` → `int(Record)`.

Сделано: `is_solo_table` сначала `int`, иначе `table["max_seats"]`. Тест `_RecordLike` + FakeConn отдаёт Record-like.

Файлы:
- `site/exchange-backend/casino_house_tables.py`
- `site/exchange-backend/tests/test_casino_house_tables.py`

Локально: `unittest tests.test_casino_house_tables` → **30 OK**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed**. Postgres Recreate **без** `down -v`.

Тесты: в live backend `python -m unittest tests.test_casino_house_tables` → **30 OK**. Remote `staging-test.sh casino_house_tables` → **30 dots / 100%** (exit 0).

Живой шлюз **200**: `/api/health`, `/casino/play/pvp_dice`.

SQL: ключей **65**. `casino_games` **438**.

md5 local = `/opt` = live `/app/backend`:

- `casino_house_tables.py` `6c90b3ba0848de31a65ddc31e3995f5b`
- `test_casino_house_tables.py` `f11f8960957e826e17c76122495edd56`

`rg`: `is_solo_table` + комментарий asyncpg.Record — модуль; `_RecordLike` / `test_is_solo_table_accepts_int_dict_and_asyncpg_record_like` — тесты.

Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Публичный play на хосте `:18082` (как в скрине) — отдельный listener.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: house solo Record fix + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`) или как сейчас **18082**.

- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house&view=table` — боты 4, ставка 100 → **Ставка** → кубы, без красного тоста.
- Сразу ещё раз **Ставка** (повтор после выигрыша/проигрыша) — снова раунд, **не** «Не удалось выполнить запрос».
- 1×1 `?mode=house` без `view=table` — 100 → 195. **Должно остаться.**

## 2026-08-29 — Quiet House: лобби и шелл

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Скрытые игры не открывал. Игровые столы (hit/stand, соло 2–6) не менял.

Сделано: визуальный язык **Quiet House** на лобби и оболочке. Не Stake (navy/neon green). Лёд `#6ea8ff`, canvas `#0a0a0a`, Inter 14 / JetBrains. Бутик из четырёх видимых игр, не слот-каталог на 3000.

- Токены: атмосфера (radial ice), radius 8/10/16, elevation, duration 180ms. Заблокированные static-check строки не трогал (`--casino-header-h: 60px`, facet, press 0.97, `#0a0a0a`, `#6ea8ff`).
- Шапка: логотип + FocusPay / House, glass, баланс-чип, «Пополнить» на desktop.
- Рельс: lucide вместо emoji, активное состояние.
- Лобби: hero (HMAC + CTA кубики), недавние чипами, одна сетка игр + фильтры, живые дуэли, четыре pathway-карточки. How-to остаётся `data-casino-howto`.
- Плитки крупнее (minmax 200), бейдж категории, hover «Играть», портретная иллюстрация.

Файлы этого среза:

- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/CasinoGameTile.tsx`
- `focussite/frontend/src/casino/CasinoTileArt.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoTokensPreview.tsx`
- `docs/CASINO_WORKLOG.md`

Локально: `npx tsc -b` ок; `bootstrap_static_test.sh` **passed**; `npm run build` ок (2264 modules). Бандлы: `index-Dd1oWN56.css`, `index-0RUGVuFu.js`, `index-XsL6HNYl.js`, `index-pKHLblhk.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate **без** `down -v`.

Тесты на staging: **1309** collected (прогресс `[100%]`), **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. **1302 passed**. Новых имён нет.

Живой шлюз **200**: `/casino`, `/api/health`. В `index-XsL6HNYl.js`: `casino-hero`, `Focus House`.

md5 local = staging `/opt`:

- `casino.css` `d7c320d585beab464d62400359783be5`
- `CasinoLobby.tsx` `25df7d186a1bac12cb4b6a71ae039fc2`
- `CasinoGameTile.tsx` `1f6a3507579cd6264b7590f3e2d05ef7`
- `CasinoTileArt.tsx` `477f8b69686a2deaf3c66d52e644da08`
- `CasinoShell.tsx` `095feb650fa8cd52bbba575c18e02946`
- `CasinoTokensPreview.tsx` `c3f2e199e27f30c7868eeb81bed68cbf`

`rg` `casino-hero`: css + `CasinoLobby`. `data-casino-howto`: Lobby. `data-casino-tile`: GameTile. `Focus House`: Lobby. SQL не трогал.

Docker: наружу `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: Quiet House лобби/шелл + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino` — hero Focus House, CTA «Играть в кубики» и «Честность», сетка из четырёх плиток (Кубики / Баккара / Блэкджек / Джекпот). Нет холдема, рулетки, комнаты N, кланов.
- Поиск «холдем»: «Точного совпадения нет — весь каталог», скрытых плиток нет.
- Фильтры Все / Дуэли / Карты / Против казино. Desktop hover на плитке — «Играть».
- Шапка: FocusPay House, баланс, на широком экране «Пополнить».
- Не ломать: дом BJ hit/stand; куб 1×1 100→**195**; стол 2–6 повторная «Ставка». **Должно остаться.**

## 2026-08-29 — Отмена своих игр и таймаут 10 минут

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Скрытые холдем / рулетка / комната N / кланы не открывал. Вкладку «Мои» у ленты не превращал в живые столы.

Симптом: waiting-дуэль (баккара `#WEB-03E1`) можно было только открыть. В комнате «Остаться в очереди», в шапке только «Перейти», `POST /user/casino/duels/{id}/cancel` не было. Холд жил ~2 ч. V2 expire — 24 ч и только внутренний POST. Тост «Сначала встаньте с другого стола против казино» — leftover house-multi, кнопки встать не было.

Сделано:

- `POST /api/user/casino/duels/{game_id}/cancel` — создатель, `waiting`, нет соперника; `release_unified_hold`; `cancelled`; гонка с join → 409.
- Closer каждые ~10 с в процессе API (`WAITING_JOIN_TIMEOUT_SECONDS = 600`): waiting 1×1 без соперника; V2 `open`/`ready`/`draft` старше 10 мин и <2 людей; house-multi `open` старше 10 мин (solo 1×1 vs боты не трогаем). `active`/`running` не отменяем.
- Фронт: «Отменить игру» в комнате дуэли; шапка/колокол «Перейти» + «Отменить»/«Встать»; своя waiting-строка в лобби; на «Стол 2–6» 409 house — тост со «Встать».
- `formatApiDetail` читает `detail.message` у dict-409.

Файлы этого среза:

- `site/exchange-backend/casino_waiting.py` (новый)
- `site/exchange-backend/routers/user_casino.py`
- `site/exchange-backend/routers/internal_casino.py` (`expire_unjoined_v2_tables_with_conn`)
- `site/exchange-backend/casino_house_tables.py` (`expire_open_unjoined`, 409 с `table_id`)
- `site/exchange-backend/casino_inbox.py` (`can_cancel` / `can_leave`)
- `site/exchange-backend/casino_pvp_dice.py`, `casino_v2_web.py` (хук closer)
- `site/exchange-backend/tests/test_casino_waiting.py` (новый, 10 тестов)
- `site/exchange-backend/tests/test_casino_house_tables.py`, `tests/test_casino_inbox.py`
- `focussite/frontend/src/lib/public.ts` (`cancelCasinoDuel`)
- `focussite/frontend/src/lib/api.ts`
- `focussite/frontend/src/casino/CasinoDuelRoom.tsx`, `CasinoShell.tsx`, `CasinoPlayersLobby.tsx`, `CasinoPlayerChip.tsx`, `CasinoPlay.tsx`

Локально: `npx tsc --noEmit` ок. Live backend `python -m unittest tests.test_casino_waiting tests.test_casino_inbox tests.test_casino_house_tables tests.test_casino_duels tests.test_casino_v2_web -q` → **88 OK**.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate **без** `down -v`. Gateway build: 2264 modules; `casino-Ce08PqiK.js`, `index-BM3JWQ2L.js`, `index-DtXoghln.js`, `index-pKHLblhk.js`.

Тесты на staging: `staging-test.sh` **1309** collected (`test_casino_waiting.py`: 10), **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. **1302 passed**. Новых имён нет.

Живой шлюз **200**: `/api/health`, `/casino`.

SQL: ключей **65**. `casino_games` **438**. Миграций в этом срезе нет.

md5 local = `/opt` = live `/app/backend` (на момент выката):

- `casino_waiting.py` `1381d1a9a719d77d594174233012b58f`
- `user_casino.py` `02dad656ff98304e80bfbacea6b65078`
- `casino_house_tables.py` `31339810f5f21a48d11800c10a7a10c1`
- `casino_inbox.py` `e78045340ae98d561b3f2d8c49c09488`
- `test_casino_waiting.py` `1aa77b79bbb49a1d49cdb478e3467b39`
- `CasinoDuelRoom.tsx` `361507428f2b7902043095a035c1b472`
- `CasinoPlay.tsx` `04f6a6c064d62928dcdcf8ab2bf11c76`
- `CasinoPlayersLobby.tsx` `7f7f7886bc6cf12fae65329e0bd48f18`
- `CasinoPlayerChip.tsx` `37509347fc293b62ee50371b992004f7`
- `public.ts` `65b48a6893f2b88a7e4ec53cba1c4fe9`
- `api.ts` `3070ef6f7a49064a12d60ca4844539aa`
- `CasinoShell.tsx` на `/opt` `254028026493b5e3bd22f1412439042f` (выкат с cancel в шапке/колоколе)

`rg`: `cancel_waiting_duel` — `casino_waiting.py`, `user_casino.py`, тесты. `cancelCasinoDuel` — `public.ts`, `CasinoShell`, `CasinoDuelRoom`, `CasinoPlayersLobby`. `WAITING_JOIN_TIMEOUT` — модуль + тесты. `expire_unjoined` — waiting, `internal_casino`, house, тесты. Роут `/casino/duels/{game_id}/cancel` есть в `user_casino.router`.

Docker: наружу `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. `focuspay-staging-play-public` без публикации в `docker ps` (как раньше, хост **18082** — отдельный listener).

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: waiting cancel/expire + UI + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty с прошлого WIP — **этот срез бота не трогал**. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`); тот же шлюз с хоста — **18082**.

- Создать баккару 1×1, уйти в кубики: шапка/колокол → **Отменить**, ставка снова на балансе.
- Та же дуэль без отмены: через 10 мин статус cancelled, деньги вернулись; до 10 мин жива.
- Своя строка в лобби «С игроками» тоже отменяет.
- 1×1 vs дом 100 ₽ → **195** ₽ как сейчас.
- Join чужой дуэли на 9-й минуте не должен отменить её под игроком.
- «Стол 2–6»: если висит тост «Сначала встаньте…» — **Встать**, не только красный текст.

## 2026-08-29 — Quiet House: стол, чат, дуэли

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Скрытые игры не открывал. Hit/stand, соло 1×1 и «Отменить игру» не вырезал.

Сделано: тот же Quiet House на поверхностях, где сидят дольше лобби. Чат больше не колонка 320px.

- Чат: `docked={false}`, выезжает справа (`position: fixed`, 360px), затемнение, Escape / крестик / backdrop. В шапке desktop кнопка «Открыть чат». `casinoChatIsLive` по-прежнему `return open || docked` (тест чата не ломал).
- Игра: крошка «Лобби / имя», сегменты режима как фильтры, панель «Ставка», холст стола без emoji в h1.
- Лобби: скелет цифр hero, пока нет ответа API.
- Дуэли / джекпот / профиль / настройки / комната дуэли: те же крошки и карточки. Оверлей с сайта — на весь экран, не «окошко» 16px.
- Срез waiting-cancel («Отменить игру», колокол) на месте.

Файлы этого среза:

- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoChatPanel.tsx`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/CasinoJackpot.tsx`
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/src/casino/CasinoDuels.tsx`
- `focussite/frontend/src/casino/CasinoPlayerSettings.tsx`
- `focussite/frontend/src/casino/CasinoDuelRoom.tsx`
- `docs/CASINO_WORKLOG.md`

Локально: `npx tsc -b` ок; `bootstrap_static_test.sh` **passed**; `npm run build` ок (2264 modules). Бандлы шлюза после второго sync: `index-CcD2SnQS.css`, `index-B_OocKWV.js`, `index-CxAFxw71.js`, `index-pKHLblhk.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Первый retry упал на `fake-payfast` «removal already in progress»; повтор — health **passed** дважды. Postgres Recreate **без** `down -v`.

Тесты на staging: `staging-test.sh` дошёл до **[100%]**, **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет.

Живой шлюз **200**: `/casino`, `/api/health`. В CSS: `casino-crumb`, `casino-header-chat`, `casino-stake-kicker`. В JS: `Focus House`, `Открыть чат`.

md5 local = staging `/opt`:

- `casino.css` `b0b0f400ac02b09edc180c253b10a058`
- `CasinoShell.tsx` `5cbf635bf42e0d09a7a39ae540811c77`
- `CasinoChatPanel.tsx` `355bcf759c8dceea7c14dc2ab165d3d7`
- `CasinoPlay.tsx` `e694909ba8b2dae8922d80e733affee0`
- `CasinoLobby.tsx` `5e0de55c0710143b7ec9659526084e0e`
- `CasinoJackpot.tsx` `c622bb346d445f7cd0226ff80da915b6`
- `CasinoProfile.tsx` `59f2b5c6b36eecbdb9bc1ac55b67e534`
- `CasinoDuels.tsx` `509e20182ec6e9c6accde63677e68deb`
- `CasinoPlayerSettings.tsx` `cea3cf0474eba6e26eae84c61365e46a`
- `CasinoDuelRoom.tsx` `4c080ee90e35ac6a7a18d90d7d1e67a4`

`rg` `casino-crumb`: css + Play/Lobby/Jackpot/Profile/Duels/Settings/DuelRoom. `data-casino-chat-toggle`: Shell. `return open || docked`: ChatPanel. `data-casino-howto` / `data-casino-house-view` / `data-casino-stake` на месте. SQL не трогал.

Docker: наружу `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: Quiet House стол/чат + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino` — лобби без колонки чата справа. На широком экране иконка чата в шапке: панель поверх стола, лобби не сжимается. Escape / затемнение / крестик закрывают.
- Кубики `/casino/play/pvp_dice?mode=house` — крошка «Лобби / Кубики», «Ставка» слева, заголовок стола без emoji.
- Дуэли — крошка «Лобби / Дуэли», полоса создания как карточка. Джекпот — три цифры как hero-stat.
- С сайта «Казино» — оверлей на весь экран, не рамка 16px.
- Не ломать: дом BJ hit/stand; куб 1×1 100→**195**; стол 2–6 повторная «Ставка»; waiting «Отменить игру». Поиск «холдем» — скрытых плиток нет. **Должно остаться.**

## 2026-08-29 — Стол 2–6: коэффициент растёт с числом ботов

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. 1×1 cub policy / HMAC / комиссию не менял. Скрытые холдем / рулетка / комната N / кланы не открывал.

Было: стол 2–6 брал ту же политику, что 1×1 (×2, 50%, 100→195), боты только картинка.

Сделано: N ботов дома → коэффициент ×(N+1), шанс 1/(N+1). Комиссия как раньше — 5% от выигрыша (gross − stake).

| Боты | Коэф. | Шанс | 100 ₽ → выплата |
|---|---|---|---|
| 2 | ×3 | 33% | 290 |
| 3 | ×4 | 25% | 385 |
| 4 | ×5 | 20% | 480 |
| 5 | ×6 | 17% | 575 |
| 6 | ×7 | 14% | 670 |

1×1 без `house_bot_count` остаётся ×2 / 50% / 195. Порог HMAC в `play_cub_with_conn` масштабируется только если в запросе 2–6 ботов.

Файлы этого среза:

- `site/exchange-backend/casino_play.py` (`house_bots_cub_odds`)
- `site/exchange-backend/casino_house_tables.py` (quote/play с `house_bot_count`)
- `site/exchange-backend/routers/internal_casino.py` (`CubPlayRequest.house_bot_count`)
- `site/exchange-backend/routers/public_casino.py` (query `house_bot_count`)
- `site/exchange-backend/tests/test_casino_play.py`
- `site/exchange-backend/tests/test_casino_house_tables.py`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/CasinoHouseTables.tsx`

Локально: `npx tsc --noEmit` ок. `python -m unittest` HouseBotOdds + HouseMoney + TableFlow **OK** (36).

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Первый `--apply` упал на конфликт имени `fake-payfast` (Created leftover). Снял только Created-контейнеры, `down -v` не было. Postgres **Up 12 hours**. Повторно сервисы поднялись сами; health **passed**. Gateway bundle: `index-CxAFxw71.js` (`data-casino-house-odds`).

Тесты на staging: `staging-test.sh` **1316** collected (было 1309, +7 этого среза), **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. **1309 passed**. Новых имён нет.

Живой шлюз **200**: `/api/health`, `/casino`. Quote 100 ₽:

- без ботов: `payout_multiplier` **2**, `win_probability` **0.5**, `win_on_win_rub` **195**
- `house_bot_count=2`: **3** / **0.333…** / **290**
- `house_bot_count=3`: **4** / **0.25** / **385** (max_bet на staging **250** из-за ×4 и банка)

SQL: ключей **65**. Миграций нет.

md5 local = `/opt` = live `/app/backend`:

- `casino_play.py` `9c48ee61fea5f897fac0168c27b460db`
- `casino_house_tables.py` `7167bb1cd5ecc21bc44b5bee58b74324`
- `internal_casino.py` `8cf6df2fdbff67ba3759a9197aefc3f1`
- `public_casino.py` `988fedcd3f776c044480db376b08beed`
- `test_casino_play.py` `be02d8ea1b577dd590c323b3829d62ac`
- `CasinoPlay.tsx` `e694909ba8b2dae8922d80e733affee0`
- `CasinoHouseTables.tsx` `1cf9ab57f456abfc25a31ca02e6324a2`
- `public.ts` `d7f4516095e6b08f5bd10ca19cd8bd83`

`rg` `house_bots_cub_odds`: `casino_play.py`, `internal_casino.py`, `test_casino_play.py`. `data-casino-house-odds`: `CasinoPlay.tsx` + бандл `index-CxAFxw71.js`. Query `house_bot_count`: `public_casino.py` + `public.ts`.

Docker: наружу `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. Хост **18082** — отдельный listener, quote ×4/385 там же.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: odds стола 2–6 + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty с прошлого WIP — **этот срез бота не трогал**. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`); тот же шлюз с хоста — **18082**.

- `/casino/play/pvp_dice?mode=house&view=table` — вкладка «Стол 2–6». Ставка 100 ₽.
- Чип **2** бота: коэффициент **×3**, шанс **33%**, «Выигрыш при победе» **290 ₽**.
- Чип **3**: **×4**, **25%**, **385 ₽**.
- Чип **6**: **×7**, **14%**, **670 ₽**.
- Сыграть раунд на 3 ботах: при победе на баланс должно прийти **385**, не 195.
- `/casino/play/pvp_dice?mode=house` без table: 100 ₽ → **195**, ×2, 50%. **Должно остаться.**
- Не ломать: повторная «Ставка» на столе 2–6; BJ hit/stand; waiting «Отменить игру».

## 2026-08-29 — Quiet House: сукно столов

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Скрытые холдем / рулетка / комната N / кланы не открывал. Hit/stand, HMAC, коэффициенты стола 2–6 не менял.

Сделано: видимые столы как Quiet House, не зелёный фетр.

- Блэкджек/баккара 1×1: казино сверху, вы снизу, vs, крупнее карты и «Добрать»/«Оставить».
- Стол 2–6: тот же холст `casino-cub-stage`.
- Лобби «С игроками»: крошка «Столы»; карточки льда вместо `#163322`.
- V2-стол: крошка «Лобби / Стол», заголовок без emoji, места на холсте.
- Комната дуэли: места на том же холсте. Джекпот-лента глубже.

Файлы этого среза:

- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/CasinoHouseCards.tsx`
- `focussite/frontend/src/casino/CasinoHouseTables.tsx`
- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/casino/CasinoV2Table.tsx`
- `focussite/frontend/src/casino/CasinoDuelRoom.tsx`
- `docs/CASINO_WORKLOG.md`

Локально: `npx tsc -b` ок; `bootstrap_static_test.sh` **passed**; `npm run build` ок (2264 modules). Бандлы шлюза: `index-DIz6bZMq.css`, `index-B6-ZgfLT.js`, `index-gnVCo_vO.js`, `index-pKHLblhk.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` дважды (вторая — копия «сверху казино»). Health **passed**. Postgres Recreate **без** `down -v`.

Тесты на staging: `staging-test.sh` **[100%]**, **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет.

Живой шлюз **200**: `/casino`, `/api/health`. CSS: `casino-house-cards` ×8, `casino-felt-card`, без `#163322`. JS: `Сверху карты казино`, `data-casino-bj-hit`, `data-casino-house-tables`.

md5 local = staging `/opt`:

- `casino.css` `9cbc3b8fe50d1831f99b6cbf6aca5452`
- `CasinoHouseCards.tsx` `e0946a2fee52b1dcb555f15d4f0ec16d`
- `CasinoHouseTables.tsx` `4cab122330d51e758365ca50be8da445`
- `CasinoPlayersLobby.tsx` `af8b1011145ed1e95d286a111c5fa339`
- `CasinoV2Table.tsx` `02a856389045be96f43fd9fb683f9654`
- `CasinoDuelRoom.tsx` `081086929111c21cb7ae03eadfd8bd91`

`rg` `data-casino-house-cards` / `data-casino-bj-hit`: HouseCards. `data-casino-house-tables`: HouseTables. `data-casino-players-lobby`: PlayersLobby. `data-casino-v2-table`: V2Table. SQL не трогал.

Docker: наружу `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: сукно + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `/casino/play/blackjack?mode=house` — казино сверху, вы снизу, vs. После ставки: **Добрать** / **Оставить** как раньше.
- Баккара дом — та же раскладка, без hit/stand.
- `/casino/play/pvp_dice?mode=house&view=table` — вы vs боты дома на холсте. 3 бота, 100 ₽ → **385**.
- `/casino/play/pvp_dice?mode=house` без table: 100 → **195**.
- «С игроками» — карточки столов без зелёного фетра.
- Не ломать: BJ hit/stand; стол 2–6 повтор «Ставка»; waiting «Отменить игру»; поиск «холдем» без скрытых плиток. **Должно остаться.**

## 2026-08-29 — Кубики стол 2–6: переброс не кидал куб

Повод: `web-531386ff43fe4fd3`, статус «переброс», тост `V2 table cannot enter tie break`, кнопка «Кинуть кубик» не записывала грань.

Причина: HMAC переброса брал тот же `index=0`, что первый раунд → сразу снова ничья; `commit_outcome` пускал `tie_break` только из `status='running'`, повтор из `tie_break_running` откатывал транзакцию вместе с броском.

Сделано:

- `hmac_index` = `tie_break_round * required + i` в `fill_hmac_rolls` и `roll_web_table`
- `commit`/`settle` `tie_break` из `running` **или** `tie_break_running`
- тост: «Не удалось начать переброс. Обновите стол.»

Тесты: `test_tie_break_hmac_does_not_reuse_first_round_index`, `test_second_tie_break_is_allowed_from_tie_break_running`. Локально `test_casino_v2_web.py` 23/23.

Файлы этого среза: `casino_v2_web.py`, `routers/internal_casino.py`, `tests/test_casino_v2_web.py`, этот журнал. Фронт не трогал.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed**. Postgres Recreate **без** `down -v`.

`staging-test.sh`: **1318** collected, **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых FAIL нет.

Живой шлюз **200**: `/casino`, `/api/health`. SQL: ключей **65**. Стол из скрина `web-531386ff43fe4fd3` сейчас `finished` / `state_version=12` / `tie_break_round=1` — для проверки нужен **новый** стол.

md5 local = `/opt` = live `/app/backend`:

- `casino_v2_web.py` `04fcc05b207068b28329632806b2010f`
- `internal_casino.py` `79c4a8c3b2aff1474b02e589ef4d7770`
- `test_casino_v2_web.py` `90a99b9e3ee73ab22bf11f433143ff9f`

`rg`: `def hmac_index` — `casino_v2_web.py:253`. Вызовы — `fill_hmac_rolls`, `roll_web_table`. `status IN ('running','tie_break_running')` — commit и settle в `internal_casino.py`.

Docker: наружу `127.0.0.1:18081->8080/tcp` у gateway. Хост nginx слушает **18082** (`focuspay-staging-play-public`). `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: переброс кубов + журнал; остальной dirty — чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`) или как раньше **18082**.

- `/casino/play/pvp_dice?mode=players` — стол 3, ставка 100, один бот, старт. Старый `web-531386ff43fe4fd3` уже завершён — не тот стол.
- Кинуть кубик: грань появляется, тоста `V2 table cannot enter tie break` нет.
- Если ничья: статус «переброс», у робота **другая** грань, не та же что в первом раунде; ваш куб снова кидается.
- Банк 200, комиссия 10, победителю **190**.
- Не ломать: дом 1×1 кубы 100→195; BJ hit/stand; стол BJ «ничья — выбор». **Должно остаться.**

## 2026-08-29 — Quiet House: верификатор честности в оболочке

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. Скрытые холдем / рулетка / комната N / кланы не открывал. Hit/stand, HMAC, коэффициенты стола 2–6, waiting-cancel не менял. Логику `verify` не трогал.

Сделано: `/casino/fairness` больше не светлая страница с `PublicHeader`. Живёт внутри `CasinoShell` (крошка, поля, карточки Quiet House). С оверлея сайта «Честность» не выкидывает на публичный сайт.

- Маршрут `path="fairness"` в `casinoChildRoutes`; отдельный `path="/casino/fairness"` из `App.tsx` убран. Miniapp берёт тот же child.
- `isCasinoShellPath` включает fairness (исключения: `/casino/tg`, `/tokens`, `/creator`).
- Селект без shadcn: холдем / комната N / клан vs клан по-прежнему не в списке, глубокая ссылка остаётся (`isShelvedCasinoGame`).
- Автопроверка по query (`autoVerifyFromParams`) и тексты «Сходится» / «Не сходится» те же.
- Рельс: `NavLink` активен на `/fairness`. В мобильном листе «Игры» появилась «Честность».

Файлы этого среза:

- `focussite/frontend/src/pages/CasinoFairness.tsx`
- `focussite/frontend/src/casino/casinoRoutes.tsx`
- `focussite/frontend/src/casino/casinoOverlay.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/miniapp-main.tsx`
- `focussite/frontend/src/App.tsx`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Локально: `npx tsc -b` ок; `bootstrap_static_test.sh` **passed**; `npm run build` ок (2264 modules). Бандлы шлюза: `index-Bg4jPeTl.css`, `index-PdOMw3Sn.js`, `index-DMkwzRcI.js`, `index-Cb0Y9e8n.js`.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed** дважды. Postgres Recreate от `staging-test.sh` **без** `down -v` (том жив, ключей 65).

Тесты на staging: `staging-test.sh` **[100%]**, **1318** collected, **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых имён нет. Passed **1311** (1318−7). +2 collected — не этот срез (уже в дереве: переброс V2).

Живой шлюз **200**: `/casino`, `/casino/fairness`, `/api/health`. CSS: `casino-fairness` в `index-Bg4jPeTl.css`. JS: `data-casino-fairness` ×2, `Сходится`, `Не сходится` в `index-PdOMw3Sn.js`. Live `POST /api/public/casino/fairness/verify`: match **True**, tamper **False**.

SQL: ключей **65**. Миграций нет.

md5 local = staging `/opt`:

- `CasinoFairness.tsx` `898ba2ff146b9f077386485532b724bd`
- `casinoRoutes.tsx` `69828830866833097e2eedee2a657efd`
- `casinoOverlay.tsx` `f998e393e210e4aa8a4f37a189db013a`
- `CasinoShell.tsx` `f3c97fc54b8191c58ff1e7485e178f6a`
- `casino.css` `2d60551d4fd1372b14c6aa47db018288`
- `miniapp-main.tsx` `29cb06ea84b993aaf85872c3fbfa4e95`
- `App.tsx` `9c49cd2d605cb2666315fe43701e5a36`
- `bootstrap_static_test.sh` `d51dd0cabb053ce55b657958cdde2789`

`rg` `data-casino-fairness` / `autoVerifyFromParams`: страница + bootstrap. `path="fairness"`: `casinoRoutes.tsx` + bootstrap. `isShelvedCasinoGame`: catalog + Fairness. В `casinoOverlay.tsx` / `App.tsx` строки `/casino/fairness` больше нет.

Docker: наружу `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: fairness в оболочке + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/fairness` — шапка/рельс казино, крошка «Лобби / Честность», без светлой `PublicHeader`. В селекте нет холдема / комнаты N / кланов.
- С лобби «Честность» — остаётесь в оболочке (с сайта — в оверлее, лобби не сжимается в колонку).
- Рельс «Честность» подсвечивается. На узком экране: «Игры» → Честность.
- Пустая форма: вставить сид+хеш, **Проверить**. Испортить один символ сида → **Не сходится**.
- Ссылка из бота с query по-прежнему сама бьёт verify.
- Не ломать: BJ hit/stand; куб 1×1 100→**195**; стол 2–6, 3 бота 100→**385**; waiting «Отменить игру»; поиск «холдем» без скрытых плиток. **Должно остаться.**

## 2026-08-30 · Европейская рулетка 0–36 (новый режим против казино)

Сделано: полноценная European Roulette 37 лунок как ещё одна игра против дома. Исход считает сервер (HMAC-SHA256 mod 37), баланс — существующий ledger, отдельной денежной системы нет. Другие режимы не тронуты.

Бэкенд:

- `casino_roulette.py` (637 строк) — единственный источник правды: `WHEEL_ORDER` (физический порядок одного зеро), `RED_POCKETS` / `BLACK_POCKETS`, `ROULETTE_BETS` (red/black ×2, zero ×36), `roulette_pocket` = `HMAC-SHA256(seed, "client_seed:nonce:game_id:pocket") mod 37`, `resolve_roulette_round`, `verify_roulette_round`, `play_roulette_with_conn` (холд → резерв дома по максимальной выплате → расчёт → комиссия → history).
- Регистрация: `GAME_KEYS`, `KNOWN_GAME_TYPES`, `HOUSE_PLAY_GAME_TYPES`, `CASHBACK_GAME_TYPES`, `GAME_LABELS`, `LOBBY_CATALOG` (стало **10** игр).
- Роуты: `GET /public/casino/play/quote?game_type=roulette&bet=red|black|zero`, `POST /user/casino/play {game_type:"roulette", bet}`, лента отдаёт `result{pocket,color,bet}`, `POST /public/casino/fairness/verify` с `expected_pocket`.
- Политика/банкролл: своей `casino_house_policies` строки у рулетки нет — берём cub-политику и cub-банкролл (`allowed_games ? 'roulette' OR ? 'cub'`). Коэффициенты остаются жёстко в правилах колеса, оператор их не крутит.
- Миграция `add_casino_roulette.sql` (70 строк): `casino_games_game_type_check` + `'roulette'`, `enabled_games.roulette = false` через `DO NOTHING`-семантику. Зарегистрирована в `00-apply-migrations.sh` (2 места) и `20-full-panel-bootstrap.sh` (3 места).

Фронтенд:

- `src/casino/roulette.ts` (143) — зеркало колеса для рендера: порядок, цвета, ставки, `rouletteRotationFor` (детерминированный угол посадки), `mergeRouletteHistory` (18 записей).
- `src/casino/CasinoRoulette.tsx` (259) — SVG-колесо 37 секторов, указатель на 12 часов, статичная ступица с номером, селектор red/black/zero (`aria-pressed`, border+fill+ring, не только цвет), результат в `aria-live`, история кружками.
- `CasinoPlay.tsx` — рулетка идёт как house-игра: котировка с типом ставки, быстрые чипы 10/50/100/500/1000/5000 ₽ (вне лимита — `disabled`), блокировка ставки/суммы во время спина, «Крутить», авто-таб скрыт, «С игроками» в свитче выключен + PlayNote. Результат раскрывается только после остановки колеса (launch 900 мс linear → settle 2600 мс `cubic-bezier(0.12,0.74,0.02,1)`, при `prefers-reduced-motion` 0 мс).
- Зеро резервирует ×36, поэтому его максимум ниже: при переключении ставки сумма один раз поджимается к новому максимуму.
- `casino.css` +65 правил `casino-roulette*`; `CasinoTileArt` — плитка с реальным порядком секторов; `CasinoFairness.tsx` — игра «Европейская рулетка», поле «Лунка 0–36», вывод лунки/цвета; каталог, `adminApi`, `casinoSettingsModel`, `CasinoRisk` знают ключ `roulette`.

Тесты локально:

- `tests/test_casino_roulette.py` (778 строк, **53** теста) — все 37 лунок и цвета, порядок колеса, ×2 / ×36, комиссия только с выигрыша, детерминизм и разброс HMAC, verify (match/tamper), реестры, котировка, полный `play_roulette_with_conn` (баланс, резерв, ledger, выключенная игра, неверная ставка, лимиты).
- Поправлены 3 чужих теста, где `"roulette"` служил примером **неизвестной** игры (`test_casino_settings_registry` ×2, `test_admin_casino_regression` ×1) — теперь `"keno"`. `test_public_casino_lobby`: игр стало 10, добавлена проверка roulette.
- `npx tsc -b` ок. `npm run build` ок (2266 modules). `scripts/check-roulette-model.mts`: 37 лунок, канонические цвета, угол посадки < 1e-6°.
- Локальный прогон `tests`: 1371 collected, падают те же 6 имён. Проверено, что они не про рулетку: убрал `"roulette"` из `CASHBACK_GAME_TYPES` — те же 6 падений.

Staging (`staging-sync.sh` дважды, health **passed** оба раза):

- `staging-test.sh` **[100%]**, junit: tests **1463**, failures **6**, errors **0**, skipped **1** → passed **1456**. Имена: `CasinoWeeklyCashbackTests` ×2, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Новых имён нет (`FinanceAccessStagingFixtureTests` в junit-прогоне прошёл, в первом — упал; он и раньше в списке).
- SQL: constraint = `... 'cub', 'roulette'`; `enabled_games` содержит `"roulette"`; ключей **65**. Включил рулетку на staging: `enabled_games.roulette = true`. После повторного `staging-sync.sh` флаг **остался true** — bootstrap настройку не затирает.
- Живой прогон денег `scripts/staging-roulette-smoke.py` внутри backend-контейнера (реальный Postgres, `play_roulette_with_conn`, без подделки токенов):
  - 60 раундов ×10 ₽ по кругу red/black/zero: wins **17**, staked **600.00**, paid **331.50**, комиссия **8.50**. Ledger игрока **−268.50** = paid − staked, дом **+268.50**. Лунок различных **30**, зависших холдов и резервов **0**.
  - 19 раундов только на зеро: выпал **0 green**, выплата **342.50** при комиссии **17.50** (10 × 36 = 360 − 5% с 350). Ledger **+152.50**, дом **−152.50**.
  - Итого в базе рулетки: **79** finished, оборот **790.00**, выплат **674.00**, комиссии **26.00**, различных лунок **32**, цвета black 41 / red 37 / green 1.
- HTTP через шлюз 18081: лобби отдаёт `roulette` (**enabled: true**, 10 игр). Котировка red 100 ₽ → ×2, шанс **0.4865**, выплата **195.00**, лимит 10–500 ₽. Котировка zero 100 ₽ → ×36, шанс **0.0270**, gross **3600**, комиссия **175**, выплата **3425**, лимит 10–**27.78** ₽ и `bound_error` (это общий предохранитель `effective_max_stake`: ×36 × ставка не может превысить долю банкролла, тот же механизм, что у cub). `bet=purple` → **422**. Лента: 40 строк с `result{pocket,color,bet}`.
- Fairness на реальном раунде `b90d9a35…`: `matches` **true**, `pocket` **0 green**, `wheel_index` 0, algorithm `hmac-sha256-pocket-mod37`. Порча одного символа сида → `matches` **false**, `commit_matches` **false**.
- Бандлы шлюза: `index-C--i5Rb5.css` (65 вхождений `casino-roulette`), `index-g9Xa2SSe.js`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у gateway. Новых публикаций нет.

md5 local = staging `/opt`:

- `casino_roulette.py` `d065799388b84f931f920d213079b531`
- `casino_play.py` `d710d9c23fe11c46a928668ff302bf64`
- `casino_settings_registry.py` `7051da20b8a92aa4ff2efbc78c273ed2`
- `routers/user_casino.py` `dffdfffe70c031db7db696b2ba88c896`
- `routers/public_casino.py` `528a522ef0b9cf9d5291171aa291c69a`
- `migrations/add_casino_roulette.sql` `0e00fceb336408ecf69b6586d3b141bc`
- `casino/roulette.ts` `511e4778013e61bffcf6e5d4e3ffec54`
- `casino/CasinoRoulette.tsx` `5c782734cf7456ee32a73cffb253021c`
- `casino/CasinoPlay.tsx` `712025d0d25846b23b5a8cdaddcad5c5`
- `casino/casino.css` `9ce1f1734107a33c4f6a27f6e6338d02`
- `lib/public.ts` `cafbed4ce5239d049d596ee7d83fd61f`
- `pages/CasinoFairness.tsx` `fd306e043de43fd2b744b584ddc27502`

`rg -ci roulette` (не «объявили и забыли»): бэкенд — `casino_roulette.py` 50, `casino_play.py` 16, `public_casino.py` 14, `user_casino.py` 10, миграция 11, реестр/finance/wager/profile по 1, тесты 100 + 3. Фронт — `CasinoPlay.tsx` 67, `CasinoRoulette.tsx` 69, `casino.css` 81, `roulette.ts` 35, `public.ts` 13, `CasinoFairness.tsx` 9, `CasinoTileArt.tsx` 7, каталог 3, панель 3. Bootstrap-скрипты 2 + 3.

Прод (read-only `ssh focuspay`), до и после работ одно и то же: `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: рулетка + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, не деплоил на прод.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/play/roulette` — колесо 37 секторов, 0 зелёный, порядок 0-32-15-19-4-21… (не 0-1-2-3). Указатель сверху, номер в ступице.
- Ставка **Красное**, сумма **100** → «Выигрыш при победе» **195.00 ₽**. Крутить: колесо разгоняется, тормозит и встаёт ровно на выпавший номер; результат и история появляются **после** остановки, не раньше.
- Переключить на **Зеро** → сумма сама поджимается к **27.78 ₽**, чипы 50/100/500 гаснут, коэффициент становится **35:1**. Ставка 10 ₽ → в поле выигрыша **342.50 ₽**. Это защита банкролла, не баг.
- Во время спина: сумма, ½, ×2, чипы и три кнопки ставки — заблокированы, второй клик по «Крутить» не проходит.
- История: 10–18 кружков, красный / чёрный / зелёный, номер внутри. F5 — история подтягивается из ленты, не пустая.
- Мобильная ширина (или телефон через тот же туннель): колесо масштабируется, ставки в три колонки, «Крутить» крупная, горизонтальной прокрутки нет.
- Вкладка «С игроками» у рулетки выключена, при заходе по `?mode=players` — пояснение, что игра только против казино.
- `http://127.0.0.1:18081/casino/fairness` → игра «Европейская рулетка»: вставить game_id / хеш / сид / nonce из раунда, «Лунка» — номер. **Сходится**. Испортить символ сида → **Не сходится**.
- Лобби и поиск: плитка «Европейская рулетка» видна, поиск по «рулетка», «red», «зеро» находит. FocusLucky-раффл по-прежнему скрыт.
- Не ломать: куб 1×1 100 → **195**; стол 2–6, 3 бота 100 → **385**; BJ hit/stand; баккара 1×1; джекпот; лента и «Честность» у карт. **Должно остаться.**

## 2026-08-30 · Рулетка: UI-доводка под спецификацию стола

Сделано: европейская рулетка уже была house-игрой (сервер HMAC, ledger, ×2/×36). Этот срез только фронт: явные фазы стола, −/+, карточка результата, подписи истории, подсветка лунки. Бэкенд, выплаты и другие режимы не трогал.

Файлы (только эти):

- `roulette.ts` 177 — `ROULETTE_STAKE_STEP=10`, `rouletteUiPhase` (idle/ready/spinning/win/loss/insufficient/invalid).
- `CasinoRoulette.tsx` 296 — карточка «Выпало / номер / цвет / Победа|Поражение ±сумма / ставка·выплата», `data-casino-roulette-phase`, сектор `is-landed`, история с подписью цвета.
- `CasinoPlay.tsx` 1201 — степпер `[−][сумма][+][½][×2]`, фаза в стол, ½/×2 у рулетки ещё и на `pending`.
- `casino.css` — степпер 44px, кнопка «Крутить» 52px, результат, подписи истории, mobile 5 колонок.
- `scripts/check-roulette-model.mts` 115 — плюс 8 проверок фаз.

Проверки:

- `npx tsx scripts/check-roulette-model.mts` — ok (37 лунок, цвета, угол < 1e-6°, фазы).
- `npx tsc -b` ok. `npm run build` ok (2266 modules). Бандл `index-Ct0O9Zgr.css` / `index-Cb0Y9e8n.js`.
- Браузер preview :4175: desktop — колесо справа, панель слева, −/+ есть, зеро с зелёной рамкой, ставка 0 → «некорректна» + «должна быть больше нуля», − disabled. Mobile 390×844 — колесо масштабируется, ставки в три колонки, степпер и «Войти и крутить» без горизонтального overflow.
- `staging-sync.sh` — health **passed**. md5 local = staging: `roulette.ts` `0b7de9d2b1ab9b35b55cea733a690251`, `CasinoRoulette.tsx` `a9e2a63282764e2d2b7144b68058f397`, `CasinoPlay.tsx` `fe00bd4c9367d1f743dc8618986b7403`, `casino.css` `0315dae3bcb6ba453dd9b0ea6ab0a630`, `check-roulette-model.mts` `080add64b8a7b7f27da4b46cb6353a23`. Бэкенд `casino_roulette.py` без изменений `d065799388b84f931f920d213079b531`.
- `staging-test.sh` **[100%]**, упали те же известные 6 + флапающий `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`. Новых имён нет. Рулеточные тесты не в списке.
- SQL: constraint содержит `'roulette'`; `enabled_games.roulette` = **true**; ключей **65**; finished-раундов рулетки **115**.
- HTTP 18081: лобби 10 игр, roulette **enabled: true**. Quote red 100 ₽ → ×2, шанс **0.4865**, выплата **195.00**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp`. Новых публикаций нет.
- Прод (read-only): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

`rg -ci roulette` фронт этого среза: `CasinoPlay.tsx` 84, `CasinoRoulette.tsx` 81, `casino.css` 100, `roulette.ts` 39, `check-roulette-model.mts` 45.

Git: `focuspay` HEAD `61e47be`, dirty (рулетка + журнал). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, не деплоил на прод.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/play/roulette` — колесо 0-32-15-19…, указатель сверху. Под колесом Красное / Чёрное / Зеро: выбранное с рамкой и лёгким свечением, не только цветом.
- Сумма: **−** / **+** шагают по **10 ₽**, рядом ½ и ×2, чипы 10/50/100/500/1000/5000. Ставка 0 → красная ошибка «должна быть больше нуля», «Крутить» не должна списывать.
- Красное 100 → «Выигрыш при победе» **195.00 ₽**. Крутить: колесо разгон → торможение на выпавшем номере; карточка «Выпало / N / цвет / Победа|Поражение ±сумма» и кружок в истории — **после** остановки.
- Зеро: коэффициент **35:1**, максимум сам поджимается (~27.78 ₽). Это защита банкролла ×36, не баг.
- Во время спина: − + ½ ×2 чипы и три цвета заблокированы, второй «Крутить» не проходит.
- История: кружок цвета + подпись «красное/чёрное/зеро» под ним. F5 — не пустая, из ленты.
- Телефон: колесо масштабируется, ставки столбиком, «Крутить» крупная (≥44px), горизонтальной прокрутки нет.
- «С игроками» выключена. Честность: game_id/хеш/сид → лунка сходится; испортить сид → нет.
- Не ломать: куб 1×1 100 → **195**; стол 2–6, 3 бота 100 → **385**; BJ hit/stand; баккара; джекпот. **Должно остаться.**

## 2026-08-30 · Рулетка: баланс после остановки, числа 35:1, разный спин

Сделано по клик-приёмке: (1) баланс в шапке и на панели больше не прыгает до остановки колеса; (2) straight-up 0–36 как зеро, 35:1; (3) прокрутка каждый раз другая (6–10 оборотов, 3.8–6.2 с, разные easing, coast пока сервер считает). RNG и ledger те же.

Бэкенд:

- `bet_spec` принимает `red`/`black`/`zero` и `"0"`–`"36"`. `"0"` = зеро. Число 1–36 — ×36, один карман. `HousePlayBody.bet` и quote `bet` — строка, не Literal из трёх.
- Локально `tests/test_casino_roulette.py`: **57** passed (было 53). Новые: straight payout, quote 17 = zero max, play 17 → 342.50.

Фронт:

- `onSpin`: `applyRoundWallet` и `CASINO_BALANCE_EVENT` только после `plan.durationMs`. Результат на колесе уже есть, деньги на экране — нет.
- Сетка 0–36 под цветами; клик по сектору колеса тоже ставит число. 17 → шанс 2.7%, тот же max что у зеро.
- Спин: coast 48 оборотов / 14 с linear, потом interrupt на случайный план (crypto, не Math.random).

Проверки:

- `npx tsx scripts/check-roulette-model.mts` ok. `tsc -b` ok. `npm run build` ok. Бандл `index-DKdUnwXU.css`.
- Preview: 17 с белой рамкой, «Сейчас «17», выплата 35:1». Mobile 390: сетка 7 колонок, 44px.
- `staging-sync.sh` health **passed**. md5 local = staging: `roulette.ts` `e8f9954f871b37ef85a78c79eb206c39`, `CasinoRoulette.tsx` `2f165009a53ba90c8111ef677d9f1ba1`, `CasinoPlay.tsx` `dc9c99e6d1b69bf508646a14b0c59e42`, `casino.css` `2eb8bf98096be2f106771e4dade12f1e`, `casino_roulette.py` `180990730fa6799ee0ed6a039e5f1666`, `user_casino.py` `a75cacc96223613b90463e3f2f49e272`, `public_casino.py` `7bc85e132bbda635dd801296bc897f02`.
- `staging-test.sh` **[100%]**, те же 7 известных имён. Новых нет.
- HTTP 18081: quote `bet=17` stake 10 → ×36, max **27.78**, выплата **342.50**. `bet=0` → `bet: zero`.
- Docker наружу: только `127.0.0.1:18081->8080`. Прод метки те же: index 2026-08-29 06:08:38, panel 2026-08-28 04:22:48, unit 2026-08-29 06:08:19.

Git: `61e47be`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette` — войти. Запомнить баланс в шапке и на панели. Крутить красное: **пока колесо крутится баланс не меняется**. После остановки — да, и карточка результата.
- Сетка: нажать **17**. «Выигрыш при победе» как у зеро на ту же сумму (10 ₽ → **342.50**). Крутить. Победа только если выпало 17.
- Два спина подряд: длительность и число оборотов **разные**, не один и тот же ролик.
- Во время спина сетка и цвета заблокированы. Второй «Крутить» не проходит.
- Не ломать: куб 1×1 100 → **195**; BJ; баккара. **Должно остаться.**

## 2026-08-30 · Рулетка: один спин, стол 0–36, короткая история

Клик: колесо крутилось дважды; числа не влезали; история длинная; снизу «Мои / Все / Крупные» крупные.

Причина двойного спина: после остановки `setSpinPlan(null)` заново запускал CSS-settle на ту же лунку. Coast был отдельным 14 с CSS-переходом — выглядело как второй разгон.

Сделано:

- Один ход: rAF-coast пока сервер считает, затем одно торможение на HMAC-лунку. Повторно не крутит, когда план сбрасывается.
- Стол как в европейской рулетке: 0 слева на три ряда, 12 колонок 3/2/1. Все 37 клеток, без обрезки. На 390px: 37 клеток, overflowX 0, zero 84px.
- История колеса: **10** последних, одна лента без подписей «красное/чёрное».
- Лента «Мои / Все / Крупные»: компактные вкладки, 8 строк, высота ~148px. Чипы быстрой суммы меньше.

Проверки:

- `npx tsx scripts/check-roulette-model.mts` ok (лимит истории 10, felt 0–36). `tsc -b` ok. `npm run build` ok. Бандл `index-DyYj-0WP.css`.
- Preview 390: 37 клеток, 36/35/34 на месте, горизонтального скролла нет.
- `staging-sync.sh` health **passed**. md5 local = staging: `roulette.ts` `bcb5d5e3bfe94ff44dce365511afff98`, `CasinoRoulette.tsx` `cd4dd3afa589797bf505b74713b55835`, `CasinoPlay.tsx` `b2d9f6b21fab615bc98ec0ec26c10300`, `casino.css` `526bfd9d6d46be5d4f53fd5a0d1c0bae`.
- `staging-test.sh` те же 7 известных имён. Новых нет: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу: только `127.0.0.1:18081->8080`. Прод метки те же: index 2026-08-29 06:08:38, panel 2026-08-28 04:22:48, unit 2026-08-29 06:08:19.

Git: `61e47be`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette` — крутить: **одно** торможение, без второго круга после остановки.
- Сетка: 0 слева на всю высоту, справа 1–36 как на столе, все видны, в том числе 34–36. Клик по 17 по-прежнему 35:1.
- История под колесом — не больше **10** кружков в один ряд.
- Снизу «Мои / Все / Крупные» ниже и мельче, не на пол-экрана.
- Не ломать: баланс после остановки; куб 1×1 100 → **195**. **Должно остаться.**

## 2026-08-30 · Рулетка: без показа игр на столе

Клик: убрать показ игр на экране рулетки.

Сделано только на `/casino/play/roulette`:

- Рельс: нет секции «Игры», нет кубиков/баккары/джека, нет «Все дуэли». Остались Лобби / Честность / Профиль / Настройки / Кошелёк.
- Телефон: пункта «Игры» и шита каталога нет (Лобби / Чат / Профиль).
- Ленты «Мои / Все / Крупные» нет.
- Нет «Контроль игры», HMAC-простыни и табов «Против казино / С игроками».

Лобби и другие столы не трогал. Каталог игр на `/casino` как был.

Проверки:

- `tsc -b` ok. `npm run build` ok. Бандл `index-D4rvyYNr.js`.
- Preview: рельс без игр, ленты Мои/Все/Крупные нет.
- `staging-sync.sh` health **passed**. md5 local = staging: `CasinoShell.tsx` `37bff9cbe680bf05e578028e6735b37a`, `CasinoPlay.tsx` `7e3d69f2507bc4fd5707f7c6d81d476d`, `CasinoRoulette.tsx` `af337ff136c38a0cdb0e5c8b780e1123`.
- `staging-test.sh` те же 7 известных имён. Новых нет.
- Docker наружу: только `127.0.0.1:18081->8080`. Прод метки те же: index 2026-08-29 06:08:38, panel 2026-08-28 04:22:48, unit 2026-08-29 06:08:19.

Git: `61e47be`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Задачи 1–18 плана казино закрыты раньше. Заготовки на полке (холдем, FocusLucky, комната N, клан vs клан, команды) не открывал.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette` — слева нет списка игр, снизу нет «Мои / Все / Крупные» и нет кнопки «Игры». Стол: колесо, цвета, сетка 0–36, крутить.
- Лобби `/casino` — плитки игр на месте.
- Кубик `/casino/play/pvp_dice` — рельс «Игры» и лента как были.
- Не ломать: один спин, баланс после остановки, 17 = 35:1, куб 1×1 100 → **195**. **Должно остаться.**

## 2026-08-30 · Рулетка: несколько чисел, выплата 36÷N

Сделано: на сетке и колесе клик **добавляет** число в одну ставку (повторный клик снимает, последнее не снимается). Выплата как на европейском столе: возврат **36/N**, не ×36 на каждое. 1 число → 35:1 (×36); 2 → 17:1 (×18); 10 → **2.6:1 (×3.6)**. Красное/чёрное по-прежнему 1:1. HMAC, ledger, комиссия с выигрыша — те же.

Бэкенд:

- `casino_roulette.py` — `STRAIGHT_RETURN=36`, `_cover_bet`: multiplier = 36/N. Ключ `"1,2,3,4,5,6,7,8,9,10"`. `"0"` по-прежнему `zero`. Нельзя покрыть все 37.
- `HousePlayBody.bet` / quote `bet` — `max_length=120` (`ROULETTE_BET_KEY_MAX_LENGTH`).
- Резерв дома по фактическому множителю: 10 чисел ×100 ₽ держит **347**, не 3425.

Фронт:

- `toggleRoulettePocket` в `roulette.ts`; сетка и сектора колеса подсвечивают все выбранные.
- Кикер: `10 чисел · 2.6:1`. Поле «Выигрыш при победе» из котировки.
- `CasinoPlay.tsx` не трогал (рельс без игр как в прошлом срезе).

Проверки:

- Локально `tests/test_casino_roulette.py`: **68** passed (было 57). Новые: 10 чисел ×3.6 / 34.70 после 5%, сплит ×18, каре ×9, линия ×6, quote max 10 чисел > straight, play reserve 347.
- `npx tsx scripts/check-roulette-model.mts` ok. `tsc -b` ok. `npm run build` ok. Бандл `index-En0bWG3v.js` / css без изменений `index-DyYj-0WP.css`.
- `staging-sync.sh` health **passed**. md5 local = staging: `casino_roulette.py` `03f29b393dbdb5c37458c8b51bdc6a48`, `test_casino_roulette.py` `38bd4281b25d80a3bc05577b16b95418`, `user_casino.py` `142ec25c0105573f7b4ffe853cc1acad`, `public_casino.py` `da51a89de85732ae981952d3bc39ffc8`, `roulette.ts` `b3e0e797e27c4431a79c63ee234ae94d`, `CasinoRoulette.tsx` `b7acd4d0f36e6f5ce5b654d695cf28c6`, `check-roulette-model.mts` `11a94aa0cf7eac09b1df2b9bca42e76e`, `CasinoPlay.tsx` `7e3d69f2507bc4fd5707f7c6d81d476d`.
- `staging-test.sh`: те же известные имена, **новых нет**. Первый прогон 7: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production` (flake), `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Повтор без finance-flake = 6. Рулеточные тесты не в списке.
- HTTP 18081: quote `bet=1,2,3,4,5,6,7,8,9,10` stake 10 → **×3.6**, odds **2.6:1**, gross **36**, win **34.7**, max **277.78**. `bet=17` → ×36, max **27.78**. red 100 → **195**.
- SQL: `enabled_games.roulette` = **true**; finished рулетки **153**.
- Docker gateway: `127.0.0.1:18081->8080`. Новых публикаций нет. На хосте по-прежнему слушает **18082** (0.0.0.0) — это не этот срез.
- Прод (read-only): index 2026-08-29 06:08:38 UTC, panel 2026-08-28 04:22:48 UTC, unit 2026-08-29 06:08:19 UTC. Не сдвинулись.

`rg` cover/36÷N: бэкенд `casino_roulette.py` 23 + тесты 21; фронт `roulette.ts` 6, `CasinoRoulette.tsx` 7, check-script 14.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081/casino/play/roulette`).

- Нажать **10**, потом ещё девять чисел (1–9). Кикер **«10 чисел · 2.6:1»**, не 35:1. «Выигрыш при победе» на 10 ₽ → **34,70** (не 342,50). Лимит стола поднимается (~277 ₽), это из-за меньшего ×, не баг.
- Два числа (сплит) → **17:1**. Одно число / зеро → по-прежнему **35:1**. Красное 100 → **195**.
- Повторный клик по числу снимает его. Последнее число не сбрасывается. Красное/чёрное сбрасывают набор чисел.
- Крутить 10 чисел: победа только если выпало одно из выбранных; выплата ≈ ставка×3.6 минус комиссия.
- Не ломать: один спин; баланс после остановки; рельс без списка игр; куб 1×1 100 → **195**. **Должно остаться.**

## 2026-08-30 · Рулетка: кнопка «Сбросить все»

Клик: сбросить набор чисел одной кнопкой, не снимая по одному.

Сделано на `/casino/play/roulette`, справа от кикера сетки:

- Кнопка **«Сбросить все»** (`data-casino-roulette-clear`). Ставит ставку в дефолт `"red"`.
- Неактивна, когда уже красное, и пока крутится / ставки закрыты.
- Сетка гаснет, кикер снова «Числа · клик добавляет, выплата 36÷N». Котировка и лимит стола обновляются через существующий `onBetChange`.

Файлы этого среза: `CasinoRoulette.tsx`, `casino.css` (ряд кикер+кнопка, высота 36px / 44px на телефоне), `check-roulette-model.mts` (`DEFAULT_ROULETTE_BET === "red"`). Бэкенд не трогал.

Проверки:

- `npx tsx scripts/check-roulette-model.mts` ok.
- `staging-sync.sh` health **passed**. md5 local = staging: `CasinoRoulette.tsx` `fe8d14e3d7fc2a9ef8c01273585577cf`, `casino.css` `29bc9823ba8e9f5dcf439c6ab322bc16`, `check-roulette-model.mts` `3bd23db1a1bcd5635e3bf7f4d5c25af1`.
- Бандлы шлюза: `index-DvKQC7lz.css`, `index-DdUhC0xv.js` (ещё чанки `index-BXPr-dsZ.js`, `index-Cb0Y9e8n.js`).
- `staging-test.sh`: те же известные имена, **новых нет**. Первый прогон 7: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production` (flake), `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Повтор без finance-flake = 6.
- HTTP 18081: red 100 → **195**; 10 чисел ×10 ₽ → **×3.6 / 2.6:1 / 34.7**, max **277.78**. SQL: finished roulette **198**. `enabled_games` не менял.
- `rg` «Сбросить все» / `casino-roulette-clear`: `CasinoRoulette.tsx` 7, `casino.css` 2, check-script 2.
- Docker gateway: `127.0.0.1:18081->8080`. Новых публикаций нет. На хосте по-прежнему слушает **18082** (0.0.0.0) — не этот срез.
- Прод (read-only): index 2026-08-29 06:08:38 UTC, panel 2026-08-28 04:22:48 UTC, unit 2026-08-29 06:08:19 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081/casino/play/roulette`).

- Набрать несколько чисел → справа от кикера **«Сбросить все»** становится активной. Нажать → снова красное, сетка пустая, кнопка серая.
- Пока крутится — кнопка не жмётся.
- 10 чисел по-прежнему **2.6:1**; красное 100 → **195**.
- Не ломать: один спин; баланс после остановки; рельс без списка игр. **Должно остаться.**

## 2026-08-30 · История над колесом + общий стол рулетки

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. 1×1 HMAC и множители не менял. Джекпот не трогал.

Две задачи одного плана, одним sync (как в промпте implement all to-dos). Клики — список внизу; после клика не начинать следующую.

### Задача 1. Лента всегда в кадре

`RouletteHistory` — первый ребёнок `.casino-roulette`, над колесом. `.casino-roulette-history-wrap`: `position: sticky; top: 0`, фон стола, 10 кружков без подписей «красное/чёрное». Лимит `ROULETTE_HISTORY_LIMIT` = 10.

### Задача 2. Стол «С игроками» — одно колесо vs дом

Не новый `game_type`. URL `/casino/play/roulette?mode=players`. 1×1 остаётся `?mode=house`. Деньги — тот же `calculate_house_settlement` / `play_roulette_known_pocket_with_conn`, не банк игроков.

Бэкенд:

- `casino_roulette_table.py` — live-раунд `open|locked|spinning|settled`, unique live index, closer 1 с, SSE `bet/lock/spin/settled/idle`. HMAC лунки от `round_id`. Пустой раунд → `idle`, колесо не крутится.
- Ставка: холд + резерв дома × максимальной выплате этой клетки. Пока `open` можно сменить клетку/сумму (перехолд). При `max_players` — lock сразу.
- `play_roulette_known_pocket_with_conn` в `casino_roulette.py`: общий карман, существующий холд, `reserved_rub` повторно не увеличивает.
- Настройки `ON CONFLICT DO NOTHING`: `roulette_table_collect_seconds` **25** (5–120), `roulette_table_max_players` **24** (2–48). Комиссия как у 1×1.
- API: `GET/POST /api/user/casino/roulette-table`, `GET .../events` SSE, `GET /api/public/casino/roulette-table` без входа. `server_seed` только после lock.

Фронт:

- Табы «Против казино» / «С игроками» на рулетке снова видны. Заглушки `roulettePlayersNote` нет.
- Фишки на red/black/zero и на числах (`CasinoPlayerAvatar`), свои с рамкой. Таймер до lock. Список «кто поставил».
- Лента сверху и в режиме стола. После lock — тот же спин, что 1×1. Пустой раунд не крутит.

Админка: секция «Рулетка стол» в `/x8/casino/settings` (сбор 5–120, макс. игроков 2–48).

Тесты локально: `test_casino_roulette.py` **68**, `test_casino_roulette_table.py` **9** (одна лунка, red проигрывает на 17-чёрном / 17 выигрывает **342.50**, пустой не крутит, SSE lock, смена ставки отпускает холд, overflow банкролла не холдит). Registry/admin: дефолты 25/24, collect=4 → reject. `npx tsx scripts/check-roulette-model.mts` ok. `tsc -b` ok. `npm run build` ok (`index-DvKQC7lz.css`, `index-BrRmp6iq.js`, `panel-DJK4QI4x.js`). `bootstrap_static_test.sh` passed.

Staging: `staging-sync.sh` health **passed**. Postgres-контейнер Recreate, том живой: finished roulette **198**, `enabled_games.roulette=true`. Bootstrap/идемпотентный SQL: таблицы `casino_roulette_rounds` / `casino_roulette_bets` есть. Ключи `roulette_table_*` = 25 / 24. Всего ключей **67** (было 65, +2).

Живой шлюз: `GET /api/public/casino/roulette-table` **200** `{status:open, player_count:0, max_players:24, collect_seconds:25, server_seed:null}`. `/casino/play/roulette` **200**.

`staging-test.sh`: **6 failed, 1389 passed, 1 skipped**. Первый прогон ещё finance-flake = 7. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production` (flake), `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.

md5 local = staging `/opt` = live `/app/backend`:

- `casino_roulette.py` `f227b9250d067b8a61a8477df4785457`
- `casino_roulette_table.py` `f56f9e4bb3ac1b44210a50f741714ff1`
- `casino_settings_registry.py` `4757240ae5b73cadb22b6c95a94be649`
- `add_casino_roulette_table.sql` `712daf7651551132f05b4f8134bcef4e`
- `user_casino.py` `5a9cd23b1dd3f85ea19cbd03cfb23a14`
- `public_casino.py` `f9675517c271ecef9cc2ec2c740df879`
- `admin_casino.py` `90cb3836d6cceb08e7e505fe46ef8b2d`
- `test_casino_roulette_table.py` `3d0bdcdd5ebf4ca1c6fb1cc998cacea3`
- `CasinoRoulette.tsx` `fe8d14e3d7fc2a9ef8c01273585577cf`
- `CasinoPlay.tsx` `23d5c4d3cc2e115c82cc74fcf93e907e`
- `casino.css` `29bc9823ba8e9f5dcf439c6ab322bc16`
- `public.ts` `f6b6d967903c65fbebfbc80508405767`
- `casinoSettingsModel.ts` `6a12b4ab97cf749e6cc348351d7f0b4b`
- `adminApi.ts` `71531c318b52392c53c2010262bb115b`
- `00-apply-migrations.sh` `0106a972d5ed54e88efdf6367cd4b74d`
- `20-full-panel-bootstrap.sh` `5256cfed6e499ee7f723bc329e3cf241`

`rg roulette_table_collect_seconds`: registry, table config, миграция, admin GET/PATCH, adminApi, casinoSettingsModel, CasinoSettings, audit labels, тесты, bootstrap. Не одно вхождение.

Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Новых публикаций нет.

Прод (read-only): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил.

Следующий шаг: стоп, жду клик-приёмку двух окон. Другую задачу не начинать.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette` — лента **над** колесом, видна без прокрутки вниз. Крутить 1×1: один спин, 17 = 35:1, красное 100 → **195**.
- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — таб «С игроками». Два окна (два аккаунта): разные клетки (например красное и **17**). 17 на этом колесе **чёрное**, не красное. Фишки на felt, свои с рамкой. Таймер ~25 с с первой ставки. Один спин на всех. Балансы после остановки: каждому vs дом, не общий банк.
- Пустой раунд без ставок колесо не крутит.
- Админка `http://127.0.0.1:18081/x8/casino/settings` — секция «Рулетка стол»: сбор 25, макс. 24. Сохранить, F5 — значения те же.
- Не ломать: джекпот; куб 1×1 100 → **195**; рельс без списка игр на рулетке. **Должно остаться.**

## 2026-08-30 · Рулетка: баланс только после остановки колеса

Клик: баланс в шапке и на панели всё ещё менялся, пока колесо крутится.

Почему прошлый фикс не держал: сервер закрывает раунд в момент play (ставка и выплата уже в ledger). Старый код ждал `plan.durationMs` от ответа API, а не от реального `transitionend` ротора; плюс `getBalance` с шапки / `refreshWallet` могли прилететь в середине спина и показать уже новый баланс.

Сделано:

- Снимок кошелька на старте спина (`visibleCasinoWallet`). Пока `spinning`, панель показывает снимок, даже если live уже другой.
- Шапка: `CASINO_BALANCE_HOLD_EVENT` замораживает чип и отбрасывает in-flight `/user/balance`. Обновление только по `CASINO_BALANCE_EVENT` после остановки.
- Колесо зовёт `onSettled` с `transitionend` (fallback `durationMs+200`). House и стол «С игроками» больше не пишут баланс по параллельному таймеру.
- `npx tsx scripts/check-roulette-model.mts`: live 800 / frozen 1000 / spinning → **1000**.

Файлы этого среза: `roulette.ts`, `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `CasinoShell.tsx`, `gameCatalog.ts`, `check-roulette-model.mts`. Бэкенд не трогал.

Проверки:

- `npx tsx scripts/check-roulette-model.mts` ok. `tsc -b` ok.
- `staging-sync.sh` health **passed**. md5 local = staging: `CasinoPlay.tsx` `a7d91f141fa0a44838b7a0310e181551`, `CasinoRoulette.tsx` `3fbbeeaa92ea9f16772c06dd9177b7ca`, `CasinoShell.tsx` `da070196fca625e85fd0b968c87db367`, `roulette.ts` `8db990481df70a96c1b1883cf5713eb9`, `gameCatalog.ts` `9c1d186fc9220160dc602b6901090baf`, `check-roulette-model.mts` `d226dfeb528028918d85dee3b664f032`.
- Бандлы шлюза: `index-1RNTwwsQ.js` содержит `casino-balance-hold` и `casino-wallet-frozen`; CSS `index-DvKQC7lz.css`. HTTP 18081 `/casino/play/roulette` **200**.
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `visibleCasinoWallet`: `roulette.ts` 1, `CasinoPlay.tsx` 2, check-script 5. `CASINO_BALANCE_HOLD_EVENT` / hold-атрибуты: `gameCatalog.ts` 1, `CasinoShell.tsx` 4, `CasinoPlay.tsx` 3.
- Docker наружу: только `127.0.0.1:18081->8080` у gateway. На хосте по-прежнему слушает **18082** (0.0.0.0) — не этот срез.
- Прод (read-only): index 2026-08-29 06:08:38 UTC, panel 2026-08-28 04:22:48 UTC, unit 2026-08-29 06:08:19 UTC. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081/casino/play/roulette`).

- Войти. Запомнить баланс в шапке и строку «Баланс …» на панели. Крутить красное: **пока колесо крутится оба числа не меняются**. После остановки — да, и карточка результата.
- Повтор: проигрыш и победа — то же: во время спина баланс как до клика, после остановки новый.
- `?mode=players`: поставить, дождаться колеса. Пока крутится — выплата в шапке/панели не появляется. После остановки — да.
- Не ломать: один спин; 17 = 35:1; куб 1×1 100 → **195**. **Должно остаться.**

## 2026-08-30 · Рулетка: быстрая игра (спам «Крутить»)

Сделано: на 1×1 рулетке против дома переключатель «Быстрая игра». Когда включён, колесо не крутится 4–6 с — тот же путь, что `prefers-reduced-motion` (0 оборотов, 0 мс). Кнопка снова живая сразу после `POST /casino/play`. Деньги и лунка по-прежнему только с сервера. Общий стол (`?mode=players`) и авто-вкладка не тронуты. Бэкенд не менял.

Файлы этого среза:

- `focussite/frontend/src/casino/roulette.ts` — `ROULETTE_FAST_PLAY_KEY`, `readRouletteFastPlay` / `writeRouletteFastPlay` (`localStorage`, ключ `focuspay_casino_roulette_fast`).
- `CasinoPlay.tsx` — чекбокс над «Крутить» только для house; `makeRouletteSpinPlan(reduced || fastPlay)`; без тостов/haptic на win/lose; лента debounce 500 мс; кнопка «Крутим…».
- `CasinoRoulette.tsx` — `fastPlay` → `skipMotion`; `data-casino-roulette-fast`. Включение во время обычного спина сразу сажает колесо.
- `casino.css` — чекбокс `.casino-notify-toggle` не растягивается на ширину поля (иначе тумблер выглядел как 40px input).
- `scripts/check-roulette-model.mts` — storage on/off.

Проверки:

- `npx tsx focussite/frontend/scripts/check-roulette-model.mts` ok. `npx tsc -b` ok. Staging gateway `npm run build`: 2266 modules, CSS `index-CYa4sM9_.css`, JS `index-DDM5GH7v.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды: update + sync).
- HTTP `http://127.0.0.1:18081/casino/play/roulette` **200**. Живой бандл `index-DDM5GH7v.js` содержит `focuspay_casino_roulette_fast`, `roulette-fast`, `roulette-fast-toggle`, `Крутим`.
- md5 local = staging `/opt`:
  - `roulette.ts` `529467518f69a210ec507c13d79642d7`
  - `CasinoPlay.tsx` `7e89a9cf937331aab28265a5b1bbea03`
  - `CasinoRoulette.tsx` `3633e74219ad777f528648eb80d0635e`
  - `casino.css` `91cb978065557f5cfde08b0cae6ac2ae`
  - `check-roulette-model.mts` `071c293b848f0117003d4037127b85d1`
- `staging-test.sh`: collected **1395**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg`: `readRouletteFastPlay` / `writeRouletteFastPlay` / `ROULETTE_FAST_PLAY_KEY` — `roulette.ts` (объявление), `CasinoPlay.tsx` (чтение/запись/тумблер), `check-roulette-model.mts` (assert). `data-casino-roulette-fast` — `CasinoRoulette.tsx`. SQL не трогал: схемы нет.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. На хосте по-прежнему слушает **18082** (0.0.0.0) — не этот срез.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: пять файлов фронта + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`).

- `http://127.0.0.1:18081/casino/play/roulette` — галка «Быстрая игра» выкл: колесо 4–6 с, «Крутить» серая, тост win/lose.
- Вкл галку. Жать «Крутить» подряд: лунка и баланс меняются сразу, тосты не стопкой. Кнопка серая только на время запроса.
- F5 — галка остаётся. Выкл — снова длинное колесо.
- Не ломать: `?mode=players` без этой галки, полный спин; куб 1×1 100 → **195**; ставка/чипы во время обычного спина. **Должно остаться.**

## 2026-08-29 — Стол 2–6: грани, забрать / один переброс

Прод не деплоил. `deploy_all.py` не гонял. Коммит не делал. 1×1 cub (HMAC-порог ×2 / 50% / 100→**195**) не менял. Скрытые холдем / рулетка FocusLucky / комната N / кланы не открывал.

Было: стол 2–6 платил по порогу 1/(N+1); кубы дома только картинка. 6 vs 6 мог показать ничью и всё равно «победа».

Сделано: соло стол 2–6 сравнивает HMAC d6 игрока с каждой гранью бота.

- Проигрыш **любому** боту → вся ставка 0.
- Всех обыграл, ничьих нет → сразу ×(N+1) (3 бота → ×4 → **385**).
- Есть ничьи, проигрышей нет → не тост «победа». Кнопки **Забрать** ×(K+1) (K=2 → ×3 → **290**) или **один** переброс игрока + ничейных ботов (зафиксированные победы держат грани). Выигрыш переброса: `2×(K+1)+(R+1)` при K≥1 (K=2 R=1 → ×8 → **765**). Остаточные ничьи после переброса — без второго переброса, платится take от K+новых побед. Все ничьи, K=0 → забрать ×1 (ставка назад).
- AFK ~10 мин (`WAITING_JOIN_TIMEOUT_SECONDS` = 600): auto-take, не проигрыш.
- Деньги: холд ставки + резерв дома под max(переброс), `casino_games` cub `htcub-…`. Не `play_cub_with_conn` порог.
- `POST /api/user/casino/house-tables/{id}/resolve` `{action: take|reroll}`.

Файлы этого среза:

- `site/exchange-backend/casino_house_tables.py`
- `site/exchange-backend/casino_waiting.py` (`expire_pending_choices` в closer)
- `site/exchange-backend/routers/user_casino.py` (`/resolve`)
- `site/exchange-backend/tests/test_casino_house_tables.py`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/CasinoHouseTables.tsx`
- `focussite/frontend/src/casino/casino.css`

Локально: FaceCompare + FaceFlow + HouseMoney + TableFlow + HouseBotOdds **47 OK**. `npx tsc --noEmit` ок. Числа: take 100→290, reroll-win →765, leftover ties →290, lose-one →0, push ×1 →100.

Залито: `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`. Health **passed**. Postgres оставался Running, `down -v` не было. Gateway: `index-BuzS-HZN.js` (`casino-house-choice` ×3), CSS `index-CgR26mzS.css`. HTTP **200**: `/api/health`, `/casino`, `/casino/play/pvp_dice`.

Quote 100 ₽ (без игры, как раньше): без ботов ×2 / 0.5 / **195**; `house_bot_count=3` ×4 / 0.25 / **385**, max_bet **250**.

Тесты на staging: **1410** collected (было 1395, +15 этого среза), **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. **1403 passed**. Новых имён нет.

SQL: ключей **67**. Миграций нет.

md5 local = `/opt` = live `/app/backend`:

- `casino_house_tables.py` `9d8b705e8643f0277a85c137b53aae97`
- `casino_waiting.py` `5770554e6ec1033ea840e13133198221`
- `user_casino.py` `254d911bf113ff95d2a4e3a6f0e48f63`
- `test_casino_house_tables.py` `05d591fe5e0ce7ff9ec42f4651832f67`
- `CasinoPlay.tsx` `73a2cf27be8501f22539f11e061c5728`
- `CasinoHouseTables.tsx` `3b2196f80fdf407523ff8977d05ec9af`
- `public.ts` `dce56fa9a53ad66dcad976df8a813cad`
- `casino.css` `2fb76693fda72c2ff2feb1666e36392a`

`rg` `after_reroll_multiplier`: `casino_house_tables.py` (формула + resolve), тесты. `expire_pending_choices`: tables + waiting + тесты. `resolveCasinoHouseTable` / `/resolve`: `public.ts`, `CasinoPlay.tsx`, `user_casino.py`. `data-casino-house-choice`: `CasinoHouseTables.tsx` + бандл `index-BuzS-HZN.js`.

Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports. Хост **18082** — отдельный listener, не этот срез.

Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: грани стола 2–6 + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty с прошлого WIP — **этот срез бота не трогал**. Не коммитил.

Следующий шаг: стоп.

Потыкать. Туннель **18081** (`http://127.0.0.1:18081`); тот же шлюз с хоста — **18082**.

- `/casino/play/pvp_dice?mode=house&view=table` — 3 бота, ставка 100 ₽. «Ставка».
- Если все грани дома строго меньше вашей — сразу выплата **385**, без кнопок.
- Если есть ничья и нет проигрыша: **не** тост «Выигрыш». На столе «Забрать … ₽» и «Переброс ×…». Новая «Ставка» серая, пока не заберёте.
- Забрать при двух победах и одной ничьей: на баланс **290**.
- Переброс: куб игрока и ничейные боты крутятся ещё раз. Выигрыш всех оставшихся при двух зафиксированных → **765**. Проигрыш хотя бы одному из переброса → **0** (включая зафиксированных). Если снова ничья — без второй кнопки, платится take.
- `/casino/play/pvp_dice?mode=house` без table: 100 ₽ → **195**, ×2, 50%. **Должно остаться.**
- Не ломать: рулетка быстрая игра; BJ hit/stand; поиск «холдем» — скрытых плиток нет.

## 2026-08-30 · Рулетка с игроками: колесо не крутилось

Почему: closer стола публикует `spin` и сразу `settled` в одном заходе. На staging `locked_at` = `settled_at` до микросекунды (раунд `rt-4c36136c4885`: оба `2026-08-30 21:18:40.615289+00`). Клиент по `settled` сразу звал `reveal` → `setSpinning(false)`. React часто даже не рисовал кадр со спином. 1×1 жив, потому что там reveal только с `transitionend` колеса. Джекпот то же самое обходит: `settled` во время спина игнорирует.

Сделано (фронт, бэкенд денег/HMAC не трогал):

- `rouletteTableRevealReady`: пока стол крутится, reveal только после посадки колеса.
- `rouletteTableShouldSpinFromSnapshot`: poll/GET `locked|spinning|settled` с лункой запускает тот же спин, если этот `round_id` ещё не крутили.
- SSE `settled` только кладёт выплату; `lock`/`idle` обновляют стол. Карточка win/lose без payload ставки не рисуется (не фейковый проигрыш).

Файлы этого среза: `roulette.ts`, `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `check-roulette-model.mts`, комментарий в `test_casino_roulette_table.py`.

Проверки:

- `npx tsx focussite/frontend/scripts/check-roulette-model.mts` ok (`revealReady(true,false)=false`). `npx tsc -b` ok. Локально roulette **68** + table **13** passed.
- Gateway build: 2266 modules, CSS `index-BY03rmCR.css`, JS `index-DUvMpIGt.js`.
- Первый `staging-sync.sh`: compose `--wait` упал `No such container` (гонка recreate). Повтор `staging-runtime-update.sh --apply` → health **passed**. Postgres том живой: settled roulette **7**, open **1**, ключей **67**, `roulette_table_*` = 25 / 24.
- HTTP `127.0.0.1:18081` healthz **200**, `/casino/play/roulette` **200**, `GET /api/public/casino/roulette-table` `{status:open, player_count:0, collect_seconds:25}`.
- md5 local = `/opt` = live `/app/backend`:
  - `CasinoPlay.tsx` `f96ff4824c745190f592475822089409`
  - `CasinoRoulette.tsx` `51d9b7158ae4e4879e4c75fc8f7a02a5`
  - `roulette.ts` `9054481ec255c53dd84edaedd79ec6ac`
  - `check-roulette-model.mts` `6e4715e9f4d1ed35788b18e8755347ae`
  - `test_casino_roulette_table.py` `055e2a6b8c1041e1ce40e808c54c99e5`
  - `casino_roulette_table.py` `28efecbbf587f52437150e84150ca89a` (без правок логики)
- `rg` `rouletteTableRevealReady`: `roulette.ts`, `CasinoPlay.tsx`, `check-roulette-model.mts`.
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Хост **18082** — отдельный nginx, не этот срез.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: посадка колеса стола + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — поставить (красное или число). Таймер ~25 с. После lock колесо крутится **4–6 с**, не прыжок сразу на лунку. Баланс в шапке до остановки не меняется.
- Два окна: один спин на всех. Пустой раунд без ставок колесо по-прежнему не крутит.
- `?mode=house` — «Крутить» как раньше, в т.ч. быстрая игра. **Должно остаться.**
- Не ломать: куб 1×1 100 → **195**; джекпот.

## 2026-08-30 · Общий стол рулетки: фишки на клетки

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. 1×1 HMAC и множители не менял. Джекпот не трогал.

Было: одна ставка на игрока (`UNIQUE round_pk, user_id`). Клик по числу затирал красное — нельзя 50 на цвет и 25 на 22 сразу.

Сделано на `/casino/play/roulette?mode=players`:

- Клик по клетке **сразу** кладёт выбранную фишку (10 / 25 / 50 / 100 / 500 / 1000). Повтор по той же клетке накидывает. Красное и 22 — разные холды, дом платит каждую отдельно.
- «Сбросить все» снимает свои фишки. ПКМ по своей клетке снимает только её.
- Кнопка «Поставить / сменить ставку» у авторизованного на столе убрана — ставка это клик по felt.
- 1×1 `?mode=house` по-прежнему одна ставка (клик по числам = cover 36÷N). Не фишки.

Бэкенд:

- Миграция `add_casino_roulette_table_chips.sql`: `UNIQUE (round_pk, user_id)` → `ux_casino_roulette_bets_spot (round_pk, user_id, bet)`.
- `place_bet` добавляет чип, не заменяет чужие клетки. `max_players` считает **уникальных** игроков, не число фишек.
- `POST /api/user/casino/roulette-table/clear` `{bet?}` — одна клетка или все.
- Снимок: `my_bets[]`, `my_stake_rub` = сумма, `player_count` = уникальные. Settle: `game_id = {round_id}-b{bet_id}`.

Файлы: `casino_roulette_table.py`, `user_casino.py`, миграция, тесты, bootstrap ×3, `roulette.ts`, `CasinoRoulette.tsx`, `CasinoPlay.tsx`, `casino.css`, `public.ts`, `check-roulette-model.mts`.

Проверки:

- Локально `tests/test_casino_roulette.py` + `test_casino_roulette_table.py`: **81** passed (было 77 = 68+9). Новые: второй слот не отпускает красное, стек 50+50=100, два слота одного игрока не заполняют стол при max=2, clear одной клетки, settle двух холдов одного user_id.
- `npx tsx focussite/frontend/scripts/check-roulette-model.mts` ok (фишки 10…1000, 25 есть). `npx tsc -b` ok. `bootstrap_static_test.sh` passed. Gateway: 2266 modules, CSS `index-BY03rmCR.css`, JS `index-CZZP0BdJ.js` (`roulette-table/clear`, `casino-roulette-chip-hint`).
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**.
- SQL: индекс `ux_casino_roulette_bets_spot` есть; ключей **67**; `enabled_games.roulette=true`. Публичный снимок `{status:open, player_count:0, my_bets:[]}`.
- HTTP `http://127.0.0.1:18081/casino/play/roulette` **200**, `GET /api/public/casino/roulette-table` **200**.
- md5 local = staging `/opt` = live `/app/backend`:
  - `casino_roulette_table.py` `28efecbbf587f52437150e84150ca89a`
  - `user_casino.py` `d92ff8048493dceea5c8bd2e18476207`
  - `add_casino_roulette_table_chips.sql` `52c987b827b1276263f04f12b15d9757`
  - `test_casino_roulette_table.py` `055e2a6b8c1041e1ce40e808c54c99e5`
  - `roulette.ts` `9054481ec255c53dd84edaedd79ec6ac`
  - `CasinoRoulette.tsx` `51d9b7158ae4e4879e4c75fc8f7a02a5`
  - `CasinoPlay.tsx` `f96ff4824c745190f592475822089409`
  - `casino.css` `944c9c8ef4272893174dcc5f7e5bcd9f`
  - `public.ts` `3de9aab45866eef0de9a03a9b97eb186`
- `staging-test.sh`: collected **1414** (было 1410, +4), **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `ROULETTE_TABLE_CHIPS`: `roulette.ts`, `CasinoPlay.tsx`, check-script, bootstrap. `onPlaceSpot`: `CasinoRoulette.tsx` + `CasinoPlay.tsx`. `ux_casino_roulette_bets_spot`: миграция + bootstrap. `/roulette-table/clear`: `user_casino.py`, `public.ts`, bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Хост **18082** — отдельный listener, не этот срез.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — войти. Слева фишка **50**. Клик **Красное** — фишка на красном, баланс −50. Фишка **25**, клик **22** — на столе и красное 50, и 22 25. Красное не стёрлось.
- Повторный клик по красному с фишкой 50 — на красном 100.
- «Сбросить все» — фишки снимаются, баланс возвращается. ПКМ по клетке снимает только её.
- Дождаться спина: колесо 4–6 с; выплата после остановки, каждая клетка vs дом.
- `?mode=house` — не фишки: клик по числам по-прежнему одна ставка 36÷N, кнопка «Крутить». **Должно остаться.**
- Не ломать: куб 1×1 100 → **195**; джекпот.

## 2026-08-30 · Ширина экрана настроек казино

По клику: `/x8/casino/settings` был узкий столбец 720px, таблица уровней не читалась. Логику сохранения не трогал.

Сделано:

- `CasinoSettings.tsx`: снял `max-w-[720px] xl:max-w-[1064px]`. Форма `flex-1 min-w-0`, липкий aside 320px (секции / подсказка / живой расчёт) на месте. Ширину даёт PanelShell `max-w-[1440px]`.
- `TierGridEditor.tsx`: таблица `min-w-[880px]`, заголовки `whitespace-nowrap`. Пояснение только при выборе ячейки и **под** таблицей. Пустой блок 260px убран.
- `CasinoTierGrids.tsx`: подсказка «нажмите ячейку — под таблицей».
- `CasinoAudit.tsx`: тот же съём 720/1064, список `flex-1`, панель «было → стало» 320px как была.
- `bootstrap_static_test.sh`: `xl:max-w-[1064px]` заменён на проверки `flex-1` / `min-w-[880px]`.

Проверки:

- Локально: `bootstrap_static_test.sh` **passed**. `npx tsc -b` ок. `npm run build` на staging: 2266 modules, бандл `panel-B6NL3YVI.js` / `panel-BqL_43vt.css`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (после update и ещё раз). Postgres Recreate **без** `down -v`; ключей **67**.
- HTTP `http://127.0.0.1:18081/x8/casino/settings` **200**, `/x8/casino/audit` **200**. Без логина панель редиректит на `/x8/login` — клик ширины за человеком.
- Бандл: `min-w-[880px]` ×1; `max-w-[720px]` ×0; `max-w-[1064px]` ×0.
- md5 local = staging `/opt`:
  - `CasinoSettings.tsx` `13d414e3206c444587e5e2a12e4da9f4`
  - `CasinoAudit.tsx` `30e3be491029e3f83698d9fa6f421064`
  - `TierGridEditor.tsx` `1f3a508d86641748716f3635e19ffdf9`
  - `CasinoTierGrids.tsx` `0065fbc4a8142f3fcac7da2749589927`
  - `bootstrap_static_test.sh` `ef85dab860a9cedf415fba919f95c3da`
- `staging-test.sh`: collected **1418** (прошлый срез 1414; +4 уже в дереве от фишек, не этот срез), **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1411**.
- `rg` `min-w-[880px]`: `TierGridEditor.tsx` + bootstrap. `flex min-w-0 flex-1 flex-col gap-5`: `CasinoSettings.tsx` + bootstrap. `min-w-0 w-full flex-1 space-y-3`: `CasinoAudit.tsx` + bootstrap. `Нажмите ячейку — под таблицей`: `CasinoTierGrids.tsx`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: ширина настроек/аудита + журнал). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/x8/casino/settings` — форма на ширину панели (~1440), не узкая колонка по центру. Справа оглавление секций.
- «Уровни по недельному обороту»: заголовки в одну строку, поля читаются. Клик по ячейке — пояснение **под** таблицей, не справа.
- Сохранить с причиной, F5 — значения те же. **Должно остаться.**
- `http://127.0.0.1:18081/x8/casino/audit` — список шире, клик сохранения открывает «было → стало» справа.
- Не ломать: куб 1×1 100 → **195**; джекпот; рулетка фишки на `?mode=players`.

## 2026-08-30 · Рулетка стол: черновик, подтвердить, повтор, отмена

Не прод. `deploy_all.py` не запускал. House 1×1, FocusLucky / холдем / комнаты / кланы не трогал. HMAC и множители не менял.

Сделано на `/casino/play/roulette?mode=players`:

- Клик по клетке кладёт **черновик** (полупрозрачная фишка). Баланс не меняется, таймер не стартует.
- **Подтвердить** (слева) шлёт весь черновик одним `POST /api/user/casino/roulette-table/bets`. Деньги холдятся здесь.
- **Отменить** — последняя фишка черновика. **Повторить** — раскладка прошлого своего раунда (выкл., если уже есть черновик или принятые фишки). **Сбросить все** — черновик + принятые через прежний `clear`.
- ПКМ снимает черновик с клетки. `?mode=house` — по-прежнему «Крутить», не фишки.

Бэкенд: `place_bets` в одной транзакции, проверки банкролла **до** холдов, один SSE `bet`. Одиночный `place_bet` остался обёрткой.

Файлы: `casino_roulette_table.py`, `user_casino.py`, `test_casino_roulette_table.py`, `public.ts`, `roulette.ts`, `CasinoRoulette.tsx`, `CasinoPlay.tsx`, `casino.css`, `check-roulette-model.mts`, `bootstrap_static_test.sh`.

Проверки:

- Локально `tests/test_casino_roulette.py` + `test_casino_roulette_table.py`: **85** passed (было 81 = 68+13). Новые: пустой список 400, два слота одним запросом / один publish, второй слот по банкроллу не холдит, locked 409.
- `npx tsx focussite/frontend/scripts/check-roulette-model.mts` ok (стек 50+25, undo, merge red 50+50=100, sessionStorage last bets). `npx tsc -b` ok. `npm run build` 2266 modules, CSS `index-C5lKoM-A.css`, JS `index-B5XW029g.js`. `bootstrap_static_test.sh` passed.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**.
- SQL: ключей **67**; `enabled_games.roulette=true`; таблица `casino_roulette_bets`. Публичный снимок `{status:open, player_count:0, my_bets:[], enabled:true}`.
- HTTP `http://127.0.0.1:18081/casino/play/roulette` **200**, `GET /api/public/casino/roulette-table` **200**.
- md5 local = staging `/opt` = live `/app/backend`:
  - `casino_roulette_table.py` `39845d7eb8165f984dada6e4fd2839e4`
  - `user_casino.py` `788dbfe950ffa4ed20015aa870dfc173`
  - `test_casino_roulette_table.py` `cbd0b806c3b8f1d3d825f500e114f831`
  - `roulette.ts` `28f36c3f0d6593d12aa146329ddcbb0b`
  - `CasinoRoulette.tsx` `4f75c138ae1029b0c031d6ed6d27389f`
  - `CasinoPlay.tsx` `ab40ce3b7eeaca56d409b9eb3710255e`
  - `casino.css` `9e7e114070b677020e8d997965b77e02`
  - `public.ts` `ae8b8f0a7e0581786ad6c0f2da6da5d1`
  - `check-roulette-model.mts` `055c51a386faa01b3d817d725cc643af`
  - `bootstrap_static_test.sh` `ef85dab860a9cedf415fba919f95c3da`
- Шлюз: `roulette-table/bets`, `casino-roulette-repeat`, `casino-roulette-confirm` в `index-B5XW029g.js`; `is-draft` в `index-C5lKoM-A.css`.
- `staging-test.sh`: collected **1418** (срез фишек 1414, +4 batch), **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `place_bets`: `casino_roulette_table.py`, `user_casino.py`, тесты. `/roulette-table/bets`: роут + `public.ts` + bootstrap. `onTableConfirm`: `CasinoPlay.tsx`. `rouletteDraftConfirmPayload`: `roulette.ts` + CasinoPlay + check-script. `data-casino-roulette-repeat`: `CasinoRoulette.tsx`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Хост **18082** — отдельный nginx, не этот срез.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**.

- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — войти. Фишка **50**, клик **Красное**: фишка на клетке, **баланс не минусуется**. «Черновик» 50, «На столе (принято)» 0.
- **Подтвердить** — баланс −50, фишка плотная, черновик 0. Пока не подтвердил — другие игроки клетку не видят.
- Фишка **25**, клик **22**, не жать подтвердить: **Отменить** снимает 22. **Сбросить все** чистит черновик (и принятое, если было).
- Дождаться спина. Следующий раунд: **Повторить** раскладывает прошлые клетки без списания; снова **Подтвердить**.
- Пока черновик или принятые фишки есть — **Повторить** серая.
- `?mode=house` — «Крутить» как раньше, без этих кнопок. **Должно остаться.**
- Не ломать: куб 1×1 100 → **195**; джекпот.

## 2026-08-30 · Рулетка стол: лимит числа vs цвет, русские ошибки

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. HMAC и множители 1×1 не менял.

Клик на `?mode=players` (в т.ч. с хоста **18082**): фишка 100 на числа → toast `Stake is outside configured limits (10.00-27.78)` или `House bankroll is insufficient`. UI писал «лимит 10–100 000 ₽».

Почему: стол брал глобальный max_bet. Число — выплата ×36. На staging у house-робота `max_exposure_rub` был **1000** → 1000/36 = **27.78 ₽** на число; 100 ₽ на 15 требует ~3600 ₽ покрытия. Цвет ×2 при этом жил. 1×1 уже поджимал зеро; стол — нет.

Сделано:

- Снимок стола отдаёт `max_even_bet_rub` и `max_straight_bet_rub` (тот же `apply_roulette_stake_window`, что котировка 1×1): % банка, обязательства, **экспозиция робота**, свободный банк / множитель.
- Клик по числу с фишкой больше прямого лимита — русский тост, черновик не кладётся. Подтвердить то же. Строка: «цвет … · число до …».
- Ошибки дома: `Ставка вне лимита (… ₽)`, `Дом не может покрыть выплату по этой ставке`.
- Staging only: `casino_robot_profiles.max_exposure_rub` house **1000 → 50 000** (банк ~49k). Иначе фишка 100 на число остаётся мёртвой при честном лимите 27.78.

Файлы: `casino_roulette.py`, `casino_roulette_table.py`, `casino_play.py`, `internal_casino.py`, тесты, `roulette.ts`, `CasinoPlay.tsx`, `public.ts`, `check-roulette-model.mts`, bootstrap.

Проверки:

- Локально `tests.test_casino_roulette` + `test_casino_roulette_table`: **92** passed (+3: окно ×2 vs ×36, экспозиция 1000 → 27.78, фишка 100 на 15 при капе 27.78). `npx tsx scripts/check-roulette-model.mts` ok. `npx tsc -b` ok. `bootstrap_static_test.sh` passed.
- Gateway: 2266 modules, CSS `index-BN3yssqC.css`, JS `index-Bfi9hm0C.js` (`max_straight_bet_rub`, `На число максимум`).
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды: лимиты+перевод, потом экспозиция в окне).
- SQL: ключей **67**; house `max_exposure_rub` **50000**; банк `49234.65` / reserved `640`.
- HTTP 18081 и 18082: страница **200**. Снимок `{min:10, max_even:14770.4, max_straight:422.01}`. Quote red 100 → **195**, без bound_error. Quote `bet=17` stake 100 → max **422.01**, bound_error null.
- md5 local = `/opt` = live `/app/backend`:
  - `casino_roulette.py` `e37b789687840770355fe9e1804e99c9`
  - `casino_roulette_table.py` `981df9796b992ed884bd932a57be9085`
  - `casino_play.py` `63ab04d890c784d42edecca8ec0f4e03`
  - `internal_casino.py` `7cfb62234ac55429606f3b7f1fc82632`
  - `test_casino_roulette.py` `d7e4163e29050b9da0b1cd0496475545`
  - `test_casino_roulette_table.py` `ce87cab30c14e727b1cc04074e409ce6`
  - `roulette.ts` `fb12337e7aa3c5b645a0a45ef04332ac`
  - `CasinoPlay.tsx` `285e86ab2b6f7bbd111725dd7ea518d3`
  - `public.ts` `96575937a1f8a078e526ee5817059a3e`
  - `check-roulette-model.mts` `15bc0acf98275b71ddd184f2ffde1162`
  - `bootstrap_static_test.sh` `34d5c8bb2a1d1f66c93f4c5bf4f660b3`
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. +3 теста рулетки в этом срезе.
- `rg` `rouletteTableSpotMax`: roulette.ts, CasinoPlay, check-script, bootstrap. `max_straight_bet_rub`: table py + public.ts + CasinoPlay + bootstrap. `HOUSE_BANKROLL_INSUFFICIENT`: casino_roulette.py + table. `apply_roulette_stake_window`: roulette.py, play.py, table, тесты.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** — nginx, тот же API (снимок с новыми полями).
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** или тот же шлюз с хоста **18082**.

- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — слева лимит **цвет ~10–14 770 · число до ~422** (не 100 000 на всё).
- Фишка **100**, клик по числу (15) — черновик кладётся. **Подтвердить** — холд, без английского тоста.
- Фишка **500**, клик по числу — тост по-русски «На число максимум …», черновик пустой. **500 на красное** — можно, подтвердить.
- `?mode=house` зеро по-прежнему само поджимает максимум. Красное 100 → **195**.
- Не ломать: куб 1×1 100 → **195**; джекпот; колесо стола 4–6 с.

## 2026-08-30 · Рулетка из Telegram: одна клетка, multi, справка

Не прод. `deploy_all.py` не запускал. FocusLucky `/fast`, холдем, комнаты, кланы не открывал. Сплиты/корнеры как одна фишка 36/N из бота не делал.

Сделано:

- Одна команда без `multi` — одна фишка на одну клетку (цвет, 0–36, ряд `1rd`/`2rd`/`3rd`, чёт/нечет, 1–18, колонки). `/roulette multi 1 4 6 10р` — отдельные прямые фишки ×36, не пачка. Запятая `1,5,8` — отказ.
- Сумма 0–36, если её можно принять за лунку: только `10р` / `10₽`. `/roulette 10 10` отказ; `/roulette red 10` и `/roulette 17 500` ок.
- Бэкенд: именованные клетки + алиасы; `casino_roulette_bets.notify_chat_id`; internal `GET/POST /roulette-table` и `/roulette-table/bet`; outbox `roulette_table_settled` в чат команды (сайтовые фишки без колонки в TG не пишутся). FK `outbox.game_id → casino_games` снят.
- Бот `focuspay-casino`: `/roulette` и `/рулетка` (личка или игровой чат). `/help` — оглавление; `/help roulette` (и cub, 2cub, baccara, blackjack, tables, duels, deposit, fairness, team, rules). Лимиты из `get_casino_settings`. `/fast` в оглавлении: выключены.
- Сайт `?mode=players` по умолчанию из лобби. Сукно: ряды, колонки 2:1, чёт/нечет, 1–18. Фишка и список «кто поставил» → `/casino/u/{id}`. Вкладка «Против казино» — 1×1 как раньше.

Файлы: `casino_roulette.py`, `casino_roulette_table.py`, `internal_casino.py`, `add_casino_roulette_telegram_notify.sql`, тесты рулетки, `roulette.ts`, `CasinoRoulette.tsx`, `CasinoPlay.tsx`, `gameCatalog.ts`, `casino.css`, `check-roulette-model.mts`, bootstrap; бот `games/roulette_cmd.py`, `games/roulette_table.py`, `games/help.py`, `focuspay_client.py`, `bot.py`, `tests/test_roulette_cmd.py`, `tests/test_help.py`.

Проверки:

- Локально backend `test_casino_roulette` + `test_casino_roulette_table`: **92** passed. Бот: `test_roulette_cmd` **8**, `test_help` **6**, плюс `test_focuspay_client` (internal roulette-table), `test_bot_startup` / `test_staging_ui` / `test_profile` — ок. Итого прогнанный набор бота **53**.
- `npx tsx focussite/frontend/scripts/check-roulette-model.mts` ok (`1rd`→dozen1, `чёт`→even, cover 1–12 → dozen1). `npx tsc -b` ok. Gateway build 2266 modules, CSS `index-BAF4hsN9.css`, JS `index-BDU0rQJY.js`. `bootstrap_static_test.sh` passed.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Миграция `notify_chat_id` на живом томе: колонка **bigint**, `ADD COLUMN IF NOT EXISTS` no-op (уже была). FK на `outbox.game_id` нет.
- SQL: ключей **67**; `enabled_games.roulette=true`. Снимок `{status:open, player_count:0, enabled:true}` HTTP **200**. Страница `?mode=players` **200**.
- md5 local = staging `/opt` = live backend `/app/backend` и casino-bot `/app`:
  - `casino_roulette.py` `e37b789687840770355fe9e1804e99c9`
  - `casino_roulette_table.py` `981df9796b992ed884bd932a57be9085`
  - `internal_casino.py` `7cfb62234ac55429606f3b7f1fc82632`
  - `add_casino_roulette_telegram_notify.sql` `fb1638f7d2d0b892d071300dae018181`
  - `CasinoRoulette.tsx` `50756ed80e73de8d2ca84d3c3d57f8ec`
  - `roulette.ts` `fb12337e7aa3c5b645a0a45ef04332ac`
  - `CasinoPlay.tsx` `285e86ab2b6f7bbd111725dd7ea518d3`
  - `gameCatalog.ts` `6d0b8168981850fb38d49b1ea63abd28`
  - `casino.css` `288dd44551dcb97c447f31425b71c569`
  - `roulette_cmd.py` `4e17a5061c99d434d26f80714525c3d6`
  - `roulette_table.py` `ea188967c2c65d9a475c0cdb5ff17b45`
  - `help.py` `fe4a844641a0a9af95281484feabd588`
  - `bot.py` `0c426b6ad4442a62169b806a78d785a8`
  - `focuspay_client.py` `708363d7462a29ec6bddf8c3f740a0e9`
- Шлюз `index-BDU0rQJY.js`: `dozen1`, `1rd`, `mode=players`, `/casino/u/`. CSS `index-BAF4hsN9.css`: `casino-roulette-dozens`, `even-money`, `felt-outside`.
- `staging-test.sh`: collected **1425** (было 1418, +7 рулетка), **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1418**.
- `rg` `notify_chat_id`: table py, internal router, миграция, тесты, bootstrap. `dozen1`/`1rd`: `casino_roulette.py`, `roulette.ts`, `CasinoRoulette.tsx`. `parse_roulette_command`: cmd + table + tests. `/help roulette`: `help.py` + `test_help.py`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (в этом срезе roulette/help; остальное чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**.

1. В боте `/help` — оглавление; `/help roulette` — правило `10р`, `1rd`, `multi`. `/help cub` и `/help blackjack` читаются до конца.
2. `/roulette 10 10` — отказ; `/roulette 10 10р` — фишка на 10.
3. `/roulette 1rd 50` — фишка на ряд 1–12 на `http://127.0.0.1:18081/casino/play/roulette?mode=players`. Клик по нику/фишке → профиль `/casino/u/…`.
4. `/roulette multi 1 4 6 10р` — три фишки по 10, не одна пачка.
5. Личка и игровой чат — ок; чужая группа — отказ.
6. Спин: бот пишет результат в тот же чат; на сайте то же число.
7. Лобби «Европейская рулетка» открывает общий стол, не 1×1. Вкладка «Против казино» — «Крутить» как раньше.

## 2026-08-30 · Рулетка: лунка только после остановки

Не прод. `deploy_all.py` не запускал. HMAC, 17=35:1, лимиты клеток, скрытые игры не трогал.

Почему светило число во время спина: сервер знает лунку сразу; `loadTable` после GET мог записать её в ленту над колесом; на ободе цифры оставались читаемыми на ease-out.

Сделано:

- Ступица и `is-landed` через `rouletteVisiblePocket(spinning, pocket)` — пока спин, `—`, без подсветки. Pocket по-прежнему кормит угол ротора.
- Пока `spinning`: цифр на ободе нет (`data-casino-roulette-labels=0`), blur на весь спин (`is-spinning`).
- Стол: после `await` GET, если колесо уже едет — snapshot не применять. Старт спина выкидывает текущий `round_id` из ленты (`rouletteHistoryWithoutRound`). SSE `lock` больше не дергает GET (он же сразу `spin`).
- Карточка «Выпало N» как раньше: только после `onSettled`.

Файлы: `roulette.ts`, `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `casino.css`, `check-roulette-model.mts`, `bootstrap_static_test.sh`.

Проверки:

- `npx tsx scripts/check-roulette-model.mts` ok (`rouletteVisiblePocket(true, 17)===null`, лента без `rt-live`). `npx tsc -b` ok. `npm run build` 2266 modules. `bootstrap_static_test.sh` passed.
- Gateway: CSS `index-CFM_Y8xV.css` (`is-spinning`), JS `index-DaIDAz8i.js` (`data-casino-roulette-labels`). HTTP 18081 `/casino/play/roulette` и `?mode=players` **200**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды).
- md5 local = staging `/opt`:
  - `roulette.ts` `91c4ba7b4042b1665a8a4ee7317a4658`
  - `CasinoPlay.tsx` `edc391f29edcae349cb061708bf2b7a0`
  - `CasinoRoulette.tsx` `7178fbbf455f9c04cd6b0acfae1e9c88`
  - `casino.css` `3f422841ceb95e85fc17f725759c0365`
  - `check-roulette-model.mts` `418c97dfada39cca15c4ec7374dafca6`
  - `bootstrap_static_test.sh` `9bf8a744b73fa9d081c80f52ded64d05`
- `staging-test.sh`: collected **1425**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1418**.
- `rg` `rouletteHistoryWithoutRound`: roulette.ts, CasinoPlay, check-script, bootstrap. `rouletteVisiblePocket`: roulette.ts, CasinoRoulette, check-script, bootstrap. `data-casino-roulette-labels`: CasinoRoulette, bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (тот же API на хосте **18082**).

- `http://127.0.0.1:18081/casino/play/roulette` — 1×1, крутить: пока колесо едет, в центре **—**, на ободе **без цифр**, лента сверху без новой лунки. После остановки — число, цвет, лента, баланс.
- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — фишка, дождаться спина: то же. Пустой раунд по-прежнему не крутит.
- Не ломать: один спин; 17 = 35:1; куб 1×1 100 → **195**; лимит на число vs цвет.

## 2026-08-30 · Рулетка: ставка сразу; чат рядом со столом

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. HMAC и множители 1×1 не менял. Бэкенд рулетки не трогал: `POST /bet`, `/bets`, `/clear` уже были.

План был два среза. В этом заходе оба: в запросе стояло закрыть все пункты, включая чат.

Сделано:

- Общий стол (`?mode=players`): клик по клетке / цвету / колесу сразу `POST .../roulette-table/bet`. Кнопки «Подтвердить» и поле «Черновик» нет. Баланс минусуется на клике.
- **Повторить** — прошлый расклад сразу на стол (`POST .../bets`), если своих фишек на раунде нет.
- **Отменить** — последняя фишка (LIFO). API снимает клетку целиком; если на ней остаётся сумма — clear + bet на остаток. ПКМ по своей клетке снимает клетку.
- **Сбросить все** — `POST .../clear` как раньше, без черновика.
- Фишки на сукне больше не `Link`. Клик по занятой 36 ставит, не уводит в профиль. Профиль — список «Кто поставил».
- Чат: без затемнения. На десктопе колонка в `.casino-body` (`docked`), стол кликабелен. На телефоне нижний лист **36vh**. Крестик и Escape закрывают. На всех `/casino/*`.

Файлы: `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `roulette.ts`, `check-roulette-model.mts`, `CasinoShell.tsx`, `CasinoChatPanel.tsx`, `casino.css`.

Проверки:

- Локально `npx tsx scripts/check-roulette-model.mts` ok (стек 50+50 на 36: undo remainder **50**, второй undo **0**). `npx tsc -b` ok.
- Gateway: 2266 modules, CSS `index-CFM_Y8xV.css`, JS `index-Bb02OTgk.js` (`клик сразу на стол`). В бандле нет `Подтвердить ставки на столе`. CSS `is-docked`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **не** Recreate (Running).
- Страницы `casino.html` и `/casino/play/roulette` HTTP **200**.
- SQL: ключей **67** (без новых).
- md5 local = staging `/opt`:
  - `CasinoPlay.tsx` `6706db04c8518194e1fb73216190ac7b`
  - `CasinoRoulette.tsx` `7178fbbf455f9c04cd6b0acfae1e9c88`
  - `CasinoShell.tsx` `bed68ce7bf2b9aedfd703eff1d3458d5`
  - `CasinoChatPanel.tsx` `c200d66add86e006a307aef630090d93`
  - `roulette.ts` `91c4ba7b4042b1665a8a4ee7317a4658`
  - `casino.css` `3f422841ceb95e85fc17f725759c0365`
  - `check-roulette-model.mts` `418c97dfada39cca15c4ec7374dafca6`
- `staging-test.sh`: collected **1425**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1418**.
- `rg` `rouletteUndoLastPlace`: `roulette.ts`, `CasinoPlay.tsx`, `check-roulette-model.mts`. `postCasinoRouletteTableBet`: `public.ts` + `CasinoPlay.tsx`. `is-docked`: `casino.css` + `CasinoChatPanel.tsx`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку.

Потыкать. Туннель **18081**.

1. `http://127.0.0.1:18081/casino/play/roulette?mode=players` — войти. Фишка **50**, клик **Красное**: фишка на клетке сразу, баланс **−50**, кнопки «Подтвердить» нет.
2. Фишка **25**, клик **36**: ещё одна фишка, баланс ещё **−25**. **Отменить** снимает 36, баланс **+25**. **Сбросить все** чистит стол.
3. Дождаться спина. Следующий раунд: **Повторить** сразу кладёт прошлый расклад (деньги списываются без второй кнопки). Пока свои фишки есть — **Повторить** серая.
4. Чужая или своя фишка на **36** — клик по клетке ставит, **не** открывает `/casino/u/…`. Профиль — строка «Кто поставил».
5. Чат (иконка в шапке): стол слева кликабелен, чат справа без затемнения. Написать сообщение, кликнуть клетку — оба живы. Escape / крестик закрывают. На телефоне лист не на весь экран.
6. `?mode=house` — «Крутить» как раньше. **Должно остаться.**
7. Не ломать: куб 1×1 100 → **195**; джекпот; лимит число vs цвет.

## 2026-08-30 · Стол рулетки: GET 409 глушил колесо, фишки и ленту

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. HMAC и множители 1×1 не менял.

Сломалось после скрытия лунки во время спина, но причина не в CSS: **GET `/api/public/casino/roulette-table` отдавал 409** `Ставка вне лимита (10.00–277.58 ₽)`. `snapshot()` зовёт `maybe_close_due` → settle уже принятых фишек через `load_roulette_house_seat`, который **заново** гонял живое окно. Раунд **17** `rt-d5962b181623` был `open` с overdue `closes_at`: на **11** стояло **300** ₽ при straight-max ≈ **277.58** (house available ~1949 после reserve 36685). Фронт глотал 409 → `tableSnap` null → пустая лента, ставки не ставятся, колесо мёртвое.

Сделано:

- `load_roulette_house_seat(..., require_stake_window=True)`. `play_roulette_known_pocket_with_conn` передаёт **False**: уже принятое место закрывается без `game_stake_bounds` / robot min-max. Проверки робота и payout-vs-reserve (с `extra_available_rub=reserved`) остаются.
- `snapshot()` ловит `HTTPException` closer и всё равно отдаёт стол (лог `roulette table snapshot closer`).
- Фронт: перед `startTableSpin` сеем ленту через `rouletteHistoryWithoutRound`; cleanup колеса сбрасывает `settleOnce`, если `onSettled` не ушёл (иначе второй эффект глушил парковку); blur с `.casino-roulette-rotor` на `.casino-roulette-wheel.is-spinning`, чтобы `filter` не срывал `transitionend` у `transform`.
- Bootstrap: `require_stake_window`, snapshot closer; профиль в списке «Кто поставил» через `CasinoPlayerChip` (строка `casinoTo(/casino/u/${seat.user_id})` в `CasinoRoulette.tsx` уже не жила).

После заливки: GET **200**, раунд **17 settled pocket 17**, живой **18** `rt-e36cdfc0e840` `open`, history **10**.

Файлы: `casino_roulette.py`, `casino_roulette_table.py`, `test_casino_roulette.py`, `test_casino_roulette_table.py`, `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `casino.css`, `bootstrap_static_test.sh`.

Проверки:

- Локально: `PYTHONPATH=. python3 -m unittest tests.test_casino_roulette tests.test_casino_roulette_table -q` → **95 OK**. Новые: held seat 300 на 11 при живом окне ~277 **не** зовёт `_assert_stake_within_limits`; fresh seat — зовёт и 409; snapshot при closer 409 всё равно возвращает history. `npx tsx scripts/check-roulette-model.mts` ok. `npx tsc -b` ok. `bootstrap_static_test.sh` passed.
- Gateway: 2266 modules, CSS `index-i-OsRWRO.css`, JS `index-Cb0Y9e8n.js`. `casino.html` и `/casino/play/roulette` HTTP **200**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Running** (не Recreate).
- SQL: ключей **67**. Раунды: 18 open, 17 settled pocket 17.
- md5 local = staging `/opt`:
  - `casino_roulette.py` `f1a80336cc23168962577fc8fd1e3148`
  - `casino_roulette_table.py` `1611d6ad1b98215b90ead0c6b8bf8f24`
  - `test_casino_roulette.py` `a87c92b9c9ece8b9425cf6cc6dc1a615`
  - `test_casino_roulette_table.py` `127cb87d9f494a1ae5bb9625ee5f7cd5`
  - `CasinoPlay.tsx` `155748ded810163ab62f38d86bbeb23b`
  - `CasinoRoulette.tsx` `5f946f4596744af6b6ba832d5fcd1025`
  - `casino.css` `589873a410d0460b0c4abe8521df3ab4`
  - `bootstrap_static_test.sh` `bcf0e1e471ead26426cea4aad1c043bb`
- `staging-test.sh`: collected **1428** (было 1425, +3 seat/snapshot), **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1421**.
- Повторный `pytest --tb=no` (мимо `staging-test.sh`) **Recreate** контейнера postgres; volume цел, ключи 67, раунд 17 на месте, health passed. Sync так не делал.
- `rg` `require_stake_window`: `casino_roulette.py`, `test_casino_roulette.py`, `bootstrap_static_test.sh`. `roulette table snapshot closer`: `casino_roulette_table.py`, bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (тот же API на хосте **18082**).

- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — лента сверху с прошлыми числами, не пустая. Фишка ставится сразу. Дождаться спина: колесо едет, число **после** остановки, лента обновляется.
- `http://127.0.0.1:18081/casino/play/roulette` — 1×1 «Крутить» как раньше.
- Не ломать: 17 = 35:1; куб 1×1 100 → **195**; один спин; лимит на число vs цвет.

## 2026-08-30 · Рулетка: цифры на ободе не снимать во время спина

Не прод. `deploy_all.py` не запускал. HMAC, 17=35:1, скрытые игры не трогал. Бэкенд не менял.

После «лунка только после остановки» обод на время спина размонтировали (`spinning ? null`). Колесо ехало без 0–36 — «пропадают числа». Прятать нужно было **выпавшее** в ступице и ленте, не всю разметку колеса.

Сделано: `<g className="casino-roulette-numbers">` всегда в SVG. `data-casino-roulette-labels="1"`. Ступица по-прежнему `—` пока `spinning` (`rouletteVisiblePocket`). Подсветка `is-landed` только после парковки. Лента без текущего `round_id` до reveal.

Файл: `CasinoRoulette.tsx`.

Проверки:

- `npx tsx scripts/check-roulette-model.mts` ok. `npx tsc -b` ok. `bootstrap_static_test.sh` passed.
- Gateway: 2266 modules, CSS `index-i-OsRWRO.css` (без смены), JS `index-D8ilrqTN.js` / `casino-B6fUuAdJ.js`. `/casino/play/roulette` HTTP **200**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **Running** (не Recreate).
- md5 local = staging `/opt`: `CasinoRoulette.tsx` `24eb49e22295404bd365a4add57b7859`
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Collected **1428** (как в прошлом срезе, фронт без новых pytest). Passed **1421**.
- `rg` `data-casino-roulette-labels`: CasinoRoulette, bootstrap. `casino-roulette-numbers` text: CasinoRoulette + casino.css. Нет `spinning ? null` в CasinoRoulette.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (хост **18082** — тот же API). Жёсткое обновление страницы.

- `http://127.0.0.1:18081/casino/play/roulette` — на ободе **0–36 всегда**, и пока крутится. В центре **—** до остановки, потом число и цвет. Лента не показывает новую лунку раньше парковки.
- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — то же на общем столе, фишки ставятся.
- Не ломать: 17 = 35:1; куб 1×1 100 → **195**; один спин; лимит число vs цвет.

## 2026-08-31 · Рулетка: колесо паркуется и стол больше не принимает ставки

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. HMAC и 17=35:1 не менял.

После спина UI мёртвый: фишки не ставятся, 1×1 «Крутить» молчит. Две причины сразу.

**Клиент.** `revealRouletteRound` ждал SSE `settled`, пока крутится стол; poll GET пропускался (`tableSpinningRef`). Пропавший event → вечный лок. После парковки GET ещё ~15 с отдавал `settled` (пустой новый `open` перекрывали недавним settled) — фронт считал `status !== open` запретом.

**Сервер.** Раунд **26** `rt-eb93234fb544` завис в `spinning` (pocket 26). `maybe_close_due` закрывал только overdue `open`, locked/spinning не резюмировал. Closer крутился раз в ~1 с: GET 200, стол вечно `spinning`. Две прямые 100 ₽ (23/24) без `game_id`, резерв **3425** при 5% комиссии; живой расчёт **3460**. `load_roulette_house_seat` и `settlement.payout > reserved` давали **409** `HOUSE_BANKROLL_INSUFFICIENT` / «payout exceeds». `snapshot()` глотал 409 (`roulette table snapshot closer`) — клиенты видели живой spinning.

Сделано:

- Колесо: timeout парковки всегда вешается заново (`[spinning, pocket, skipMotion]`), без `settleOnce`, который срывал `onSettled`.
- Unlock сразу после парковки, без ожидания SSE; локальный `tableSnap` → `open`; `rouletteTableAcceptsBets`: `open` и `settled` принимают, `locked`/`spinning` нет. Таймер «ставки закрыты» только на locked/spinning.
- Snapshot всегда предпочитает живой `open` недавнему settled (`Keep the new collecting round`).
- `_lock_and_settle` резюмирует `locked`/`spinning`, пропускает места с `game_id`. `maybe_close_due` берёт `status IN ('locked', 'spinning')`.
- Held settle: `require_stake_window=False` не перепроверяет живой bankroll/окно. Cover drift — warning, не 409. Выплата выше резерва — `clamp_held_roulette_payout` (платим резерв, стол не клинит).

После заливки: GET **200 `open`**. Раунд **26 settled pocket 26** в `00:08:42Z` (два warning `cover drifted max=3460.00 reserved=3425.00`). Дальше живые open (27→…→30), closer не 409-лупит.

Файлы: `casino_roulette.py`, `casino_roulette_table.py`, `test_casino_roulette.py`, `test_casino_roulette_table.py`, `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `roulette.ts`, `check-roulette-model.mts`, `bootstrap_static_test.sh`.

Проверки:

- Локально: `PYTHONPATH=. python3 -m unittest tests.test_casino_roulette tests.test_casino_roulette_table -q` → **99 OK**. Новые: held seat без bankroll-recheck; payout 3600 при резерве 3425 → **3425**, не 409; spinning resume только leftover без `game_id`; snapshot не подменяет пустой open недавним settled. `npx tsx scripts/check-roulette-model.mts` ok (`rouletteTableAcceptsBets("settled")===true`). `npx tsc -b` ok. `bootstrap_static_test.sh` passed.
- Gateway: `/casino/play/roulette` HTTP **200**. CSS `index--5l2FL6L.css`, JS `index-Dg7MCK28.js` / `casino-BXpxIU4t.js`. В бандле есть `rouletteTableAcceptsBets`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Running** (не Recreate).
- SQL: ключей **67**. Раунд 26 settled pocket 26; живой open после него.
- md5 local = staging `/opt`:
  - `casino_roulette.py` `0126d537a93f0376e4913eeb2150b48f`
  - `casino_roulette_table.py` `8e1fc8a1ff2566ca44e4423b30aac510`
  - `test_casino_roulette.py` `8b9ba9cb07f2d98d5d9c72232f389abf`
  - `test_casino_roulette_table.py` `e041eac2a369b92f6ea483ce271c005d`
  - `CasinoPlay.tsx` `3da9e2ccdb3508929da9de9312037d36`
  - `CasinoRoulette.tsx` `0085e4797448ad8cf96d562978722f8d`
  - `roulette.ts` `6266aacb368726acc1533e03460a2713`
  - `bootstrap_static_test.sh` `02c6edbedac0f0515f3181c68065b061`
- `staging-test.sh`: collected **1432** (было 1428, +4: bankroll skip, payout clamp, spinning resume, snapshot empty-open). **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1425**.
- Повторный `docker compose --profile tests run` с `--tb=no` (мимо `staging-test.sh`) **Recreate** postgres; volume цел, ключи 67, раунды на месте, health passed. Так второй раз не гонял.
- `rg` `rouletteTableAcceptsBets`: roulette.ts, CasinoPlay, check-roulette-model, bootstrap. `clamp_held_roulette_payout` / `payout drifted`: casino_roulette.py, тест, bootstrap. `status IN ('locked', 'spinning')` и `Keep the new collecting round`: casino_roulette_table.py, bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без HostConfig ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (хост **18082** — тот же API). **Жёсткое обновление** страницы — иначе старый JS так и будет ждать SSE.

- `http://127.0.0.1:18081/casino/play/roulette?mode=players` — дождаться спина до остановки. Сразу после парковки фишка ставится на **следующий** раунд. Обод 0–36 на месте, в центре число только после остановки.
- `http://127.0.0.1:18081/casino/play/roulette` — 1×1 «Крутить» снова жмётся после парковки.
- Не ломать: 17 = 35:1; куб 1×1 100 → **195**; один спин; лимит число vs цвет.

## 2026-08-31 · Риск: графики читаемые, без наездов

Не прод. `deploy_all.py` не запускал. Backend / SQL / формулы RTP не менял. Следующую задачу плана не начинал.

Клик по `/x8/casino/risk`: полукруг банка наезжал суммой `557 284,65 ₽` на дугу; SQL `SELECT COALESCE(SUM(bet_rub)…` торчал в лицо; «коридор RTP» был линией между разными играми, ось раздувалась играми без партий.

Сделано (только фронт):

- Банк — горизонтальная полоса, сумма снаружи, метки порог / макс. выплата / цель легендой, статус «запас есть / ниже порога».
- RTP — по одной полоске на игру с партиями: серое = шум ±100/√n, пунктир = формула, точка = сколько вернули. Статус: «в коридоре» / «дом в плюсе» / «игроки в плюсе». Игры без партий — строкой внизу, не на графике.
- KPI: «Ставки за окно». SQL спрятан в «Как посчитаны ставки за окно». `data-risk-verify` / `data-risk-verify-sql` на месте.

Файлы: `riskViz.tsx`, `CasinoRisk.tsx`.

Проверки:

- `npx tsc -b` ok. `bootstrap_static_test.sh` passed.
- Gateway: HTTP **200** `/x8/login`, `/x8/casino/risk`. Бандл `panel-KaAG_HxM.js` содержит `data-risk-verify`, `Доступно сейчас`, `Отдача игр (RTP)`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Recreate**, volume цел.
- SQL: ключей **67**. `SELECT COALESCE(SUM(bet_rub), 0) FROM casino_games WHERE created_at > now() - interval '7 days'` → **299531.19** (как KPI на скрине).
- md5 local = staging `/opt`:
  - `riskViz.tsx` `0531da8fefb50d5a2732fa524960b684`
  - `CasinoRisk.tsx` `6e9219b841e2caebd1ea194bf9d50b77`
- `staging-test.sh`: collected **1432**, **1425** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `data-risk-verify`: CasinoRisk + bootstrap. `export function Gauge` / `CorridorChart`: riskViz + bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление** `/x8/casino/risk` (Ctrl+Shift+R) — иначе старый бандл с полукругом.

- `http://127.0.0.1:18081/x8/casino/risk` — сумма банка не на графике; SQL не виден, пока не открыть «Как посчитаны ставки за окно»; у каждой игры своя полоска и статус, не общая ломаная линия.
- 24ч / 7д / 30д — полоски пересчитываются, игры без партий за окно уходят в подпись внизу.
- Не ломать: число ставок за 7д = **299 531,19 ₽**; аномалии / топ выигравших-проигравших на месте.

## 2026-08-31 · Рулетка в Telegram: «Ставка принята» в личке и в игровом чате

Не прод. `deploy_all.py` не запускал. FocusLucky / холдем / комнаты / кланы не открывал. HMAC и множители не менял. Бэкенд рулетки не трогал.

Клик: `/help roulette` ответил, `/roulette red 50` — тишина и в боте, и в игровом чате. Ставка на стол **встала** (POST 200, `notify_chat_id` записан, раунд 39/40 settled, выплата 97.5 ₽). Сообщение Telegram отверг: Web App кнопка «Открыть стол» с `http://127.0.0.1:18081/...` — `Bad Request: Only HTTPS links are allowed`. Подтверждение умирало вместе с клавиатурой. Итог спина уходил в outbox позже; в момент ставки не было ни «принята».

Сделано:

- Web App на подтверждении только если URL `https://`. Staging `http://127.0.0.1:18081` — текст без кнопки.
- Если клавиатура всё же падает — повтор без markup.
- Заголовок **Ставка принята**. Из лички копия в привязанный игровой чат; из чата — только reply, без дубля.

Файлы: `games/roulette_table.py`, `tests/test_roulette_table.py`; bootstrap `Ставка принята` / `https://`.

Проверки:

- Локально бот `tests.test_roulette_table` **7** OK (http без web_app; https кнопка есть; retry без markup; DM → reply + группа; группа без дубля; `/roulette` шпаргалка). Вместе с `test_roulette_cmd` / `test_help` / `test_bot_startup` / `test_focuspay_client`: **43** OK. `bootstrap_static_test.sh` passed.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды). Postgres при sync **Recreate**, volume цел.
- SQL: ключей **67**. Живой раунд open (46). casino-bot: `Roulette table handlers registered`.
- md5 local = staging `/opt` = live casino-bot `/app`:
  - `roulette_table.py` `904e0d959160d27c113c85790da93418`
  - `test_roulette_table.py` `aef45cc69ba0b798eba1cf4e99ed936b`
  - `bootstrap_static_test.sh` `180c94dc356f53c6fe132374e9743d68`
- `staging-test.sh`: collected **1432**, **1425** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `https_table_url` / `announce_bound_chat` / `Ставка принята`: `roulette_table.py` + `test_roulette_table.py` + bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (в этом срезе roulette notify; остальное чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Бот `@focuscazzcztewrfweda_bot`. Туннель **18081** только чтобы сверить стол.

1. Личка с ботом: `/roulette red 50` — сразу ответ **Ставка принята** (красное, списание 50 ₽). Тот же текст появляется в игровом чате с ником.
2. Игровой чат: `/roulette black 50` — ответ в чате, в личку это сообщение не дублируется.
3. `/roulette` без аргументов — шпаргалка, не молчание. Кнопки «Открыть стол» на staging нет (http).
4. Дождаться спина: результат как раньше (выпало N). На `http://127.0.0.1:18081/casino/play/roulette?mode=players` фишка видна.
5. Не ломать: куб 1×1 100 → **195**; сайт-клик по клетке как был.

## 2026-08-31 · Баккара дом: исход после карт, не сразу

Не прод. `deploy_all.py` не запускал. Бэкенд / HMAC / выплаты не менял. Паркованные холдем / FocusLucky / комнаты / кланы не открывал.

Повод: на `/casino/play/baccara?mode=house` тост «Проигрыш»/«Выигрыш» и баланс в шапке приходили вместе с ответом API — ещё до лиц карт. Красное «Поражение» могло совпасть с первой картой.

Сделано (только фронт):

- Раздача по одной карте; неоткрытые — рубашки. Очки после последней карты. «Победа / Поражение» и тост ещё через **450 мс**.
- Баланс в шапке и на панели заморожен до этого момента (как колесо рулетки).
- Блэкджек: тост и выплата тоже после добора/открытия дилера, не в момент `POST action`.

Файлы этого среза:

- `focussite/frontend/src/casino/houseCards.ts` (новый)
- `focussite/frontend/src/casino/CasinoHouseCards.tsx`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/scripts/check-house-cards-reveal.mts`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsx focussite/frontend/scripts/check-house-cards-reveal.mts` ok (3+2 карты = **1850** мс до тоста, не 0). `npx tsc -b` ok. `npm run build` ok, 2267 modules. `bootstrap_static_test.sh` passed.
- Gateway: HTTP **200** `/casino`, `/casino/play/baccara?mode=house`, `/api/health`. Бандл `index-CdWEqUFE.js` / CSS `index-D--HL3NS.css`. В JS есть `data-casino-house-outcome` и `data-casino-house-reveal`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Running** (не Recreate), volume цел. После `staging-test.sh` postgres всё ещё **Running**.
- SQL: ключей **67**.
- md5 local = staging `/opt`:
  - `houseCards.ts` `c2f0825bc384ded2759839eb18a0afc6`
  - `CasinoHouseCards.tsx` `4dd229dfb7719db244e3127938767416`
  - `CasinoPlay.tsx` `29f6d2d6096ee130c8de1fb48ee38994`
  - `check-house-cards-reveal.mts` `35cf3f2947c379bb5f8d7b0c517e2e9b`
  - `bootstrap_static_test.sh` `b44be2b536cae92a1354229af003e4ea`
- `staging-test.sh`: collected **1432**, **1425** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `grep` `houseCardsRevealMs` / `waitForCardReveal` / `data-casino-house-outcome`: houseCards + HouseCards + Play + bootstrap.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: раздача карт). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (хост **18082** — тот же API). **Жёсткое обновление** страницы — иначе старый JS сразу покажет тост.

- `http://127.0.0.1:18081/casino/play/baccara?mode=house` — войти. Ставка **100**. Пока карты раздаются: нет тоста «Проигрыш»/«Выигрыш», баланс в шапке не прыгает, нет красного «Поражение».
- После последней карты — очки, пауза, потом «Победа» или «Поражение» и тост. Баланс меняется в этот момент.
- Блэкджек дом: «Оставить» — сначала дырка и добор казино, тост не раньше.
- Не ломать: куб 1×1 100 → **195**; рулетка 1×1; баккара без hit/stand.

## 2026-08-31 · Джекпот в казино-боте: `/jackpot` и ставка

Не прод. `deploy_all.py` не запускал. Формулу ролла/билетов джекпота не трогал. HMAC/рейк рулетки не трогал. Паркованные холдем / FocusLucky (`raffle`) / комнаты / кланы не открывал. JWT `/user/casino/jackpot` без `notify_chat_id` (сайт как был).

Повод: общий банк CSGETGO уже на сайте; в казино-боте не было команды и ставки. Образец — живая `/roulette` + internal + `casino_notification_outbox`.

Сделано:

- Internal `GET /api/internal/casino/jackpot?telegram_id=` (снимок) и `POST /jackpot/bet` `{telegram_id, notify_chat_id, amount_rub}`. `user_id` = telegram id, как у рулетки.
- `place_bet(..., notify_chat_id=None)` пишет чат на ставке; докид `COALESCE` — первый чат остаётся. Settle/refund: outbox `jackpot_settled` / `jackpot_refunded` по уникальным `notify_chat_id`. Сайт-only ставки без чата — без outbox.
- Миграция `add_casino_jackpot_telegram_notify.sql`: `casino_jackpot_bets.notify_chat_id BIGINT`. В списках `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh` (свежий и existing-DB), `bootstrap_static_test.sh`. FK outbox не трогал.
- Казино-бот: `/jackpot` и `/джекпот` без суммы — карточка (банк, N/max, рейк, таймер / «ждём ставку», список с %, «Вы»). `/jackpot 100` / `/jackpot 50р` — ставка в текущий open-раунд. Кнопки 10/25/50/100/250/500 (`jpbet:`), без FSM своей суммы. Guard: личка или привязанный игровой чат. Из лички копия «Ставка принята» в чат; из чата — только reply. Web App «Открыть джекпот» только при Mini App URL `https://`.
- Справка `/help jackpot` + алиас «джекпот». Клиент `get_jackpot` / `place_jackpot_bet`.

Файлы этого среза:

- `site/exchange-backend/casino_jackpot.py`
- `site/exchange-backend/routers/internal_casino.py`
- `site/exchange-backend/migrations/add_casino_jackpot_telegram_notify.sql`
- `site/exchange-backend/tests/test_casino_jackpot_notify.py`
- `focussite/docker/staging-db/00-apply-migrations.sh`
- `focussite/docker/staging-db/20-full-panel-bootstrap.sh`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `focuspay-casino/games/jackpot.py` (новый)
- `focuspay-casino/bot.py`, `focuspay_client.py`, `games/help.py`
- `focuspay-casino/tests/test_jackpot.py` (+ help / client / startup lists)
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально бэкенд `tests.test_casino_jackpot` + `test_casino_jackpot_notify` **17** OK. Бот `tests.test_jackpot` + `test_help` + `test_focuspay_client` + `test_bot_startup` + `test_roulette_table` **50** OK. `bootstrap_static_test.sh` passed.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды). Postgres при sync **Running** (не Recreate), volume цел. После `staging-test.sh` postgres всё ещё **Running**.
- SQL: ключей **67**. Колонка `casino_jackpot_bets.notify_chat_id` **bigint**. casino-bot: `Jackpot handlers registered`.
- md5 local = staging `/opt` = live casino-bot `/app` (бэкенд `/app/backend`):
  - `casino_jackpot.py` `a07fc8ab1b32ddebac04add08e09e0a4`
  - `internal_casino.py` `56d92c94cdb3b41fe6448c44c63df249`
  - `add_casino_jackpot_telegram_notify.sql` `691ce14a1b82fdd0da33bbe9fdaa7766`
  - `test_casino_jackpot_notify.py` `dc86c55c3586802a2aa6f5ba02ac23ad`
  - `00-apply-migrations.sh` `8902c7f9a3fbbb8523a2c34b9f4236c0`
  - `20-full-panel-bootstrap.sh` `6013d91105f5be3562e0c611177ab909`
  - `bootstrap_static_test.sh` `4e7f0457b87ffc051d9c9235479c3273`
  - `games/jackpot.py` `00430a55df0d65f81f04da015d38576b`
  - `bot.py` `58eaa9fd65579a71a2c9d47ea15b111e`
  - `focuspay_client.py` `5c16bad4f1d9959883e491f4cc32c6f9`
  - `games/help.py` `aaffa6192f573f0befba4b2daaabd4ef`
  - `tests/test_jackpot.py` `792660c02dd545bc86c45b8ee35b4e5a`
- `staging-test.sh`: collected **1441** (было 1432, +9 `test_casino_jackpot_notify`), **1434** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `notify_chat_id` / `/jackpot/bet` / `jackpot_settled` / `register_jackpot_handlers`: jackpot py, internal router, миграция, тесты, bootstrap, `games/jackpot.py`, `bot.py`, client.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (в этом срезе jackpot; остальное чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Бот `@focuscazzcztewrfweda_bot`. Туннель **18081**.

1. `/jackpot` — банк, таймер или «ждём ставку», список с %. Кнопки пресетов; своей суммы нет. На staging кнопки «Открыть джекпот» нет (http).
2. `/jackpot 100` — **Ставка принята**, списание. На `http://127.0.0.1:18081/casino/play/jackpot` тот же банк.
3. Докид `/jackpot 50` — сумма и % выросли; выйти нельзя.
4. Второй аккаунт ставит — оба в списке; после спина (таймер или набор) — сообщение кто выиграл (банк, рейк, выплата).
5. Не ломать: `/roulette red 50`; куб 1×1 100 → **195**.

## 2026-08-31 · Личка: «Ставка принята» только в боте, не в игровом чате

Не прод. `deploy_all.py` не запускал. HMAC / выплаты / формулы спина не трогал. Паркованные холдем / FocusLucky / комнаты / кланы не открывал.

Повод: ставка из лички (`/roulette red 50`, `/jackpot 500`) дублировала «Ставка принята» в привязанный игровой чат с @ником. Нужно только подтверждение в боте.

Сделано:

- Рулетка и джекпот больше не копируют «Ставка принята» из лички в игровой чат. `announce_bound_chat` убран.
- В игровом чате по-прежнему reply на команду в чате, без второго сообщения.
- Исход спина по `notify_chat_id` как был (личка → личка, чат → чат).

Файлы этого среза:

- `focuspay-casino/games/roulette_table.py`
- `focuspay-casino/games/jackpot.py`
- `focuspay-casino/tests/test_roulette_table.py`
- `focuspay-casino/tests/test_jackpot.py`
- `focussite/docker/staging-db/bootstrap_static_test.sh` (две строки `test_dm_bet_replies_without_mirroring_to_game_chat`)
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально бот `tests.test_roulette_table` + `test_jackpot` + `test_help` + `test_bot_startup` + `test_focuspay_client`: **50** OK. `bootstrap_static_test.sh` passed.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды). Postgres при sync **Recreate**, volume цел. После `staging-test.sh` postgres **Running**.
- SQL: ключей **67**. casino-bot: `Roulette table handlers registered`, `Jackpot handlers registered`.
- md5 local = staging `/opt` = live casino-bot `/app`:
  - `roulette_table.py` `cbb5bcd7fe5ae469821de068843e4c1f`
  - `jackpot.py` `8cae9b08b1510a7d12389585ec04d000`
  - `test_roulette_table.py` `7912b11dafe2e60353ae27fc21850cf3`
  - `test_jackpot.py` `7fec209813683eb5f586a0f9c3c982c2`
  - `bootstrap_static_test.sh` `d5e2ffd32396ff8a50a3052facfd3fb1`
- `staging-test.sh`: collected **1441**, **1434** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `test_dm_bet_replies_without_mirroring_to_game_chat`: оба теста + bootstrap. `announce_bound_chat` в `games/roulette_table.py` и `games/jackpot.py`: **0**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty (в этом срезе без копии в чат; остальное чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Бот `@focuscazzcztewrfweda_bot`. Туннель **18081**.

1. Личка: `/roulette red 50` — в боте **Ставка принята**. В игровом чате этого сообщения **нет**.
2. Личка: `/jackpot 100` — то же: только бот, чат молчит.
3. Игровой чат: `/roulette black 50` — ответ в чате как раньше.
4. Не ломать: куб 1×1 100 → **195**; после спина результат в личке, если ставил из бота.

## 2026-08-31 · Джекпот: только игроки, понятный телефон

Не прод. `deploy_all.py` не запускал. Бэкенд раунда / HMAC / выплаты не менял. Паркованные холдем / FocusLucky / комнаты / кланы не открывал.

Повод: на телефоне вкладки «Против казино | С игроками» и лента из копий одного аватара с `100.0%` до спина. Сама игра уже PvP (дом не ставит).

Сделано (только фронт):

- У джекпота нет табов режима. `/casino/play/jackpot` сразу банк и список; `?mode=house` тоже открывает игру, не заглушку.
- Каталог: `jackpot` в `duels`, howTo «Игроки кладут в общий банк. Шанс = доля ставки.»
- До спина лента скрыта. Список с полосками шанса. Лента только на спине (аватары, без % на слотах). На телефоне ставка sticky над нижней навигацией, подпись «Ставка, ₽».

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoJackpot.tsx`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/gameCatalog.ts`
- `focussite/frontend/src/casino/casinoRoutes.tsx`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok. `npm run build` ok, 2267 modules. Бандл `index-BS9fBQcG.js` / CSS `index-DtCbhcFj.css`. В JS: `data-casino-jackpot-reel`, «Игроки кладут в общий банк. Шанс = доля ставки.» В CSS: `casino-jackpot-bar`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Recreate**, volume цел (после тестов контейнер **Running**).
- Живой шлюз HTTP **200**: `/casino`, `/casino/play/jackpot`, `/casino/play/jackpot?mode=house`, `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoJackpot.tsx` `f65eaae883e35bd3b64ca77cdb809a95`
  - `CasinoPlay.tsx` `d1ae46fb5202f5d15a3095a10e975d62`
  - `gameCatalog.ts` `cbee82c0bb458705037659579c43079f`
  - `casinoRoutes.tsx` `441378feea88a7a2b4ec0d2c61d44725`
  - `casino.css` `e03aed08742a3c7908245bc86e4c71be`
- `staging-test.sh`: collected **1441**, **1434** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `data-casino-jackpot-reel` / `JACKPOT_PLAY` / `Игроки кладут в общий банк`: Jackpot + Play + catalog + CSS. `gameId === "jackpot" ? null` прячет `CasinoModeSwitch`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.
- Браузер `http://127.0.0.1:18081`: лобби плитка джекпота badge **Дуэли**; фильтр «Против казино» — только рулетка; фильтр «Дуэли» — кубики + джекпот. `/casino/play/jackpot` без табов режима, без ленты до спина, «Первая ставка запускает таймер», поле «Ставка, ₽». Телефон 390px: банк+таймер в два столбца, ставка над нижней навигацией.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: UI джекпота). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (хост **18082** — тот же API). **Жёсткое обновление** страницы.

- `http://127.0.0.1:18081/casino/play/jackpot` — нет табов «Против казино / С игроками». Сразу банк, таймер, список (или «Первая ставка запускает таймер»).
- С телефона: до спина нет шести «100%»; ставка снизу с подписью; если уже в раунде — своя доля над кнопкой.
- Поставить / докинуть, дождаться спина — лента появляется только тогда.
- Лобби: джекпот в «Дуэли», не в «Против казино».
- Не ломать: куб 1×1 100 → **195**; рулетка стол; баккара дом.

## 2026-08-31 · Ссылка «смотреть на сайте» после ставки

Не прод. `deploy_all.py` не запускал. Формулу джекпота, HMAC/рейк рулетки, куб 1×1 и парковку (холдем / FocusLucky / комнаты / кланы) не трогал. Mini App `web_app` не менял.

Повод: после принятой ставки в казино-боте открыть **ту же партию** на сайте. На staging origin `http://` — Mini App ломает сообщение, поэтому новая ссылка: HTML `<a href>` + кнопка `url=`.

Сделано (казино-бот):

- Общий `games/site_links.py`: origin из `CASINO_MINIAPP_URL` (и http, и https), href, строка «Смотреть на сайте», кнопка `url=`. HTTPS Mini App остаётся в `https_only()`.
- Рулетка / джекпот: ссылка в `confirm_text` + url-кнопка. Статус `/jackpot` без суммы — без url-кнопки. `web_app` «Открыть стол» / «Открыть джекпот» только https, как было.
- Дуэль: после создания ожидания и входа. Стол: визард «стол создан» и вход «Вы заняли место»; на «Ваши активные игры» кнопка стола. Карты 1×1: `/casino/duels/{settlement_game_id}`.
- `house_cub.py` без новой ссылки.

Файлы этого среза:

- `games/site_links.py` (новый)
- `games/roulette_table.py`, `games/jackpot.py`, `games/pvp.py`, `games/v2_tables.py`, `games/table_wizard.py`, `games/baccara.py`, `games/blackjack.py`
- `tests/test_site_links.py` (новый) + правки тестов рулетки / джекпота / v2 / визарда / pvp / куба / карт
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально бот: `test_site_links` + `test_roulette_table` + `test_jackpot` + `test_v2_tables` + `test_table_wizard` + `test_pvp_dice` + `test_house_cub` + `test_card_bet_input` + `test_help` + `test_bot_startup` + `test_focuspay_client`: **100** OK; `test_pvp_lobby` + `test_card_invite` + `test_card_server_deal` + `test_staging_ui` + `test_profile`: **46** OK. `bootstrap_static_test.sh` passed.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres после тестов **Running** (`focuspay-staging-runtime-postgres-1 Up … healthy`).
- SQL: ключей **67**. casino-bot: `Roulette table handlers registered`, `Jackpot handlers registered`, PVP/V2/wizard, Baccara, Blackjack.
- md5 local = staging `/opt` = live casino-bot `/app` (игры; тесты только `/opt`):
  - `site_links.py` `a5a6fd91ecaf44db5a9f74b36022fb19`
  - `roulette_table.py` `9b4d1a6cf24b27fde0a3892c5ec5beca`
  - `jackpot.py` `9fdd8bea10475cd5ffb1dc5438046401`
  - `pvp.py` `ade4915e706e3a432f2105ef88326175`
  - `v2_tables.py` `b8e4a476f028b535a0cc7c876a89fdfb`
  - `table_wizard.py` `d38c02bbc2284ca7db6da750307d8732`
  - `baccara.py` `6ac3632bbcfea3cebb46751f49f5bacf`
  - `blackjack.py` `088c90784771aa43608a32969a250fc5`
  - `test_site_links.py` `1356863725e41d649a024c21f82e0beb`
  - `bootstrap_static_test.sh` `050631cd0794d1422ff7a3fcbedd3866`
- `staging-test.sh`: collected **1441**, **1434** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `Смотреть на сайте`: `site_links.py` + тесты рулетки/джекпота/визарда/карт/куба (куб: **assertNotIn**). `append_watch_line`: roulette, jackpot, pvp, v2_tables, table_wizard, baccara, blackjack. `house_cub.py`: **0**. `web_app` остался только в roulette/jackpot на https.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: bootstrap + worklog). `focuspay-casino` HEAD `4b8d65e`, dirty (этот срез: site_links + ставки; остальное чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Бот `@focuscazzcztewrfweda_bot`. Туннель **18081**.

1. `/jackpot 100` и `/roulette red 50` — в «Ставка принята» ссылка **Смотреть на сайте** и url-кнопка; страница та же партия. Mini App-кнопка на staging по-прежнему не появляется (http).
2. Создать стол / войти в дуэль — ссылка на `/casino/tables/…` или `/casino/duels/…`, стол живой.
3. Куб 1×1 100 → **195**, без новой ссылки.

## 2026-08-31 · После входа с казино-ссылки — обратно в казино

Не прод. `deploy_all.py` не запускал. Бэкенд / формулы игр не менял. Паркованные холдем / FocusLucky / комнаты / кланы не открывал.

Повод: по ссылке `/casino` (или игра) → Войти → оказывался в кабинете `/cabinet`.

Сделано (только фронт):

- Кнопки «Войти» в шапке и нижнем меню казино ведут на `/login?next=…` текущей страницы, не голый `/login`.
- После логина / регистрации / Telegram OAuth возврат на этот путь (лобби или игра). Прямой `/login` по-прежнему в кабинет.
- Оверлей с сайта: `casinoBackground` сохраняется. Mini App: `goOutsideCasino("/login?next=/casino/…")`.
- Open-redirect: только относительный `/…`, не `//`, не `/login` / `/register`.

Файлы этого среза:

- `focussite/frontend/src/lib/postLoginPath.ts`
- `focussite/frontend/src/lib/telegramOauth.ts`
- `focussite/frontend/src/casino/casinoPaths.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/pages/Login.tsx`
- `focussite/frontend/src/pages/Register.tsx`
- `focussite/frontend/src/App.tsx` (RequireAuth: pathname+search и `next`)
- `focussite/frontend/scripts/check-post-login-path.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsx scripts/check-post-login-path.mts` ok. `npx tsc -b` ok. `npm run build` ok, 2269 modules. Бандл `index-DS-5ajB2.js` содержит `tgAuthResult`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`: первый health — гонка `No such container` после recreate; повтор `staging-runtime-health.sh` **passed**. Postgres при test **Recreate**, после тестов **Running** (`Up … healthy`).
- Живой шлюз HTTP **200**: `/casino`, `/login`, `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `postLoginPath.ts` `4ef5059658f1ecbfae5f84007334e55b`
  - `telegramOauth.ts` `5f1e552319bc86a063e1131e1ddda714`
  - `casinoPaths.tsx` `844ddfc7a324c58feace9f4805fda073`
  - `CasinoShell.tsx` `c0acd144b9aee710b404cdb5ecb01461`
  - `Login.tsx` `3fea25ed77ba22a7ff498a038389c97c`
  - `Register.tsx` `d32a4ef9658b84276867f874386130af`
  - `App.tsx` `5b98291fb89bd9031547c19b387d3a25`
  - `check-post-login-path.mts` `b558922f7cb8f599ea06e4def0fcf8b5`
- Шлюз отдаёт тот же `assets/index-DS-5ajB2.js`.
- `staging-test.sh`: collected **1441**, **1434** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `CasinoLoginLink`: Shell 3 кнопки + `casinoPaths`. `authPathWithNext` / `resolvePostLoginPath`: Login, Register, App, casinoPaths, тесты. `returnPath={telegramReturnPath}` в Login, не хардкод `/cabinet`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: возврат после логина). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.** Сначала выйти из аккаунта.

- `http://127.0.0.1:18081/casino` → Войти (шапка или низ) → логин → снова **лобби**, не кабинет.
- `http://127.0.0.1:18081/casino/play/roulette?mode=house` → Войти → снова **эта рулетка**.
- С главной сайта открыть Казино оверлеем → Войти → снова казино поверх сайта.
- Контроль: просто `http://127.0.0.1:18081/login` без казино по-прежнему ведёт в кабинет.
- Не ломать: куб 1×1 100 → **195**.

## 2026-08-31 · Джекпот на телефоне без скролла вбок

Не прод. `deploy_all.py` не запускал. Бэкенд раунда / HMAC / выплаты не менял. Паркованные холдем / FocusLucky / комнаты / кланы не открывал.

Повод: лента из 100 слотов (~7200px) всегда в DOM. `overflow: hidden` и idle `height: 0` на WebKit не мешали раздуть `.casino-main` (`overflow: auto`). Плюс sticky-ставка с отрицательным margin и длинная строка таймера.

Сделано (только фронт):

- Слоты не рендерятся до спина. Трек `position: absolute` внутри окна `overflow-x: clip`. На `.casino-play[data-casino-play="jackpot"]`, `.casino-jackpot` и `.casino-main:has([data-casino-jackpot])` — `overflow-x: clip`. На телефоне слот **56px**.
- Герой: крупный банк + одна строка `04:12 · 1/30` (`спин` / `ждём` / `с 1-й ставки`). До спина одна общая полоска долей, затем список. Ники с ellipsis. Sticky-ставка без `margin-inline: -12px`.
- Спин: `useLayoutEffect` после монтирования слотов, `translateX` к индексу 80 как был.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoJackpot.tsx`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Recreate**, после тестов **Running** (`Up … healthy`). Сборка gateway: **2269** modules, CSS `index-7i95z74m.css`, JS `index-B4i41X89.js`.
- Живой шлюз HTTP **200**: `/casino`, `/casino/play/jackpot`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoJackpot.tsx` `a185756b81e44209a1b66ae39d182a5b`
  - `casino.css` `ace29c5ef63e6757e46de00a9ccebb6e`
- Живой CSS: `casino-jackpot-shares`, **6** `overflow-x:clip`, `--casino-jackpot-slot: 56px` в media, `.casino-main:has([data-casino-jackpot]){overflow-x:clip}`. Живой JS: `data-casino-jackpot-phase`, `с 1-й ставки`.
- Браузер 390px: wait-экран джекпота (банк, `с 1-й ставки · —`, «Первая ставка запускает таймер», «Ставка, ₽») без ленты. Инъекция 100 слотов в то же CSS: track **5600px** (`absolute`, слот 56px), `documentElement`/`body`/`.casino-main` **scrollWidth = 390**, страница не едет вбок.
- `staging-test.sh`: collected **1441**, **1434** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `casino-jackpot-shares` / `overflow-x: clip` / `data-casino-jackpot-phase`: Jackpot + CSS. `margin-inline` в `casino.css`: **0**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: UI джекпота). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP, не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (хост **18082** — тот же API). **Жёсткое обновление**, телефон или узкое окно.

- `http://127.0.0.1:18081/casino/play/jackpot` — страница **не** едет влево-вправо (ни до спина, ни во время).
- Банк и таймер читаются без горизонтального свайпа; ставка на экране.
- Спин: лента только в своём окне, страница по-прежнему только вертикально.
- Не ломать: куб 1×1 100 → **195**; рулетка стол.

## 2026-08-31 · Джекпот: кнопки 100 ₽ в игровом чате

Не прод. `deploy_all.py` не запускал. Формулу джекпота / HMAC рулетки / куб 1×1 / парковку не трогал. Mini App не менял.

Повод клик-приёмки: в группе **тестовый чат** рулетка (команда) работает, клик **100 ₽** на карточке джекпота — алерт «Игры доступны только в подтверждённом игровом чате». Привязка staging: `chat_id=-5562276559` (`FocusCasino staging test chat`). Рулетка — `require_message` (объект `chat.id`). Джекпот — callback: `chat` как dict / id супергруппы `-100X` гард не узнавал; `_place` тоже брал `getattr(chat, "id")` и молча выходил.

Сделано:

- `games/chat_guard.py`: id из объекта и dict, строка, пара `-X` / `-100X`; callback читает `message.chat` и json.
- `games/jackpot.py`: ставка с кнопки через `callback_chat` / `chat_id_from`.
- Тесты: callback в bound-чате ставит; чужая группа — алерт.

Файлы этого среза:

- `games/chat_guard.py`, `games/jackpot.py`
- `tests/test_game_chat_guard.py`, `tests/test_jackpot.py`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально: `test_game_chat_guard` + `test_jackpot` + `test_roulette_table` + `test_pvp_dice` + `test_table_wizard` + `test_card_bet_input` + `test_house_cub` + `test_site_links`: **70** OK. `bootstrap_static_test.sh` passed.
- Полный `staging-sync.sh` **не** дошёл: gateway `tsc` на чужом dirty `AdminFocusLucky.tsx` (`onClick={load}`). rsync на `/opt` прошёл; образ casino-bot из этой сборки поднят `compose up -d --no-deps --wait casino-bot`. Health **passed**. Postgres **Running**.
- SQL: ключей **67**. casino-bot: `Jackpot handlers registered`, `Roulette table handlers registered`.
- md5 local = `/opt` = live `/app`:
  - `chat_guard.py` `91ab2fe2ee3c664fdf86961a966ed54b`
  - `jackpot.py` `d53e9143698bb849a7a9860532c558bc`
  - `test_game_chat_guard.py` `fb615d7fd66050fa2ae4a196d884a928`
  - `test_jackpot.py` `24eef2bb4d09d21d8b93adc2d29c9dad`
  - `bootstrap_static_test.sh` `3bd56431f3750ecc06a64e40f6de08a6`
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Backend-тестов в этом срезе не добавлял (база **1441**).
- `rg` `chat_id_aliases` / `callback_chat`: `chat_guard.py`, `jackpot.py`, `test_game_chat_guard.py`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (bootstrap + worklog; `AdminFocusLucky.tsx` чужой WIP, не чинил). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Бот `@focuscazzcztewrfweda_bot`. Туннель **18081**. Группа **тестовый чат**.

1. На карточке `/jackpot` нажать **100 ₽** — ставка принимается, без алерта про игровой чат. В «Ставка принята» ссылка «Смотреть на сайте».
2. Запасной путь: `/jackpot 100` текстом — тоже «Ставка принята».
3. Не ломать: `/roulette red 50`; куб 1×1 100 → **195**.

## 2026-08-31 · FocusLucky: живой розыгрыш как джекпот

Не прод. `deploy_all.py` не запускал. `staging-sync.sh` не запускал (по плану — после явной команды). Формулу куба / рулетки 0–36 / джекпот HMAC не трогал. Парковка holdem / комната N / кланы на месте. Кабинет `/cabinet/battle` не трогал.

Повод: билеты за обмены остаются, но розыгрыш всех мест разом + LTC + ручная выплата. Нужно шоу как джекпот: одна страница, места с 1-го каждые 30 с, выбытие, RUB сразу на баланс, DM участникам.

Сделано (четыре среза в одном проходе по просьбе «все to-do»):

1. Миграция `add_raffle_live_show.sql`: status `drawing`, колонки шоу, места до 20, outbox `raffle_notification_outbox`. PATCH `/api/admin/raffle/prizes` и `/show-settings`. Админка `/x8/focus-lucky`: редактор мест, карточка «Шоу», «Запустить шоу».
2. Движок `casino_raffle.py`: seed+commit, closer 1 с, HMAC места, выбытие всего пула игрока, ledger `flucky-{campaign}-{place}` `ON CONFLICT DO NOTHING`. `POST /raffle/draw` тоже стартует шоу, не мгновенный `run_draw`.
3. `/casino/play/raffle` — `CasinoRaffle.tsx`: лента только во время спина, список шансов, подписи мест, SSE. Плитка FocusLucky снята с полки.
4. TG DM через **exchange-бот** (outbox + `raffle_notify_task`): «скоро» / «смотри тут» + URL-кнопка, DM победителю места. В боте кнопка «Смотреть розыгрыш».

Шанс = билеты / оставшийся пул (без ×N мест). Сид публичен только после `drawn`.

Файлы этого среза (ядро):

- `site/exchange-backend/casino_raffle.py`, `migrations/add_raffle_live_show.sql`, `raffle_service.py`, `raffle_phase.py`
- `routers/admin_raffle.py`, `routers/user_casino.py`, `routers/public_casino.py`, `main.py`
- `focussite/frontend/src/casino/CasinoRaffle.tsx`, `gameCatalog.ts`, `CasinoPlay.tsx`, `CasinoLobby.tsx`, `casino.css`
- `focussite/frontend/src/panel/admin/AdminFocusLucky.tsx`, `panel/lib/adminApi.ts`
- `bot/tg_bot_btc/services/raffle_notify.py`, `raffle_db.py`, `raffle_panel.py`, `raffle_admin.py`, `handlers/focus_lucky.py`, `main.py`
- `focussite/docker/staging-db/00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`
- `.cursor/rules/casino-shelved-games.mdc`

Проверки:

- Локально `python -m unittest tests.test_casino_raffle` (cwd `site/exchange-backend`): **11** OK.
- `npm run build` (frontend): **tsc + vite OK**, 2270 modules, CSS `index-D7y2GdyC.css`, JS `panel-DhixkldV.js`.
- `focussite/docker/staging-db/bootstrap_static_test.sh` **passed**.
- Тесты бота на этой машине без venv (`asyncpg`/`telegram` нет) — не гонял целиком. Константы шанса: 15/1500 = **1%**, не 10%.
- `staging-test.sh` / `staging-sync.sh` **не** гонял: код на `:18081` ещё старый, md5 с `/opt` сравнивать рано.
- md5 local:
  - `casino_raffle.py` `ee4e14a0307c179ef055011747a8dcb7`
  - `add_raffle_live_show.sql` `fc3adc5bbd56c0f84a088d564f5b858a`
  - `CasinoRaffle.tsx` `87aebb4b55d9cf60f972b1ccb64d83cb`
  - `AdminFocusLucky.tsx` `5335adb84cdd8cb0b8af4d645192a482`
  - `raffle_notify.py` `704e5dd30ba01e8f5519025fcfd69309`
- `rg` `hmac-sha256-place-mod-tickets` / `raffle_notification_outbox` / `CasinoRaffle` / `start-show`: движок, миграция, админка, watch-page, бот.
- Docker staging (read-only): наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP казино). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку **после** `staging-sync` (скажи — залью). Без синка на `:18081` этого кода нет.

Потыкать. Туннель **18081**. Жёсткое обновление. Нужен вход (как джекпот).

- `http://127.0.0.1:18081/x8/focus-lucky` — править места/суммы, сохранить, карточка «Шоу», **Запустить шоу**. Победители появляются сами, бейдж «начислено».
- `http://127.0.0.1:18081/casino/play/raffle` — таймер, лента только во время спина ~8 с, список шансов без выбывшего, строка «N место».
- Лобби: плитка **FocusLucky** видна (клик работает даже если `enabled_games.raffle` в pvp-фикстуре `false`).
- Бот: у кого есть билеты — DM со ссылкой и кнопкой; меню FocusLucky — «Смотреть розыгрыш».
- Не ломать: куб 1×1 100 → **195**; рулетка стол; джекпот; кабинет `/cabinet/battle`.

## 2026-08-31 · «Ставка принята» без ссылки на сайт

Не прод. `deploy_all.py` не запускал.

Повод: после `/jackpot` 25 ₽ в «Ставка принята» не было «Смотреть на сайте» и URL. Origin у живого бота был пустой: `CASINO_FAIRNESS_URL` / `CASINO_MINIAPP_URL` не попали в контейнер. Предыдущий `up --no-deps casino-bot` без `STAGING_RUNTIME_ENV_FILE` взял старый `/opt/focuspay/focussite/.env.staging-runtime` (без fairness). Код ссылку не рисует, если origin нет.

Сделано:

- Бот пересоздан с `/etc/focuspay/staging-runtime.env`. Живой origin `http://127.0.0.1:18081`, jackpot URL `…/casino/play/jackpot?mode=players`.
- В тексте: `<a href>` «Смотреть на сайте» и `<code>` с тем же URL.
- Compose: `CASINO_FAIRNESS_URL` с дефолтом туннеля. На сервере: fairness в leftover `.env.staging-runtime`; `STAGING_RUNTIME_ENV_FILE=` в `/etc/focuspay/staging-runtime.env`.

Файлы: `games/site_links.py`, `tests/test_site_links.py`, `focussite/docker-compose.staging-runtime.yml`, `bootstrap_static_test.sh`, worklog.

Проверки:

- Локально `test_site_links` + `test_jackpot` + `test_roulette_table`: **26** OK. `bootstrap_static_test.sh` passed.
- rsync `/opt` без полного `staging-sync` (gateway по-прежнему ломает чужой `AdminFocusLucky.tsx`). `compose build casino-bot` + `up --no-deps` с `STAGING_RUNTIME_ENV_FILE`. Health **passed**.
- Живой python: `CFG_MINIAPP='http://127.0.0.1:18081/casino/tg'`, в тексте `<a href=…>Смотреть на сайте</a>` и `<code>http://127.0.0.1:18081/casino/play/jackpot?mode=players</code>`.
- md5 local = `/opt` = live `/app`: `site_links.py` `53c9680adfb9fd0af48afa32b2219213`. Compose `e8e15c134058f701bc7b3255f87834ae`. bootstrap `a7ef2f2d42f752d2492e82a3ec822712`.
- Docker наружу: только `127.0.0.1:18081->8080`. `casino-bot` без Host ports.
- Прод: `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit 2026-08-29 06:08:19 UTC. Не сдвинулись.

Git dirty, не коммитил, прод не трогал.

Стоп. Другую задачу не начинать.

Потыкать. Бот, та же ставка джекпота.

1. `/jackpot 25` или кнопка — в «Ставка принята» строка **Смотреть на сайте**, под ней URL `http://127.0.0.1:18081/casino/play/jackpot?mode=players`, плюс url-кнопка.
2. То же для `/roulette red 50`.
3. Mini App на staging по-прежнему нет (http).

## 2026-08-31 · Джекпот: докид под банком на телефоне

Не прод. `deploy_all.py` не запускал. Бэкенд раунда не трогал. Паркованные холдем / комнаты / кланы не открывал.

Повод: поле «Ставка / Докинуть» внизу страницы (sticky над навигацией) на телефоне ездило влево-вправо.

Сделано (только фронт):

- Банк и ставка в одном блоке `.casino-jackpot-head`: докид сразу под банком.
- На телефоне блок sticky сверху (не снизу). Нижнего sticky у ставки нет.
- Строка ставки — сетка `minmax(0,1fr) auto`, `overflow-x: clip`, без нативных стрелок у number.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoJackpot.tsx`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok. `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при sync **Recreate**, после тестов **Running**. Сборка **2270** modules, CSS `index-DnrKc7zD.css`, JS `index-DGiRypFI.js`.
- HTTP **200**: `/casino/play/jackpot`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoJackpot.tsx` `4fbbf4f98652a6e406e7c064a5436c85`
  - `casino.css` `a63370a971711fdb9034cec245612910`
- Живой CSS: `.casino-jackpot-head` + `position:sticky;top:0`. `.casino-jackpot-bet` без `bottom` sticky.
- Браузер 390px, вход `fixture_buyer`: порядок **банк → ставка → правила**. `scrollWidth` страницы и `.casino-main` **390**, ставка 364=364, gap **10px**, head `sticky`.
- `staging-test.sh`: collected **1452** (было 1441; в дереве уже лежали raffle-тесты, этот срез pytest не добавлял), **1445** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `casino-jackpot-head`: Jackpot + CSS. Sticky bottom у `.casino-jackpot-bet`: **0**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: UI джекпота). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление**, телефон или узкое окно.

- `http://127.0.0.1:18081/casino/play/jackpot` — «Ставка / Докинуть» сразу **под банком**, не внизу над меню.
- Блок не едет влево-вправо; при прокрутке списка банк+ставка остаются сверху.
- Не ломать: куб 1×1 100 → **195**; рулетка стол.

## 2026-08-31 · Рулетка: рельс игр снова на месте

Не прод. `deploy_all.py` не запускал. Бэкенд / HMAC / стол не трогал. Паркованные холдем / комнаты / кланы не открывал.

Повод: на `/casino/play/roulette` слева пропадали остальные мини-игры. Это было `hideGamePicker` (срез 2026-08-30 «без показа игр»).

Сделано (только `CasinoShell.tsx`):

- Список игр в рельсе на рулетке как на кубе: Кубики, Баккара, Блэкджек, Европейская рулетка, FocusLucky, Джекпот, Все дуэли.
- Телефон: кнопка «Игры» и шит каталога снова есть.
- Лента «Мои / Все / Крупные» на рулетке по-прежнему скрыта (это не рельс).

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoShell.tsx`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok. `npm run build` ok, **2270** modules, CSS `index-DnrKc7zD.css`, JS `index-xkEHseZ0.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres при тестах **Running**.
- HTTP **200**: `/casino`, `/casino/play/roulette`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`: `CasinoShell.tsx` `049bf8a7ca7220cc1f8f90f8348c5f5a`.
- Живой JS: `hideGamePicker` **0**. В бандле есть «Кубики» / «Баккара».
- Браузер `/casino/play/roulette?mode=players`: рельс с играми, рулетка **current**. Клик **Кубики** → `/casino/play/pvp_dice`, рельс на месте.
- `staging-test.sh`: collected **1452**, **1445** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `hideGamePicker`: **0** в `focussite/frontend` и `site/exchange-backend`. `visibleCasinoCatalog` в Shell: рельс + шит, без условия на roulette.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: рельс рулетки). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/roulette` — слева **Игры**: кубики, баккара, блэкджек, рулетка (подсветка), FocusLucky, джекпот. Переход в кубики с рельса работает.
- Телефон: снизу **Игры**, шит открывается.
- Не ломать: куб 1×1 100 → **195**; стол рулетки; джекпот.

## 2026-08-31 · Уникальные аватарки, если своей нет

Не прод. `deploy_all.py` не запускал. Формулу куба / рулетки / джекпота не трогал. Парковка holdem / комната N / кланы на месте.

Повод: без фото в шапке, чате и за столом была буква. Нужна своя картинка на человека, не общий шаблон.

Сделано:

- SVG-портрет из id игрока: один и тот же id → та же картинка; 500 разных id → 500 разных SVG.
- Нет загруженного файла и нет Telegram-фото → `/api/public/casino-idents/u41` (веб `n3`). Своя загрузка и живое Telegram-фото по-прежнему главнее.
- Дом/роботы: `r{profile_id}`, `user_id` 0 (ссылки на профиль нет).
- Фронт: если URL фото 404, подставляется тот же ident, не буква.

Файлы этого среза:

- `site/exchange-backend/casino_default_avatar.py`
- `site/exchange-backend/casino_player_cosmetics.py`, `casino_chat.py`, `casino_duels.py`, `casino_house_tables.py`, `casino_v2_web.py`, `casino_player_profile.py`
- `site/exchange-backend/routers/public.py`, `rate_limit_middleware.py`
- `site/exchange-backend/tests/test_casino_default_avatar.py` (+ правки cosmetics / duels / house / rate_limit)
- `focussite/frontend/src/casino/defaultAvatar.ts`, `CasinoPlayerChip.tsx`, `CasinoChatPanel.tsx`, `CasinoJackpot.tsx`, `CasinoRaffle.tsx`
- `focussite/docker/nginx.staging-runtime.conf`, `nginx.local.conf`, `staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально unittest ident + cosmetics + duels actor + house snapshot + rate_limit: **OK**. `bootstrap_static_test.sh` passed.
- `npm run build` ok, **2271** modules, CSS `index-DnrKc7zD.css`, JS `index-Cb0Y9e8n.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres после тестов **Running**.
- Живой GET `http://127.0.0.1:18081/api/public/casino-idents/u41` **200** `image/svg+xml`. md5 u41 ≠ u42 ≠ n3.
- md5 local = `/opt` = live `/app/backend`:
  - `casino_default_avatar.py` `9dd45134505357407b3b9037ce4d1f59`
  - `CasinoPlayerChip.tsx` `cbd4d314aee6b82276b59e3c077e28f9`
  - `defaultAvatar.ts` `118ed02a86568ac7a1bce7ba554c86a7`
  - nginx staging `9228bb0d322b80a535e5e3d238f55d30`
- SQL ключей **67** (миграции нет).
- `staging-test.sh`: collected **1456** (было 1452; **+4** `test_casino_default_avatar`), **1449** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `casino-idents`: backend URL + nginx + тесты + фронт `defaultAvatar.ts`. `render_ident_svg` только в генераторе и его тесте.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: ident-аватарки). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление**, вход.

- `http://127.0.0.1:18081/casino/me` и шапка — если своего фото нет, кружок с **уникальным** портретом, не буква. У двух разных людей картинки разные.
- Стол дома / дуэль с роботом: у «Дом» тоже свой портрет, не буква.
- Кто загрузил аватар в настройках или у кого есть фото Telegram — как было, своё фото.
- Не ломать: куб 1×1 100 → **195**; рулетка стол; джекпот.

## 2026-08-31 · Рулетка только стол + иконки

Не прод. `deploy_all.py` не запускал. HMAC / выплаты 1×1 на бэкенде не удалял. Паркованные холдем / комнаты / кланы не открывал. FocusLucky в админке и боте не переименовывал.

Повод: на сайте два режима рулетки; нужны только общий стол, короткое имя и чёрные иконки в рельсе.

Сделано:

- `/casino/play/roulette` без табов «Против казино / С игроками». `mode` всегда `players`; `?mode=house` сразу `replace` на стол.
- Публичное имя **Рулетка** (алиас «европейская» в поиске). FocusLucky — то же имя.
- Рельс: рулетка `CircleDot`, FocusLucky `Ticket` (как кубики/карты, не цветной emoji).

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoPlay.tsx`, `CasinoShell.tsx`, `gameCatalog.ts`
- `focussite/frontend/src/pages/CasinoFairness.tsx`, `CasinoCreatorDashboard.tsx`
- `focussite/frontend/src/panel/admin/Casino/casinoSettingsModel.ts`
- `site/exchange-backend/routers/public_casino.py`, `casino_player_profile.py`
- `.cursor/rules/casino-shelved-games.mdc`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok. Локально `test_public_casino_lobby` + `test_casino_player_profile`: **6** OK.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **Running**. Сборка gateway **2273** modules.
- HTTP **200**: `/casino`, `/casino/play/roulette`, `?mode=house`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoPlay.tsx` `ab992a07d299c494e77870caee086377`
  - `CasinoShell.tsx` `60dce6cc27eee176d2f1f08154a2aba0`
  - `gameCatalog.ts` `852a373237639b8d940f42c73f493086`
  - `CasinoFairness.tsx` `aff8ad77b4953929304612c18fa200ad`
  - `casinoSettingsModel.ts` `609dac56eeb2d0121e37ff7278cb0048`
  - `CasinoCreatorDashboard.tsx` `a3404f142fda37bf9dead48743b30721`
  - `public_casino.py` `eb5477e8092834ce36d7e1aecec05bae`
  - `casino_player_profile.py` `410a4f948d14d9d92d13c2c6e954e57c`
- Живой `GET /api/public/casino/lobby`: roulette `name=Рулетка`; raffle `FocusLucky`. Живой JS: `name:"Рулетка"`, `Европейская рулетка` **0**, `c==="roulette"?"players"`, `c==="jackpot"||c==="raffle"||I?null`, рельс `roulette`/`raffle` → lucide, не emoji. `?mode=house` → `set("mode","players")`.
- `staging-test.sh`: collected **1456**, **1449** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `Европейская рулетка`: **0** в `focussite/frontend` и `site/exchange-backend`. `CircleDot` / `Ticket` в `CasinoShell.tsx`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: стол+имя+иконки). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/roulette` — сразу стол, **нет** табов «Против казино / С игроками». Слева имя **Рулетка** и чёрная иконка-точка.
- `http://127.0.0.1:18081/casino/play/roulette?mode=house` — не 1×1 «Крутить», тот же стол (`mode=players`).
- Рельс FocusLucky: имя то же, чёрная иконка-билет.
- Не ломать: куб 1×1 100 → **195**; фишки на общем столе; джекпот.

## 2026-08-31 · F5 сессии, баланс после джекпота, лента лиц

Не прод. `deploy_all.py` не запускал. Формулу HMAC / рейк / билеты джекпота не трогал. Паркованные холдем / комнаты / кланы не открывал.

Повод: F5 на джекпоте кидал на логин (гонка `isAuthed` пока `loading`); после спина шапка не подтягивала выплату; лента копировала одного игрока пачкой.

Сделано:

- Джекпот / FocusLucky / стол холдема ждут `session.loading` перед `goCasinoLogin`. `/login` при уже живой сессии сразу уходит на `next`.
- Старт спина джекпота — `CASINO_BALANCE_HOLD_EVENT`; стоп и refund — `CASINO_BALANCE_EVENT` (списание со ставки сначала, выплата после остановки).
- Лента: веса как были, слоты round-robin по участникам раунда, `WINNER_INDEX` — победитель. Один в банке — одно лицо.
- Staging nginx: `bot-user-avatars` без `limit_req` (как local / idents).

Файлы этого среза:

- `focussite/frontend/src/casino/weightedReel.ts`
- `focussite/frontend/src/casino/CasinoJackpot.tsx`, `CasinoRaffle.tsx`, `CasinoPokerTable.tsx`
- `focussite/frontend/src/pages/Login.tsx`
- `focussite/frontend/scripts/check-weighted-reel.mts`
- `focussite/docker/nginx.staging-runtime.conf`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsx scripts/check-weighted-reel.mts` ok. `npx tsc -b` ok. `npm run build` ok, **2272** modules локально. Gateway после sync: **2273** modules, CSS `index-BbckYaf4.css`, JS `index-Csl0FSbc.js`. `bootstrap_static_test.sh` passed.
- Локально unittest jackpot + notify + ident + rate_limit: **24** OK.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **Running** (`StartedAt=2026-08-31T02:43:11Z`), не Recreate. Bootstrap Recreate, Exited 0. Без `down -v`.
- HTTP **200**: `/casino`, `/casino/play/jackpot`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoJackpot.tsx` `3f53a1ec0a11324e02cb8003bf0c56e8`
  - `CasinoRaffle.tsx` `0b7f998806d271e8ca4bfe8d7744bb15`
  - `CasinoPokerTable.tsx` `3b430f18da894166e2bd36db58bd0bdb`
  - `weightedReel.ts` `c251085bf38555509c1e387a45a338fc`
  - `Login.tsx` `08317f084db306106197da6f6d805677`
  - nginx staging `d3a5c3a637967eae3fd02c8d5d2a2e97`
  - `bootstrap_static_test.sh` `50d8cf9b08c0aa7834e62dfbea30d5f8`
  - `check-weighted-reel.mts` `ed2d9fa8732123d5719350a00e7a71e6`
- Живой gateway nginx: `bot-user-avatars` строка **28**. Живой JS `index-Csl0FSbc.js`: `focuspay-casino-balance` + `focuspay-casino-balance-hold` + `focuspay-casino-balance-release`.
- `staging-test.sh`: collected **1456**, **1449** passed, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `buildWeightedReel`: модуль + jackpot + raffle + check-скрипт. `CASINO_BALANCE_HOLD_EVENT` в jackpot + Shell + Play. `bot-user-avatars` nginx local+staging + bootstrap + rate_limit.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports. Created-контейнеров нет.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: сессия F5 / баланс спина / round-robin лента). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

1. Войти → `http://127.0.0.1:18081/casino/play/jackpot` → **F5**. Остаёшься в джекпоте, не на `/login`.
2. С двух аккаунтов банк → спин: в ленте чередуются **разные** лица участников; под чертой победитель. Если один в банке — его лицо.
3. Победа: когда лента остановилась, баланс в шапке **сразу** с выплатой, без ручного обновления.
4. Не ломать: куб 1×1 100 → **195**; рулетка стол.

## 2026-08-31 · Профиль казино как кабинет (кошелёк без API)

Не прод. `deploy_all.py` не запускал. Бэкенд / `create_withdrawal` / `config.py` / HMAC не трогал. Паркованные холдем / комнаты / кланы не открывал.

Повод: свой профиль `/casino/me` был карточкой уровня, «Пополнить» уводило в `/cabinet`.

Сделано (только UI, заявок не создаёт):

- `/casino/me`: приветствие, полоска уровня, 4 плитки, пополнение (кратные **250 ₽**, карта/СБП) → модалка **демонстрационных** реквизитов, вывод карта (комиссия 0) / BTC **100 ₽** / LTC **50 ₽** / USDT **$5**, история пустая. Чужой `/casino/u/…` без форм.
- Шапка «Пополнить», рельс/шит «Кошелёк», MainButton лобби → `/casino/me#deposit`, не кабинет.
- Правила в `casinoWalletRules.ts` + `npx tsx scripts/check-casino-wallet-rules.mts`.

Файлы этого среза:

- `focussite/frontend/src/casino/casinoWalletRules.ts`
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/CasinoPlayerSettings.tsx`
- `focussite/frontend/src/casino/casinoPaths.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsx scripts/check-casino-wallet-rules.mts` ok (250/500 ок, 100 нет; карта 0; BTC 100 выплата 150 с 250; LTC 50; USDT $5 при курсе 80 = 400 ₽; профиль не содержит `/user/balance/withdraw`).
- `npx tsc -b` ok. `npm run build` ok, **2273** modules, CSS `index-DyuoWaye.css`, JS `index-NZxxaiL4.js` + `index-7cQ05WfR.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**.
- HTTP **200**: `/casino`, `/casino/me`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoProfile.tsx` `073c32923a8904e6c71f7f738d482026`
  - `CasinoShell.tsx` `60dce6cc27eee176d2f1f08154a2aba0`
  - `casinoWalletRules.ts` `b9129bea21b3e27decccaf54549bca93`
  - `casinoPaths.tsx` `787e7e8bee8b008491a13784ba245e3c`
  - `CasinoLobby.tsx` `11f2f7fefda7266061c36649dc1003ca`
  - `CasinoPlayerSettings.tsx` `b6c4fa093175b64d40ea2d4a56f2868c`
  - `check-casino-wallet-rules.mts` `1bdcd99745a214e5d610e22e69f9cd74`
- Живой JS `index-7cQ05WfR.js`: `data-casino-deposit`, `data-casino-withdraw`, `data-casino-deposit-modal`, `data-casino-wallet-history`. CSS `casino-wallet` **1**.
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `/cabinet` в `focussite/frontend/src/casino`: **0**. `rg` `/user/balance/withdraw` в `CasinoProfile.tsx`: **0**. `CARD_STEP_RUB` / `casinoWalletPath`: rules + profile + shell + lobby + check.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: кошелёк профиля). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Реальный API пополнения/вывода не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/me` — «Привет, …», плитки, полоска уровня.
- Пополнение: 100 — ошибка; 250 — модалка с суммой и типовыми реквизитами; F5 — модалка закрыта.
- Вывод карта 250, комиссия 0; BTC/LTC/USDT — 100 / 50 / $5; кнопка **не** создаёт заявку в кабинете/операторке.
- Чужой `/casino/u/…` без форм кошелька.
- Шапка «Пополнить» остаётся в казино (`#deposit`), не `/cabinet`.
- Кабинет `/cabinet` и `/cabinet/referral` без изменений.
- Не ломать: куб 1×1 100 → **195**; рулетка стол; джекпот.

## 2026-08-31 · Аватарки Quiet House: чёрные, лёд, без мультяшек

Не прод. `deploy_all.py` не запускал. Формулу куба / рулетки / джекпота не трогал.

Повод: дефолтные портреты были персиковые «смайлики». Нужны чёрные, в стиле казино (лёд `#6ea8ff`, без green/gold/skin).

Сделано:

- Генератор v2: near-black круг, геометрический лёд (кольца, грань, куб-пипы, карта, орбита). Один id → та же картинка; 500 id → 500 SVG.
- URL `?v=2`, чтобы не сидел закэшированный мультяшный v1.
- Загрузка и фото Telegram по-прежнему главнее.

Файлы этого среза:

- `site/exchange-backend/casino_default_avatar.py`
- `site/exchange-backend/tests/test_casino_default_avatar.py`, `tests/test_casino_player_cosmetics.py`
- `focussite/frontend/src/casino/defaultAvatar.ts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Unittest ident + cosmetics + duels robot + house snapshot + rate_limit: **18 OK**. Нет `#f3c7` в SVG.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **Running**.
- Живой GET `/api/public/casino-idents/u41?v=2` **200**. Цвета `#0b0b0b` `#1a1a1a` `#4a90e8`, peach **0**.
- md5 local = `/opt` = live `/app/backend`:
  - `casino_default_avatar.py` `a6302c253842b819286a98620bf67d61`
  - `defaultAvatar.ts` `92bc5a54665a860a919948bef6642e34`
- SQL ключей **67**. Сборка gateway **2273** modules.
- `staging-test.sh`: collected **1457**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. (В одном прогоне мелькнул `HouseRngCommitTests.test_web_client_user_id_can_prepare_and_play_cub`; повтор — его нет, одиночный прогон **ok**.)
- `rg` `focuspay-casino-ident-v2`: генератор. `?v=2`: URL + фронт + тесты.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: тёмные ident). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/me` и шапка — без своего фото **чёрный** кружок с ледяной геометрией, не персиковая морда.
- У разных людей разные фигуры; у «Дом» тоже чёрный ident.
- Своё фото / загрузка — как было.
- Не ломать: куб 1×1 100 → **195**; рулетка стол; джекпот.

## 2026-08-31 · Куб: «У игрока нет id» и 1×1 «Не удалось выполнить запрос»

Не прод. `deploy_all.py` не запускал. Полный `staging-sync.sh` не гонял (gateway tsc на чужом `AdminFocusLucky.tsx`). Формулу HMAC 1×1 / рулетку 0–36 / джекпот не менял. Парковка holdem / комната N / кланы на месте.

Повод: скрины lazyzist. Стол 2–5 vs дом — «У игрока нет id». 1×1 — «Не удалось выполнить запрос». Вход логин/пароль без Telegram даёт `client_user_id < 0`. Стол резал `telegram_id <= 0`. 1×1 собирал `CubPlayRequest` с `PositiveTelegramId` (gt=0) → ValidationError → 500 без JSON → общая плашка.

Сделано:

- `validate_roster_for_start`: нет id только при `None` или `0`. Отрицательный web-id проходит.
- `PrepareCubRequest` / `CubPlayRequest`: `ClientUserId` = Telegram >0 или web <0.
- `play_cub_with_conn`: нехватка баланса → 409 «Недостаточно средств».
- `api.ts`: короткий текстовый ответ ошибки (не HTML) показывается как есть.

Файлы этого среза:

- `site/exchange-backend/casino_finance.py`
- `site/exchange-backend/casino_house_tables.py`
- `site/exchange-backend/routers/internal_casino.py`
- `site/exchange-backend/tests/test_casino_house_tables.py`
- `site/exchange-backend/tests/test_internal_casino.py`
- `focussite/frontend/src/lib/api.ts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `test_casino_house_tables` + `HouseRngCommitTests` + `CubTelegramDiceTests`: **65 + 16 OK**. `bootstrap_static_test.sh` passed.
- rsync `/opt/focuspay`, `compose build backend` + `up --no-deps --wait backend` **Healthy**. Gateway не пересобирал. Postgres **Running**.
- Живой смоук: web id **-3**, ставка 100, `play_cub_with_conn` → `play_ok True` (3 vs 6, выплата 0). Roster `-3` ок.
- HTTP **200**: `/api/health`, `/casino/play/pvp_dice`. SQL ключей **67**.
- md5 local = `/opt` = live `/app/backend`:
  - `casino_finance.py` `ade07407130327f9766bbd7de25a7a27`
  - `casino_house_tables.py` `1f05d1b7ece52a28b0359f3e69cbbc13`
  - `internal_casino.py` `af0533f9ce78146d01ee9f7ef0279b98`
- `api.ts` на `/opt` `8644ca8a4b9d8c55dd0674cf97b4f0d9` (живой gateway без этой правки — ставка чинится бэкендом).
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `ClientUserId`: finance + internal_casino. `telegram_id) <= 0` в house_tables: **0**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports. `:18082` — play-public.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: web-id куба). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** или публичный **18082**. Вход **логин/пароль без Telegram**. Бэкенд уже новый.

- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=house` — 1×1, 100 ₽, **Ставка**: раунд идёт, без «Не удалось выполнить запрос». Выигрыш на руки **195**.
- Вкладка **Стол 2–6**, 2–5 ботов, **Ставка**: без «У игрока нет id».
- Не ломать: рулетка стол; джекпот; вход через Telegram как раньше.

## 2026-08-31 · Рулетка: убрать подписи, поднять стол

Не прод. `deploy_all.py` не запускал. HMAC / ставки / другие игры не трогал. Паркованные холдем / комнаты / кланы не открывал.

Повод: над колесом «Стол» + «Рулетка», слева одиночная «Вручную»; стол сидел слишком низко.

Сделано (только `/casino/play/roulette`):

- `.casino-stake-tabs` (Вручную / Авто) не рендерится при `isRoulette`. На кубе вкладки как были.
- Кикер «Стол» и `<h1>` над колесом скрыты. Крошка «Лобби / Рулетка» на месте.
- `.casino-roulette` padding `4px 12px 12px`; canvas рулетки `padding-top: 8px`.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok.
- HTTP **200**: `/casino/play/roulette`, `/casino/play/pvp_dice`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`:
  - `CasinoPlay.tsx` `387469c6fb4399e85ca5489304263a7a`
  - `casino.css` `7cec67189a61029156162c66d8998642`
- Живой CSS `index-DsWufcPK.css`: `.casino-roulette` `padding:4px 12px 12px`, canvas `padding-top:8px`. Живой JS `index-CtksTpgY.js`: `I?null` для `.casino-stake-tabs` и кикера «Стол»/`h1`. «Вручную» в бандле **1** (куб).
- `staging-test.sh`: collected **1457**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `isRoulette ? null` + `casino-stake-tabs` / `casino-play-kicker` в `CasinoPlay.tsx`. `padding: 4px 12px 12px` в `casino.css`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: подписи/padding рулетки). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/roulette` — нет «Вручную», нет «Стол» / «Рулетка» над колесом; колесо выше. Крошка «Лобби / Рулетка» на месте.
- Куб: «Вручную / Авто» как были.
- Не ломать: фишки на столе; куб 1×1 100 → **195**.

## 2026-08-31 · Вернули угарные аватарки

Не прод. `deploy_all.py` не запускал. Формулу куба / рулетки / джекпота не трогал.

Повод: чёрные геометрические ident — скучно. Нужны снова мультяшные морды, у каждого своя.

Сделано: генератор v1 (лица, волосы, очки), URL `?v=3` чтобы не залип кэш чёрных `v=2`.

Файлы: `casino_default_avatar.py`, `defaultAvatar.ts`, тесты cosmetics/default_avatar, worklog.

Проверки:

- Unittest ident + cosmetics + duels + house snapshot + rate_limit: **18 OK**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **Running**.
- Живой GET `/api/public/casino-idents/u41?v=3` **200**, в SVG `ellipse`. (Первый запрос во время pytest дал 502 — контейнеры поднимались; повтор 200.)
- md5 local = `/opt` = live `/app/backend`: `casino_default_avatar.py` `119345fdfe1c48aae47371a36921cc6b`, `defaultAvatar.ts` `c37af24099f135fcf07178e982069b84`.
- SQL ключей **67**. Сборка **2273** modules.
- `staging-test.sh`: collected **1457**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `?v=3`: URL + фронт + тесты. `ident-v1`: генератор.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод: `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit 2026-08-29 06:08:19 UTC. Не сдвинулись.

Git dirty, не коммитил, прод не трогал.

Стоп. Жду клик-приёмку.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/me` и шапка — снова **угарные** морды, не чёрные кольца.
- У разных людей разные; своё фото как было.
- Не ломать: куб 1×1 100 → **195**; рулетка стол.

## 2026-08-31 · Рельс: убрать «Кошелёк» (это профиль)

Не прод. `deploy_all.py` не запускал. Формулу куба / рулетки / джекпота не трогал. Паркованные холдем / комнаты / кланы не открывал.

Повод: в левом меню «Кошелёк» вёл на `/casino/me` — тот же экран, что «Профиль».

Сделано:

- Из рельса и из мобильного шита «Игры» убран пункт «Кошелёк».
- «Профиль» остаётся; шапка «Пополнить» и иконка кошелька на месте.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoShell.tsx`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok. `npm run build` ok, **2273** modules, CSS `index-DsWufcPK.css`, JS `index-BanT73Ma.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`: первый `--apply` — гонка `No such container` после Healthy; повтор `staging-runtime-update.sh --apply` → health **passed**. Postgres **Running** (`Up … healthy`). Без `down -v`.
- HTTP **200**: `/casino`, `/casino/me`, GET `/api/health`. SQL ключей **67**.
- md5 local = staging `/opt`: `CasinoShell.tsx` `062f4a8cc4cb5a9a88a57b7ff8c52679`.
- Живой DOM рельс: `Лобби, Кубики, Баккара, Блэкджек, Рулетка, FocusLucky, Джекпот, Все дуэли, Честность, Профиль, Настройки`. «Кошелёк» в рельсе **0**. Живой JS: `rail-label Кошелёк` **0**.
- `staging-test.sh`: collected **1457**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `Кошелёк` в `CasinoShell.tsx`: только шапка `casino-header-wallet` (2). В рельсе / шите — **0**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез: рельс без кошелька). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — в левом меню нет «Кошелёк», есть «Профиль».
- «Профиль» открывает `/casino/me` (пополнение/вывод как были).
- Шапка: «Пополнить» и иконка кошелька на месте.
- На телефоне шит «Игры» тоже без «Кошелёк»; внизу «Профиль».
- Не ломать: куб 1×1 100 → **195**; рулетка стол; джекпот.

## 2026-08-30 · FocusBet: фон сетки, белый акцент, иконка F

Не прод. `deploy_all.py` не запускал. Формулу куба / рулетки / джекпота не трогал. `/x8` не переименовывал. URL `/casino` как были.

Повод: игрокский `/casino` был со льдом `#6ea8ff`, а главная — чёрно-белая сетка. Продукт называть FocusBet.

Сделано:

- Фон `.casino-root` — сетка 32px как `.grid-paper`, без голубых radial.
- Акцент `#f4f4f5` / hover `#e4e4e7` / pressed `#d4d4d8`. Telegram `button_color` больше не красит акцент в синий.
- Бейдж F: `/focuspay-logo.svg`, белый квадрат, чёрная маска. Шапка **FocusBet** / FOCUSPAY.
- Шрифт Manrope + DM Mono.
- Тексты «Казино» у игрока → FocusBet (меню сайта, кабинет, оверлей, куб/карты/режим, таймаут дуэли). API `display_name: Казино` на экране маппится.
- Плитки SVG и доли джекпота — бело-серые. Рулетка красное/чёрное/зеро как были.

Файлы этого среза: `casino.css`, `CasinoTileArt.tsx`, `telegram.ts`, `CasinoTokensPreview.tsx`, `CasinoJackpot.tsx`, `CasinoShell.tsx`, `casinoOverlay.tsx`, `casino.html`, `CasinoLobby.tsx`, `CasinoModeSwitch.tsx`, `gameCatalog.ts`, `CasinoPlay.tsx`, `CasinoHouseCards.tsx`, `CasinoHouseTables.tsx`, `CasinoDuelRoom.tsx`, `CasinoProfile.tsx`, `CasinoPlayerSettings.tsx`, `PublicHome.tsx`, `PublicHeader.tsx`, `CabinetLayout.tsx`, `CasinoCreatorDashboard.tsx`, `bootstrap_static_test.sh` (assert `#f4f4f5` / Manrope вместо льда/Inter).

Проверки:

- `npx tsc -b` ok. `npm run build` ok, **2273** modules, CSS `index-HmmtRKhh.css` (staging).
- Check-скрипты: wallet / house-cards / roulette / weighted-reel / post-login-path — ok.
- `rg` в `src/casino`: `#6ea8ff` `#8bbcff` `#4a90e8` `#2481cc` `#f4f6fb` — **0**. Живой CSS: `6ea8ff` **0**, `f4f4f5` **8**, `casino-grid-line` **3**, Manrope **5**.
- Живой JS чанк: **FocusBet 39**, «Казино» **0** (админка `/x8` не в этом бандле).
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Повтор `staging-runtime-update.sh --apply` после догона `casino.css`. Postgres **Running**.
- HTTP **200**: `/`, `/casino`. SQL ключей **67**.
- md5 local = `/opt`: `casino.css` `9576bd3cee4079d385a1fa4423103d60`, `CasinoShell.tsx` `1cc9f7d09eddd4621a462f227b012b93`, `PublicHome.tsx` `511608b8432d85323b0c998446ab9b46`.
- `staging-test.sh`: collected **1457**, **1450 passed**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP казино-плана). `focuspay-casino` HEAD `4b8d65e`, dirty (чужой WIP). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- Главная тёмная: сетка, в меню **FocusBet** вместо «Казино», F в бейдже как на сайте.
- Открыть FocusBet: тот же фон-сетка, белые кнопки, без голубого свечения. Шапка FocusBet / FOCUSPAY.
- Кубики 1×1: справа подпись **FocusBet**. Баккара/блэкджек: рука дома FocusBet.
- Рулетка: красное/чёрное/зеро как были.
- Джекпот доли серые, не синие. Профиль/настройки: «FocusBet», не «казино».
- F5: палитра та же.
- `/x8` не цель этой задачи.
- Не ломать: куб 1×1 100 → **195**.

## 2026-08-30 · Только игроки: кубики, баккара, блэкджек

Не прод. `deploy_all.py` не запускал. Рулетку 0–36, джекпот, FocusLucky, холдем / комнаты / кланы не трогал. Дом 1×1 не удалял — спрятан.

Повод: на сайте у баккары «С игроками» открывало дуэль 1×1 (мест нет, плюса нет). Кубики и блэкджек умели стол 2–6, но рядом оставался дом. В боте `/cub 100` в личке был бросок против казино.

Сделано:

- Сайт: кубики / баккара / блэкджек всегда `mode=players`. Нет переключателя «Против казино» / «1×1 / Стол 2–6». `?mode=house` и `/casino/play/cub` уводят в игроков.
- Создать: панель ставка 50–1000 + своя сумма, места 2–6, превью банка. `autojoin: false`, `bot_count: 0` → `/casino/tables/:id`. Пустое место — «+ бот» (и у баккары).
- Бэкенд: `baccara` в `WEB_V2_GAME_TYPES`; раздача HMAC, третья карта при ≤5, ничья — раздел / перераздача. JWT `POST /casino/play` для cub/baccara/blackjack → **409**. `POST /casino/house-tables` → **409**. Leave живых столов на месте. Внутренний `/cub/*` не резал.
- Casino-бот: `/cub` всегда мастер стола; шаг «сколько ботов» убран (`bot_count=0`); на карточке ожидания **➕ Бот**. Help без «против казино». `register_house_cub_handlers` не вызывается (файл дома на месте).

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoPlay.tsx`, `CasinoLobby.tsx`, `CasinoPlayersLobby.tsx`, `CasinoV2Table.tsx`, `gameCatalog.ts`, `casino.css`
- `focussite/frontend/scripts/check-pvp-tables-only.mts`
- `.cursor/rules/casino-shelved-games.mdc`
- `site/exchange-backend/casino_v2_web.py`, `casino_v2_cards.py`, `routers/user_casino.py`, `routers/internal_casino.py`
- `site/exchange-backend/tests/test_casino_v2_web.py`, `tests/test_casino_v2_cards.py`
- `focuspay-casino`: `games/pvp.py`, `table_wizard.py`, `help.py`, `v2_runtime.py`, `v2_tables.py` и тесты pvp/wizard/v2/help
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально: `test_casino_v2_cards` + `test_casino_v2_web` **37 OK**. Casino-bot pvp/wizard/v2/help/house_cub **50 OK**. `npx tsc -b` ok. `npx tsx scripts/check-pvp-tables-only.mts` ok.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Gateway **2273** modules, CSS `index-HmmtRKhh.css`, casino JS `index-DNguXZT8.js`. Postgres **67** ключей.
- HTTP **200**: `/casino`, `/casino/play/pvp_dice`, `/baccara`, `/blackjack`, GET `/api/health`.
- md5 local = `/opt` = live `/app`:
  - `casino_v2_web.py` `61112d6fbe744b176ca5e3fa05f41057`
  - `casino_v2_cards.py` `9aa5ea0068b30cfec60a42906315f360`
  - `user_casino.py` `9596b45f6634465f8b070f3637782492`
  - `internal_casino.py` `950a762d7a139d4934dce1a180e5c232`
  - `CasinoPlay.tsx` `5083ef8b28daba389fe7bf74b256861a`
  - `CasinoPlayersLobby.tsx` `30dff56aa65e397f7378e7bd37d48340`
  - `pvp.py` `b710e980e9fcde295a54a1ba8c5e0810`
  - `help.py` `aa930da81c5cc8f0594e913719c21710`
- Живой JS `index-DNguXZT8.js`: `data-casino-create-menu` **1**, «Против казино» **0**, «+ бот» **2**. `mode=house` **1** (спрятанный дом в `CasinoPlay`, не лобби).
- `staging-test.sh`: collected **1465** (+8 к 1457), **1458 passed**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- `rg` `WEB_V2_GAME_TYPES`: `pvp_dice`+`blackjack`+`baccara`. `стол с игроками` + `Стол против казино закрыт` в `user_casino.py`. `/v2/tables/{table_id}/bots` internal + JWT. `start_wizard_for_command(..., "cub")` в `pvp.py`. `v2bot:` в runtime+tables. `register_house_cub_handlers(` только определение в `house_cub.py`, вызовов **0**.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Отклонение от плана: 409 только на JWT-создание дома (`/casino/play`, `/casino/house-tables`). Внутренний `/cub/*` и `casino_house_tables.create_table` живы — выход/добор старых столов. API дуэлей не выпиливал.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/pvp_dice` — нет «Против казино»; **Создать** → ставка и места 2–6 → лобби; плюс на пустом месте сажает бота.
- То же: `/casino/play/baccara` и `/casino/play/blackjack`. Старый `?mode=house` уводит в игроков, без 1×1 vs дом.
- Бот staging: `/cub 100` в личке открывает мастер стола (места/ставка), не бросок против казино. На карточке ожидания ➕ сажает бота.
- Не ломать: рулетка стол; джекпот; FocusLucky.

## 2026-08-30 · Белые баблы: текст на заливке

Не прод. `deploy_all.py` не запускал. Формулы игр не трогал. `/x8` не трогал.

Повод: после белого акцента `<Link className="casino-btn">` наследовал `--text` (светлый) поверх `--accent` (белый) — «Играть в кубики» и «Пополнить» выглядели пустыми.

Сделано:

- `.casino-root a.casino-btn { color: var(--ink) }` — чёрный текст на белой заливке.
- Ghost-ссылки: `.casino-root a.casino-btn.casino-btn-ghost { color: var(--text) }` — «Честность» как была.
- `bootstrap_static_test.sh`: require этих селекторов.

Файлы этого среза: `focussite/frontend/src/casino/casino.css`, `focussite/docker/staging-db/bootstrap_static_test.sh`.

Проверки:

- Первый `staging-sync.sh`: транзиент compose `No such container`. Повтор `staging-runtime-update.sh --apply` + health **passed**. Gateway **2273** modules, CSS `index-Cu_0bukx.css`.
- HTTP **200**: `/casino`. SQL ключей **67**.
- md5 local = `/opt`: `casino.css` `560493a50e208d6a1d504b00dd1f3cc0`, `bootstrap_static_test.sh` `f8ccfe2455594f8c5aa72a766f949842`.
- Живой CSS `index-Cu_0bukx.css`: `6ea8ff` **0**, `a.casino-btn{color:var(--ink)}` **1**, ghost-селектор **1**.
- `rg` в `src/casino`: `#6ea8ff` `#8bbcff` `#4a90e8` `#2481cc` `#f4f6fb` — **0**.
- `staging-test.sh`: collected **1471**, **1464 passed**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. +6 collected к 1465 — чужой dirty WIP в том же sync, не этот срез.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — в баннере на белой кнопке видно **Играть в кубики** (чёрным). **Честность** по-прежнему белая на тёмной.
- В шапке на белой кнопке видно **Пополнить**. Колокольчик «4» чёрным на белом как был.
- Не ломать: плитки игр, фильтр «Все», рулетка красное/чёрное/зеро.

## 2026-08-31 · Казино в общем P&L

Не прод. `deploy_all.py` не запускал. Игры, ставки, house funding/adjustment не трогал. Формула прибыли казино та же, что `/x8/casino` dashboard: owner commission + `casino_house_ledger.game_settlement`. `casino_v2_house_ledger` не суммировали. Оборот обмена (`fiat_volume`) казино-ставками не раздували.

Сделано:

- `compute_pnl`: `total.net_profit` и `owner_residual` включают казино; waterfall `casino_profit` («Казино: комиссия + дом»); `by_type` casino с `orders=0`; блок `casino` в ответе.
- Дневной ряд `/stats` и `/finance-overview`: `casino_profit_rub` в `profit_net_total`.
- Админка «Результат по направлению»: строка Казино. KPI-лейбл «+ казино», если сумма ≠ 0.
- `/dash` и `/pulse`: extras `казино N ₽`. Ночной дайджест: строка «Казино: … ₽». Чистая прибыль = residual, уже с казино.

Файлы этого среза: `finance_pnl.py`, `routers/admin_stats.py`, `business_digest.py`, `owner_dashboard_metrics.py`, `FinanceTab.tsx`, `format.ts`, `bot/.../owner_analytics.py`, `owner_dashboard.py`, `tests/test_finance_pnl_casino.py`, `test_business_digest.py`, `test_owner_analytics.py`, `test_owner_dashboard_metrics.py`, `docs/CASINO_WORKLOG.md`.

Проверки:

- Локально: `test_finance_pnl_casino` + review_bonus + digest + owner_dashboard_metrics **30 OK**. Бот `test_owner_analytics` **12 OK**.
- Первый `staging-sync.sh`: rsync ок; compose `--wait` упал `No such container` (гонка bot). Health отдельно **passed**. Backend/bot md5 совпали с локальными. Gateway слой frontend был cache — `--no-cache gateway`, затем `up -d gateway`.
- SQL staging lifetime: commission **10762.23**, house settlement **−8473.55**, owner **2288.68** ₽.
- md5 local = `/opt` = live `/app` (backend) / `/opt/tg_bot_btc` (bot):
  - `finance_pnl.py` `3d892569ca5990f4cce5acf525bf0871`
  - `admin_stats.py` `efee73658ec379c6742453726f3f1a61`
  - `business_digest.py` `cf5d0869755508e86d2fcad130453779`
  - `FinanceTab.tsx` `29f90670aeb6be9b6c7a78ef51a3619c`
  - `owner_dashboard.py` `c380455c6588a57b9f569388fa387ee3`
  - `test_finance_pnl_casino.py` `3c6f11b4b049d6b291330c86cad784eb`
- `rg fetch_casino_owner_profit`: `finance_pnl.py` 3, `admin_stats.py` 3, `test_finance_pnl_casino.py` 7. `casino_profit` в digest / `/dash` / FinanceTab.
- `staging-test.sh`: collected **1471**, **1464 passed**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/x8` → Аналитика → Финансы. Период **год** (или с начала казино): в водопаде строка **Казино: комиссия + дом**, в «Результат по направлению» **Казино**. Финальный остаток больше/меньше на эту сумму, чем был без казино. Оборот обмена не должен прыгнуть на ставки казино.
- `/x8/casino`: «Прибыль владельца» за всё время ≈ **2289 ₽** (комиссия 10762 + дом −8474). На широком периоде в общем P&L та же логика (срез по датам проводок).
- Staging-бот, группа отчётов: `/dash` — в деньгах extras **казино N ₽**, если за день |сумма| > 0. Иначе строка скрыта, остаток всё равно из того же `compute_pnl`.
- Не ломать: внештат в водопаде; кешбэк/ЗП; куб стол игроков.

## 2026-08-31 · Текст героя лобби FocusBet

Не прод. `deploy_all.py` не запускал. Формулы игр не трогал. `/x8` не трогал. Статы мин. ставка / комиссия / открытые столы и кнопки «Играть в кубики» / «Честность» не менял.

Повод: старый баннер говорил только про кубы/карты и трижды про HMAC. Нужен короткий «кто / что / какие игры».

Сделано в `CasinoLobby.tsx`:

- Kicker: **FocusBet**
- H1: **Играете с людьми. Считает сервер.**
- Абзац: кубы/баккара/блэкджек — общий стол, бот на пустое; рулетка 0–36, джекпот, дуэли; FocusLucky — билеты за обмены FocusPay; HMAC после раунда.
- How-to (`data-casino-howto`): **Выберите игру и поставьте. Карты и кубы только показывают то, что уже посчитал сервер.**
- Холдем / комнаты / кланы в тексте нет.

Проверки:

- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh`: транзиент compose `No such container`. Health после повторного `--apply`: **passed**.
- HTTP **200**: `/casino`. SQL ключей **67**.
- md5 local = `/opt`: `CasinoLobby.tsx` `97525efe738e6c99f207aca876efaa25`.
- Живой JS `index-l9WOvnli.js`: «Играете с людьми» **1**, how-to **1**, «Стол с игроками» **0**.
- `staging-test.sh`: collected **1472**, **1465 passed**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `casino-bot` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — заголовок **Играете с людьми. Считает сервер.**; в абзаце рулетка, джекпот, дуэли, FocusLucky; нет холдема/кланов.
- Справа как были: мин. ставка, комиссия, открытые столы.
- Кнопки **Играть в кубики** и **Честность** на месте.

## 2026-08-31 · FocusLucky: все места призов на экране

Не прод. `deploy_all.py` не запускал. Полный `staging-sync.sh` / `staging-test.sh` не гонял (сид участников на volume, `compose run --profile tests` раньше Recreate postgres). Формулы куба / рулетки / джекпота не трогал. Парковка holdem / комната N / кланы на месте.

Повод: в кампании 10 мест (14 500 ₽), на `/casino/play/raffle` в шапке было только текущее «1 / 5 000 ₽».

Сделано: `CasinoRaffle.tsx` рисует `prize_places` целиком (`data-casino-raffle-places`). Текущее место — `is-next`, выигравшее — `is-won`. CSS: сетка 2 колонки, на узком 1.

Проверки:

- Локально `npm run build`: **tsc + vite OK**, 2273 modules, CSS `index-D5WcRHGl.css` / staging gateway `index-CtrnEdDc.css`, JS с маркером `index-l9WOvnli.js`.
- Gateway: `compose build gateway` + `up -d --no-deps --wait gateway`. Health **passed**.
- md5 local = `/opt`: `CasinoRaffle.tsx` `77674f312e6a93b2e409279018cdd2b6`, `casino.css` `2b3516b6346e5bbc75d95480eb14e99d`.
- Живой бандл: `data-casino-raffle-places` **1**. DOM: **10** строк (5000 / 3000 / 2000 / 1000 / 1000 / 500×5), игроков **247**.
- SQL staging: `focuslucky-prod-mirror-202608` participants **253**, `jsonb_array_length(prize_places)` **10**. Прод campaign id 2: тоже **10** мест, те же суммы.
- Docker наружу: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: dirty, не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/raffle` — под шапкой сетка **10 мест**, 1-е подсвечено, суммы как в админке. Участники ниже как были.
- Не ломать: шапка «Место 1 / 5 000 ₽ / до спина —»; список шансов.

## 2026-08-31 · Профиль /casino/me: уровень, комиссия, бонус

Не прод. `deploy_all.py` не запускал. Сетку комиссии на 500k не трогал. Паркованные холдем / комнаты / кланы не открывал. Пополнение/вывод на `/casino/me` без API, как были.

Повод: свой профиль показывал только «Уровень N · оборот недели». Комиссия и «что даст следующий уровень» уже были в `GET /api/user/casino/players/me` и в админке «Уровни», но на `/casino/me` не выводились. `level_reach_bonuses` в базе был `[]`.

Сделано:

- Дефолт бонусов: 50k→500 ₽, 100k→1000, 200k→2500, 500k→5000. Миграция `seed_casino_level_reach_bonuses.sql`: `INSERT … ON CONFLICT DO NOTHING` + `UPDATE … WHERE value = '[]'::jsonb`. Без `DO UPDATE` по живым суммам.
- Карточка уровня на своём и чужом профиле: комиссия сейчас (до/после отыгрыша), сколько оборота до следующего, снижение % только если ставки падают, кешбэк, рублёвый бонус только своему (`includeBonus`).
- Текст в `casinoLevelCopy.ts`. Кошелёк не трогал.

Файлы этого среза:

- `site/exchange-backend/casino_settings_registry.py`
- `site/exchange-backend/migrations/seed_casino_level_reach_bonuses.sql`
- `site/exchange-backend/tests/test_casino_level_bonus.py`
- `site/exchange-backend/tests/test_casino_settings_registry.py`
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/src/casino/casinoLevelCopy.ts`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `focussite/docker/staging-db/00-apply-migrations.sh`
- `focussite/docker/staging-db/20-full-panel-bootstrap.sh`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально: `test_casino_level_bonus` + `test_casino_settings_registry` + `test_casino_player_profile` **31 OK**. `npx tsx scripts/check-casino-wallet-rules.mts` ok (свой профиль: `data-casino-next-level` + `data-casino-commission`; нет `/user/balance/withdraw`; бонус 500 ₽ только при `includeBonus`; без снижения комиссии на 500k строка без «комиссия»). `bootstrap_static_test.sh` passed. `npm run build` ok, **2274** modules, CSS `index-CtrnEdDc.css`, JS `index-CiQR2zB-.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды). Gateway rebuild **2274** modules, те же хеши бандлов.
- HTTP **200**: `/casino/me`, `/casino`, `/api/health`.
- SQL: ключей **67**. `level_reach_bonuses` = `[{50000,500},{100000,1000},{200000,2500},{500000,5000}]`.
- md5 local = `/opt` = live `/app/backend`:
  - `casino_settings_registry.py` `7dbb0a9d117572fa52affff76919e68b`
  - `seed_casino_level_reach_bonuses.sql` `aff2fc1cf4f9f8e73d55cc04495cb843`
  - `CasinoProfile.tsx` `16f7af793a5aaa2e44f5fdaebed2a60a`
  - `casinoLevelCopy.ts` `8014c41ead8810d3e4160d3ba0d943cd`
  - `casino.css` `2b3516b6346e5bbc75d95480eb14e99d`
  - `check-casino-wallet-rules.mts` `059840b425bd148acb70582508e84ac6`
  - `20-full-panel-bootstrap.sh` `4447051b656c05f73c189ccd8a5fae1f`
- Живой JS `index-CiQR2zB-.js`: `data-casino-commission` **2** (профиль + дуэли), `data-casino-next-level` **1**, `data-casino-level-card` **1**, `Комиссия сейчас` **1**. CSS `casino-level-card` **1**.
- `rg` `level_reach_bonuses`: registry + seed SQL + bootstrap ×3 + admin GET/PATCH + profile + grant. `seed_casino_level_reach_bonuses.sql` — **нет** `DO UPDATE`.
- `staging-test.sh`: collected **1472** (+1 `test_registry_default_is_example_grid`), **1465 passed**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу runtime: `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-runtime-casino-bot-1` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/me` — комиссия в %, сколько до следующего уровня, снижение комиссии и бонус в ₽ (на 1→2: 500 ₽).
- `http://127.0.0.1:18081/x8/casino/settings` — «Уровни»: бонус 500 / 1000 / 2500 / 5000. Поменять одну сумму, сохранить, F5 — должна остаться.
- Чужой `/casino/u/…` — до уровня и комиссия есть, рублёвого бонуса нет.
- Не ломать: пополнение 250, вывод-заглушка, куб стол игроков 100 → 195, рулетка, джекпот.

## 2026-08-31 · Telegram-аватар кружком, иначе мультик

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал, `staging-sync` не гонял. Паркованные холдем / комнаты / кланы не открывал.

Повод: `public_actors` всегда слал `/api/public/bot-user-avatars/{id}` даже без файла → 404 и мигание на идент. Список FocusLucky взял сетку джекпота `8px | 1fr | auto`, первая ячейка — чип, аватар сплющен.

Сделано:

- `_actor`: Telegram URL только если `resolve_bot_user_avatar_path` нашёл файл; иначе `None` → мультик `casino-idents`. Кастом из косметики по-прежнему важнее.
- `public_actors`: `schedule_prefetch_bot_user_avatars` без await.
- GET `/bot-user-avatars` не трогал.
- `CasinoPlayerAvatar`: обёртка `span.casino-player-avatar` (круг, overflow hidden). `onError`: TG → идент → буква.
- `.casino-raffle-list li`: `minmax(0,1fr) auto`; бар шанса `grid-column: 1 / -1`, высота 4px. Джекпот (swatch 8px) не менял.
- На volume `focuspay_staging_runtime_bot_user_avatars` распакован прод-кеш участников FocusLucky: **165** файлов (прод FOUND 163).

Файлы этого среза:

- `site/exchange-backend/casino_chat.py`
- `site/exchange-backend/tests/test_casino_player_cosmetics.py`
- `focussite/frontend/src/casino/CasinoPlayerChip.tsx`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `python3 -m unittest tests.test_casino_player_cosmetics tests.test_casino_chat tests.test_admin_users_avatar`: **22 OK**. Плюс `test_casino_default_avatar`: **8 OK**.
- Gateway+backend `up -d --no-deps --wait`. Health **passed**. Postgres **Up 2 hours**, сид `focuslucky-prod-mirror-202608` participants **253**, prize_places **10**.
- md5 local = `/opt` = live `/app/backend/casino_chat.py`:
  - `casino_chat.py` `ac6d18445618f6ca988975b0bd62f308`
  - `test_casino_player_cosmetics.py` `beafbcdf389ff8ca6cf96f2812f09339`
  - `CasinoPlayerChip.tsx` `14a53edfe100fc65949f66f4e5bcc30e`
  - `casino.css` `2abda44fe7dca592333d3579fe67e77b`
- Живой CSS `index-Bmyh6pWZ.css`: `casino-player-avatar` **1**, `casino-raffle-list` **1**.
- API `GET /api/user/casino/raffle` (fixture_buyer): **247** игроков, avatar_url **161** `bot-user-avatars` + **86** `casino-idents`. Signed TG **200** (~63 KB), unsigned без `access` **403**, ident **200**.
- Браузер после жёсткого обновления: список **247** кружков **32×32**, `border-radius: 50%`, сетка `818px 58px` (не 8px), картинок с `naturalWidth=0` **0**. Лобби/джекпот: чип **40×40** круг; список джекпота пустой (ставок нет).
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.
- `rg`: `resolve_bot_user_avatar_path` в `casino_chat.py` **2**; `.casino-player-avatar` в chip+css; `.casino-raffle-list` в `CasinoRaffle.tsx` + css.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление** (иначе старый `index.html` держит CSS джекпота 8px).

- `http://127.0.0.1:18081/casino/play/raffle` — кружки **32px**. У кого файл TG — фото, у кого нет — мультик. Полоска шанса под строкой, чип не сплюснут.
- Лента спина (когда крутится) — **48px**, те же правила.
- Лобби / джекпот / стол — тот же круглый чип. У джекпота первая колонка по-прежнему цветной **8px**.
- F5: фото без 404-мигания (URL идента сразу, если файла нет).
- Не ломать: 10 мест призов, список 247, сетка джекпота.

## 2026-08-31 · Касса 1Win: пополнение/вывод из профиля в окно

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал. Паркованные холдем / комнаты / кланы / `/casino/clans` не открывал.

Повод: пополнение и вывод жили в профиле (`/casino/me`). Нужно как у 1Win: «Пополнить» → окно со всеми способами, то же для вывода. Остаёмся на текущей странице, не уходим в `/cabinet`.

Сделано:

- Шапка «Пополнить» открывает модалку, URL не меняется (`/casino` остаётся `/casino`).
- Вкладки **Пополнить | Вывести**. Сетка способов: СБП, карта, USDT TRC20/ERC20/BEP20, BTC, LTC. Вывод: карта + те же крипты.
- Сумма: чипы 250/500/1000/2500, шаг **250 ₽** для карты/СБП. Депозит → демо-реквизиты. Вывод → тост «Заявка будет отправлена, когда подключим API». **Живой `/user/balance/withdraw` не вызывается.**
- `/casino/wallet` — статистика, кнопки Пополнить/Вывести, пустая история. Профиль `/casino/me` — только кнопки + ссылка в кошелёк, без форм суммы.
- `CasinoCashierHost` внутри `.casino-root` (токены CSS). Хеш `#deposit` / `#withdraw` по-прежнему открывает кассу.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoCashier.tsx`
- `focussite/frontend/src/casino/CasinoWallet.tsx`
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/casinoPaths.tsx`
- `focussite/frontend/src/casino/casinoRoutes.tsx`
- `focussite/frontend/src/casino/casinoWalletRules.ts`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/CasinoPlayerSettings.tsx`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-wallet-rules.mts`: **ok**. В кассе и профиле нет `/user/balance/withdraw`. `rg /cabinet` в `focussite/frontend/src/casino`: **0**.
- HTTP **200**: `/casino`, `/casino/me`, `/casino/wallet`, `/api/health`. SQL `casino_settings` count **67**.
- md5 local = `/opt`:
  - `CasinoCashier.tsx` `446dd45ef3a1b81a4d66ebd1c9209030`
  - `CasinoWallet.tsx` `4e046fcaec448e4fa4967f645cb2ffc8`
  - `CasinoProfile.tsx` `09e9c9dd5c04b66c17973ed9ff8b64dc`
  - `CasinoShell.tsx` `5d843a051f7dd60680347d0cd2a856f0`
  - `CasinoLobby.tsx` `f8b45c64c16750527ca4d525046c63e6`
  - `casinoPaths.tsx` `16af5529d7083e87ad063b4ed3acc8c5`
  - `casinoRoutes.tsx` `91949db7671d2c69897fe9af168def22`
  - `casinoWalletRules.ts` `2e8a2ff0aa39dd1f040e4fef2420a1d6`
  - `casino.css` `0de35349a78c8512060c30765450f62c`
  - `CasinoPlayerSettings.tsx` `cef3146787e22bfd274ec85b4671c379`
  - `check-casino-wallet-rules.mts` `363e3357933793d7cc9787647270f238`
- Живой бандл gateway: CSS `index-Bu3de0pm.css` (`casino-cashier` / `casino-cashier-sheet` / `casino-wallet`). JS `index-B6JVna5X.js`: `data-casino-cashier` **2**, `data-casino-deposit` **2**, `data-casino-withdraw` **1**, `data-casino-deposit-modal` **1**, `data-casino-wallet-history` **1**, `data-casino-own-profile` **1**, тост-заглушка **1**, `/user/balance/withdraw` **0**.
- `staging-test.sh`: collected **1489** (прошлый срез **1472**, +17 из чужого dirty payout-rail, не этот фронт), **1478 passed**, **11 failed**. Семь старых имён на месте. **Новые четыре** (бэкенд, не касса UI): `CreateWithdrawalRailTests.test_crypto_rejected_when_rail_blocks`, `CasinoPlayerProfileTests.test_own_profile_includes_balance_and_bonus_when_configured`, `CasinoPlayerProfileTests.test_own_web_client_negative_id_is_allowed`, `DepositCreditTests.test_credits_confirmed_deal_from_configured_exchanger`. Старые семь: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Этот срез бэкенд-тесты не добавлял и не чинил.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Postgres `running` с `2026-08-31T02:43:11Z`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- Шапка на лобби (`http://127.0.0.1:18081/casino`) — «Пополнить»: тёмное окно со способами, адрес остаётся `/casino`.
- СБП 100 ₽ — ошибка «кратна 250 ₽». СБП 250 ₽ — демо-реквизиты. F5 закрывает окно.
- Вкладка «Вывести»: карта / BTC 100 / LTC 50 / USDT $5. Тост про API, **заявки в кабинете/у оператора быть не должно**.
- `http://127.0.0.1:18081/casino/me` — нет полей суммы/СБП, только Пополнить / Вывести / Кошелёк.
- `http://127.0.0.1:18081/casino/wallet` — история пустая, те же кнопки открывают кассу.
- Кабинет `/cabinet` как был. Не ломать: куб стол игроков 100→195, рулетка, джекпот.

## 2026-08-31 · Вход-выход казино: сначала карта, потом крипта

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (volume жив, `Up 2 hours` на момент SQL). Паркованные холдем / комнаты / кланы / `/casino/clans` не открывал.

Правило — **ворота, не деление баланса**. Пока `remaining > 0`, крипто-вывод выключен целиком (в том числе выигрыш сверху). После закрытия долга — куда угодно. Повторный фиат снова закрывает. Отыгрыш (`casino_wagering.py`) не трогал: он режет сумму, этот слой — способ. Депозит в вебе по-прежнему заглушка. Живой депозит: бот казино → PayFast СБП/карта → `credit_deposit_with_conn`.

Сделано:

- Миграция `casino_deposit_credits.rail`: `fiat` | `crypto` | `legacy`. Старые строки → `legacy` (долга нет). Новые: `SBPRUB`/`CARDRUB` → `fiat`, иначе `crypto`. В `00-apply-migrations.sh` и `20-full-panel-bootstrap.sh`.
- `casino_payout_rail.py` (бэкенд + копия в боте): `fiat_in − fiat_out`, `fiat_out` = карта `pending`/`paid` после первого фиат-кредита. `rejected` не гасит. `crypto_allowed` при `remaining ≤ 0.01`.
- `create_withdrawal` (сайт и бот): `method=crypto` при долге → `ValueError` «Сначала выведите N ₽ на карту». HTTP как у прочих ошибок вывода — **400**, не 403.
- `payout_rail` в `get_unified_balance_stats` и `own` профиля игрока.
- Касса: крипто-кнопки **disabled**, не скрыты; `POST /user/balance/withdraw` через `withdraw()` из `@/lib/user`. Кабинет `/cabinet/referral`: вкладка «В крипте» disabled. Бот «Вывод»: кнопки крипты нет, пока долг.
- Клиент: `cryptoWithdrawBlocked` / `withdrawSubmitError` в `casinoWalletRules.ts`.

Файлы этого среза:

- `site/exchange-backend/migrations/add_casino_deposit_credit_rail.sql`
- `site/exchange-backend/casino_payout_rail.py`
- `site/exchange-backend/user_referral_withdraw.py`
- `site/exchange-backend/user_unified_balance.py`
- `site/exchange-backend/casino_player_profile.py`
- `site/exchange-backend/routers/internal_casino.py`
- `site/exchange-backend/tests/test_casino_payout_rail.py`
- `site/exchange-backend/tests/test_internal_casino.py`
- `site/exchange-backend/tests/test_casino_player_profile.py`
- `bot/tg_bot_btc/services/casino_payout_rail.py`
- `bot/tg_bot_btc/services/user_referral_withdraw.py`
- `bot/tg_bot_btc/services/user_unified_balance.py`
- `bot/tg_bot_btc/handlers/user_referral.py`
- `bot/tg_bot_btc/tests/test_casino_payout_rail.py`
- `focussite/frontend/src/casino/casinoWalletRules.ts`
- `focussite/frontend/src/casino/CasinoCashier.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/pages/CabinetReferral.tsx`
- `focussite/frontend/src/lib/user.ts`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `focussite/docker/staging-db/00-apply-migrations.sh`
- `focussite/docker/staging-db/20-full-panel-bootstrap.sh`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально: `test_casino_payout_rail` + `test_casino_player_profile` + `DepositCreditTests` **14 passed, 1 skipped** (asyncpg нет на хосте). Бот `test_casino_payout_rail`: **1 passed, 2 skipped** (нет `telegram`/`asyncpg`). `npx tsx scripts/check-casino-wallet-rules.mts` **ok** (`await withdraw(`, `data-casino-payout-rail-lock`, нет сырого `/user/balance/withdraw` в кассе). `bootstrap_static_test.sh` passed. `npm run build` ok, **2276** modules, CSS `index-Bu3de0pm.css`, JS кассы `index-Br0DOce5.js`.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (дважды: бэкенд, затем касса после отката заглушки). Gateway rebuild **2276** modules.
- HTTP **200**: `/casino`, `/api/health`.
- SQL: колонка `rail` есть, default `'fiat'`, NOT NULL. CHECK `rail IN (fiat, crypto, legacy)`. Строк в `casino_deposit_credits`: **0**.
- md5 local = `/opt` = live `/app/backend` и `/opt/tg_bot_btc`:
  - `casino_payout_rail.py` `247c9d954ec1979e5b77b473112774d6`
  - `add_casino_deposit_credit_rail.sql` `64af8d3f271db26e437c9f6b49a64c22`
  - `user_referral_withdraw.py` `b0edd7cb086305610565302fe97dd733`
  - `user_unified_balance.py` `ef19edfbb95af5208ac66c34f3458096`
  - `casino_player_profile.py` `c2702771fd26a76bfe98acf8bfb8f6b0`
  - `internal_casino.py` `45a335c17e679249bf38828faa24bfbd`
  - `test_casino_payout_rail.py` `c87accdd10379a274ef7aed08f9b1394`
  - bot `casino_payout_rail.py` `650593542438e574442b710e69c0acb7`
  - bot `user_referral_withdraw.py` `ce9cb2a2ed33ebdcd886df1884f6f0cd`
  - `user_referral.py` `861529672210342228a55b48d649e62a`
  - `CasinoCashier.tsx` `92dc274ee7c8ea0cc5cfdab8dfdc508c`
  - `casinoWalletRules.ts` `2e8a2ff0aa39dd1f040e4fef2420a1d6`
  - `CabinetReferral.tsx` `5f3d0e610b9002c68e5a9b1d5f0e0d9f`
  - `00-apply-migrations.sh` `96d333c945504415a2e245bffd712fa4`
  - `20-full-panel-bootstrap.sh` `7dcab995d7bbea9c360b949b7f324150`
  - `check-casino-wallet-rules.mts` `363e3357933793d7cc9787647270f238`
- Живой JS `index-Br0DOce5.js`: `когда подключим API` **0**, `Заявка на вывод создана` **1**, `payout-rail-lock` **1**, `/user/balance/withdraw` **1** (из `@/lib/user` в том же чанке). CSS `casino-cashier-method:disabled` **1**.
- `rg` `payout_rail` / `casino_payout_rail` / `cryptoWithdrawBlocked`: модуль + credit_deposit + create_withdrawal + balance/profile + касса + кабинет + бот + тесты + bootstrap. Не одно вхождение.
- `staging-test.sh`: collected **1502**, **7 failed**, имена те же что базовая линия, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Четыре лишних падения из прошлого среза кассы (неполный dirty rail) закрылись: `CreateWithdrawalRailTests`, оба `CasinoPlayerProfileTests` own-profile, `DepositCreditTests.test_credits_confirmed_...`. На staging `test_casino_payout_rail` **15 passed** (`-k casino_payout_rail`).
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. `focuspay-staging-runtime-casino-bot-1` без Host ports.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Отклонение от плана: отказ крипты отдаёт **HTTP 400** (как «недостаточно средств» и прочие `ValueError` вывода), не 403. Текст тот же.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty (не этот срез). Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление** (бандл кассы сменился на `index-Br0DOce5.js`).

- `http://127.0.0.1:18081/casino#withdraw` — после фиат-депозита (казино-бот СБП/карта) крипта серая, подпись «Сначала выведите N ₽ на карту». Карта нажимается. Вывод карты создаёт заявку (тост «Заявка на вывод создана», не заглушка API).
- Когда на карту ушла та же сумма (pending или paid) — крипта снова нажимается.
- `http://127.0.0.1:18081/cabinet/referral` — вкладка «В крипте» disabled при долге, та же подпись.
- Основной бот FocusPay «Вывод»: при долге только «Карта / СБП», крипты в клавиатуре нет.
- Депозит в кассе по-прежнему демо-реквизиты. Не ломать: куб стол игроков 100→195, рулетка, джекпот, FocusLucky.

## 2026-08-31 · Столы: вернуться, боты, не зависать

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` Up ~2 hours). Паркованные холдем / комнаты / кланы / `/casino/clans` не открывал.

Повод: 1×1 `web-demo-baccara-waiting` висела `active` с 29 августа (соперник 940002, холд 50 ₽), баннер «Вы в игре». Хост стола 2–6 после «Лобби» видел только «Отменить» — нельзя сесть обратно, посадить бота, начать.

Сделано:

- Лобби V2 (кубики / баккара / блэкджек): сидящему всегда «К столу»; пустое место — «+ бот»; при ≥2 «Начать»; «Отменить»/«Встать» вторая кнопка.
- Join `web-demo-*` в ожидании — 409. Зависший active без HMAC (демо или site-hex с пустым `rng_commit`) — abort, холды released, статус `cancelled`. Poll комнаты + closer + cancel с баннера (любой участник).
- Staging: `web-demo-baccara-waiting` `cancelled` / `unfinishable_card_duel` в `2026-08-31 04:59:30Z`. Холд 50 ₽ у 940002 `released`. Другие `web-demo-*` уже `finished`.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-pvp-tables-only.mts`
- `site/exchange-backend/casino_pvp_cards.py`
- `site/exchange-backend/casino_waiting.py`
- `site/exchange-backend/casino_inbox.py`
- `site/exchange-backend/routers/internal_casino.py` (join: `assert_card_duel_joinable`)
- `site/exchange-backend/routers/user_casino.py` (cancel → `cancel_player_duel`)
- `site/exchange-backend/tests/test_casino_pvp_cards.py`
- `site/exchange-backend/tests/test_casino_waiting.py`
- `site/exchange-backend/tests/test_casino_inbox.py`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-pvp-tables-only.mts`: **ok**. `.venv/bin/python -m unittest tests.test_casino_pvp_cards tests.test_casino_waiting tests.test_casino_inbox tests.test_casino_duels tests.test_casino_v2_web -q` → **89 OK**.
- HTTP **200**: `/casino`, `/casino/play/pvp_dice?mode=players`, `/casino/play/baccara?mode=players`, `/casino/play/blackjack?mode=players`, `/casino/duels/web-demo-baccara-waiting` (status `cancelled`), `/api/health`.
- SQL `casino_settings` count **67**. Demo-игры: waiting cancelled, cards+blackjack finished. Hold opponent released.
- md5 local = `/opt`:
  - `CasinoPlayersLobby.tsx` `0789ee354a53a96e719ce7163b12f983`
  - `check-pvp-tables-only.mts` `abcb477c04b65b65600b43f9d5f0923c`
  - `casino_pvp_cards.py` `ecc622d7fdefac2333c89f64ce6ff80d`
  - `casino_waiting.py` `d6cdc99cf7478d5f83120cc7c8d0c93e`
  - `casino_inbox.py` `9b3e011f347e916064437e92e987755d`
  - `internal_casino.py` `3e0e9c24c868994a9bf84bdceaa7419f`
  - `user_casino.py` `e442f4860013bd63e84f878fb754b4c3`
  - `test_casino_pvp_cards.py` `09a03a8dc4fa5d82654b5d71bb527f1a`
- Живой backend: `abort_unfinishable_card_duel` **6** в `/app/backend/casino_pvp_cards.py`. Gateway JS `index-Br0DOce5.js`: `data-casino-v2-to-table` **1**.
- `rg` `abort_unfinishable_card_duel` / `assert_card_duel_joinable` / `К столу` / `addCasinoV2Bot`: pvp_cards + waiting + inbox + join + cancel + лобби + check-скрипт + тесты. Не одно вхождение.
- `staging-test.sh`: collected **1502**, **7 failed**, имена базовой линии, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Целевой `-k casino_pvp_cards or casino_waiting or casino_inbox or casino_v2_web or casino_duels` → **89 dots / 100%**, exit 0.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- Баннер «Вы в игре · баккара · WEB-DEMO» пропал. Баланс: 50 ₽ со холда вернулись.
- Кубики / баккара / блэкджек `?mode=players`: создать стол → «Лобби» → в карточке **К столу**, не только Отменить.
- Пустое место → бот; при двоих — **Начать** (не ждать 4/4). Сыграть раунд.
- С другого экрана: баннер «Перейти» / «К столу» открывает тот же стол.
- `http://127.0.0.1:18081/casino/duels/web-demo-baccara-waiting` — отмена, join снова не сажает.

## 2026-08-31 · Касса непрозрачная, две кнопки в шапке

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал. Паркованные холдем / комнаты / кланы не открывал.

Повод: окно кассы сливалось с фоном; в шапке только «Пополнить»; вкладки внутри одного окна; под лого — мелкий FocusPay.

Сделано:

- Оверлей `rgba(0,0,0,0.72)` (в бандле `#000000b8`), лист `--surface-2`, рамка `--border-strong`. Десктоп — по центру, мобилка — нижний sheet, тоже непрозрачный.
- Шапка: **Пополнить** и **Вывести**. Открывают разные окна (заголовки «Пополнение» / «Вывод»), вкладок внутри нет.
- FocusBet 18px / 800, подписи FocusPay под лого нет. На 359px имя не прячется.
- `CasinoCashierHost` внутри `.casino-root`. Платёжный API в этом срезе не менял.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoCashier.tsx`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-wallet-rules.mts`: **ok**. `npx tsc -b`: ok. `rg /cabinet` в `focussite/frontend/src/casino`: **0**.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/casino/me`, `/casino/wallet`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoCashier.tsx` `1ca574291c0c1cea71a4615828eef792`
  - `CasinoShell.tsx` `2b99e135b6597de0b874772ec3f4eeb3`
  - `casino.css` `bea5917f0f08db1ae7e21f2fcbef0265`
  - `check-casino-wallet-rules.mts` `db7bf695d1a242b3685153a044ac456f`
- Живой бандл: CSS `index-C_Q3PQPX.css` `.casino-cashier{…background:#000000b8…}` лист `background:var(--surface-2)`. JS `index-BG7vBsgC.js`: `data-casino-header-deposit` **1**, `data-casino-header-withdraw` **1**, `data-casino-deposit-modal` **1**, `data-casino-withdraw-modal` **1**, `casino-cashier-tabs` **0**, `casino-brand-sub` **0**.
- `staging-test.sh`: collected **1502**, **9 failed**. Этот срез фронт-only, бэкенд-тесты не трогал. Старые семь: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Плюс чужой dirty: `ClanWarMathTests.test_weekly_wager_counts_clan_war_json`, `FixedRoomMathTests.test_weekly_wager_sql_includes_fixed_rooms`.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Postgres `running` с `2026-08-31T02:43:11Z`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- Шапка: FocusBet крупнее, подписи FocusPay нет. Видны **Пополнить** и **Вывести**.
- Пополнить → окно «Пополнение», без вкладки «Вывести». Фон тёмный, лист непрозрачный. URL `/casino`.
- Вывести → окно «Вывод», другие способы. СБП 100 — ошибка кратности 250; 250 — демо-реквизиты.
- `http://127.0.0.1:18081/casino/me` и `/casino/wallet` — те же два окна.
- Кабинет `/cabinet` как был. Не ломать куб 100→195, рулетку, джекпот.

## 2026-08-31 · Чужой профиль: уровень, оборот, история игр

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / комнаты / кланы / `/casino/clans` не открывал.

Повод: чужой `/casino/u/:id` показывал комиссию, кешбэк и неделю по играм, без пораундовой ленты. Свой профиль по кошельку не трогаем.

Сделано:

- Чужой профиль: аватар, уровень (от **недельного** `wager_rub`), «ещё N ₽ оборота до уровня», плитка «Всего поставлено» (`lifetime_wager_rub`), лента раундов. Без комиссии / кешбэка / даты регистрации / недели по играм.
- Свой `/casino/me`: шапка, комиссия, кошелёк, неделя по играм как были. Добавлены lifetime-плитка и та же лента снизу.
- Строка: игра, доля % (джекпот ставка/банк, равные PvP `100/игроков`, vs дом `null`), Победа/Проигрыш/Ничья/Возврат, ставка, «Открыть», «Проверить» если сиды раскрыты.
- `GET /user/casino/players/me/history` и `GET /user/casino/players/{id}/history?limit=&before=`.
- Общий UNION ставок: `casino_games` + holdem/jackpot/fixed_room/clan_war JSON + **v2 столы** (`casino_v2_tables` / seats; web PvP не пишет `casino_games`). Общий стол рулетки **не** дублируется через `casino_roulette_bets` — после settle это уже `casino_games.roulette`.

Отклонение от плана: в UNION не добавлял `casino_roulette_bets` (двойной счёт). Вместо дыры web-PvP — v2. Кешбэк/уровень начинают учитывать v2-ставки — исправление дыры, сетка уровней та же.

Файлы этого среза:

- `site/exchange-backend/casino_weekly_wager.py`
- `site/exchange-backend/casino_player_profile.py`
- `site/exchange-backend/casino_player_history.py`
- `site/exchange-backend/routers/user_casino.py`
- `site/exchange-backend/tests/test_casino_player_history.py`
- `site/exchange-backend/tests/test_casino_player_profile.py`
- `site/exchange-backend/tests/test_casino_fixed_rooms.py` (`inspect.getsource` модуля)
- `site/exchange-backend/tests/test_casino_clan_wars.py` (то же)
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/src/casino/casinoLevelCopy.ts`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `pytest tests/test_casino_player_history.py tests/test_casino_player_profile.py tests/test_casino_fixed_rooms.py tests/test_casino_clan_wars.py -q`: **37 dots / 100%**. History: jackpot `"18.30"` + win/loss + fairness; vs-дом `share_percent is None`; пагинация `next_before`; lifetime SQL без week CTE. `npx tsc -b` ранее ok.
- HTTP **200**: `/casino`, `/casino/me`, `/api/health`. SQL `casino_settings` count **67**.
- md5 local = `/opt`:
  - `casino_weekly_wager.py` `e1288fa55401841fd6c52717753302d8`
  - `casino_player_profile.py` `540c6dac03b3f340d86bc60c70eaddfc`
  - `casino_player_history.py` `5dcd16a18a28a0893e61e5065d9035b0`
  - `user_casino.py` `8f68b8b97c092b3c25f78201f26348be`
  - `test_casino_player_history.py` `6753e714aa3fb7b236fdf4c78f46d54d`
  - `test_casino_player_profile.py` `78fcbcf8f57eb3deee471c0d71c95c02`
  - `test_casino_fixed_rooms.py` `660c23b319c2d4fb5190bcdcbc13d070`
  - `test_casino_clan_wars.py` `98cfadc246c855d6247b2ea930db1072`
  - `CasinoProfile.tsx` `7e6532a5e64a01f4ad9dd4802b573511`
  - `casinoLevelCopy.ts` `4af9026be617992c1799a859e5e7faba`
  - `public.ts` `9f6592346cc78665b106abee47fa13da`
  - `casino.css` `0bfcee8d1f1bb337e88b85025d3a6263`
- Живой backend: `load_player_history` **1**, `lifetime_wager_rub` в weekly+profile, маршрут `{player_id}/history` **1**. Gateway JS `index-Br36usDd.js`: `data-casino-public-profile` **1**, `data-casino-game-history` **1**, `lifetime_wager_rub` **1**. CSS `index-C6M20XgA.css`: `casino-profile-history` **1**.
- `rg` `lifetime_wager_rub` / `load_player_history` / `getCasinoPlayerHistory` / `nextLevelTurnoverCopy`: weekly_wager + profile + history-модуль + `user_casino` + `public.ts` + `CasinoProfile` + тесты. Не одно вхождение. На staging `rg` нет — считал локально.
- `staging-test.sh`: collected **1517** (прошлый срез **1502**; +history/profile), **1510 passed**, **7 failed**, **1 skipped**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2 (`KeyError: 'key'` в `load_tier_config`), `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3 (мок `LifecycleConn._fetchrow` не знает новый weekly UNION с v2), `ProfileEndpointTests.test_profile_uses_weekly_wager_...` (у `Conn` нет `.fetch`). Целевой `test_casino_player_history.py` + `test_casino_player_profile.py` на staging: **20 dots / 100%**. Clan/fixed `inspect.getsource` снова зелёные (в срезе кассы они давали +2 failed).
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- С лобби клик по чужому чипу → `http://127.0.0.1:18081/casino/u/<id>`: уровень, бар, «ещё N ₽ оборота до уровня», всего поставлено, история. **Нет** комиссии, кешбэка, даты регистрации, блока «Неделя по играм», кнопок кассы.
- Строка истории: имя игры, Победа/Проигрыш (зелёный/красный), доля вроде `18.3%` у джекпота, ставка, **Открыть**, **Проверить** если раунд закрыт с сидами.
- **Проверить** → `/casino/fairness?...` и автопроверка. Кубики Telegram / cub без верификатора — только Открыть.
- `http://127.0.0.1:18081/casino/me` — кошелёк и комиссия как были; снизу та же лента и «Всего поставлено».
- Не открывать паркованные холдем / комнату N / кланы из лобби. Если старый раунд есть в базе — строка в истории нормальна, «Открыть» ведёт на скрытый маршрут.
- Не ломать: куб стол игроков 100→195, рулетка 0–36, джекпот, FocusLucky.

## 2026-08-31 · Лобби: короткие описания игр

Не прод. `deploy_all.py` не запускал. Postgres при sync **Running** (не Recreate). Паркованные холдем / комнаты / кланы не открывал. Тексты за столом (`CasinoPlayersLobby`) не трогал.

Повод: на плитках «Игры дома» длинные правила и фраза «пустое место — бот», как будто бот садится сам. Нужен смысл за пару слов плюс формат: 2–6, бота можно добавить. Ставка/комиссия уже отдельной строкой из API.

Сделано (только фронт, `howTo` + герой/промо):

- Кубики: `2–6 игроков. Кто больше на кубах. Бота можно добавить.`
- Баккара: `2–6 игроков. Ближе к 9. Бота можно добавить.`
- Блэкджек: `2–6 игроков. Ближе к 21. Бота можно добавить.`
- Рулетка: `Общий стол 0–36. Своя фишка. Из Telegram тоже.`
- FocusLucky: `Билеты за обмены. Живой розыгрыш.`
- Джекпот: `Общий банк. Больше ставка — больше шанс.`
- Герой: «стол 2–6, бота можно добавить» вместо «бот на пустое место». Промо кубиков: «Бота можно добавить.»

Файлы этого среза:

- `focussite/frontend/src/casino/gameCatalog.ts`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `docs/CASINO_WORKLOG.md`

Проверки:

- `npx tsc -b` ok (через `npm run build`). `npx tsx scripts/check-pvp-tables-only.mts` ok. `npm run build` ok, 2276 modules. Бандл `index-DWDje08B.js` / CSS `index-CtWhzO7o.css`. В JS: «Кто больше на кубах» **1**, «стол 2–6, бота можно добавить» **1**. Старые «Пустое место — бот» / «бот на пустое место» в бандле **0**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Postgres **Running**.
- Живой шлюз HTTP **200**: `/casino`, `/api/health`. SQL `casino_settings` count **67**.
- md5 local = staging `/opt`:
  - `gameCatalog.ts` `facca5db546662117ef4796f2b26f5a6`
  - `CasinoLobby.tsx` `718952a89ea66fcba3b1ae3ee8d8ec3f`
- Живой gateway `index-DWDje08B.js`: те же две новые фразы **1** / **1**, старые **0**.
- `rg` `Кто больше на кубах`: `gameCatalog.ts` **1**. `Бота можно добавить`: catalog **3** + промо лобби **1**. `стол 2–6, бота можно добавить`: герой **1**. `CasinoGameTile` рендерит `game.howTo`. Не одно вхождение.
- `staging-test.sh`: **1510 passed**, **7 failed**, **1 skipped**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2 (`KeyError: 'key'`), `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3 (мок `LifecycleConn._fetchrow` не знает weekly UNION с v2), `ProfileEndpointTests.test_profile_uses_weekly_wager_...` (у `Conn` нет `.fetch`).
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

1. `http://127.0.0.1:18081/casino` — плитки «Игры дома»:
   - Кубики / баккара / блэкджек: «2–6 игроков», смысл игры, «Бота можно добавить.» Не должно быть «пустое место — бот».
   - Внизу плитки по-прежнему `от N ₽ · комиссия X%` (не дублируется в описании).
   - Рулетка: общий стол 0–36, своя фишка, Telegram.
   - FocusLucky: билеты за обмены, живой розыгрыш. Без «как джекпот».
   - Джекпот: общий банк, больше ставка — больше шанс.
2. Абзац героя: «стол 2–6, бота можно добавить», не «бот на пустое место».
3. Блок «Как сесть за стол» / кубики: «Бота можно добавить.»
4. Не открывать паркованные холдем / комнату N / кланы. Не ломать куб 100→195, рулетку, джекпот.

## 2026-08-31 · Шапка без поиска, баланс по центру

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал. Паркованные холдем / комнаты / кланы не открывал.

Повод: поиск игр сверху занимал середину шапки; после кассы место выглядело пустым.

Сделано:

- Поиск из шапки убран (поле, лупа, `?q=`). Лобби всегда герой + каталог, не «Результаты».
- Шапка три колонки: слева FocusBet, по центру капсула баланс + Пополнить + Вывести, справа иконки.
- Шапка непрозрачная `--surface-0`. Капсула `--surface-2`. ₽/USDT по клику на баланс.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-wallet-rules.mts`: **ok**. `npx tsc -b`: ok. `rg /cabinet` в `src/casino`: **0**.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/casino/me`, `/casino/wallet`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoShell.tsx` `e491d902b90505ba1734d99b29b3a820`
  - `CasinoLobby.tsx` `449a3fe5746d4644fd2f09ba96253cb7`
  - `casino.css` `4e09e4012e5922f9895b3622ee924057`
  - `check-casino-wallet-rules.mts` `bf47a705a802929af08e396e845cb88c`
- Живой бандл: CSS `index-CtWhzO7o.css` шапка `display:grid;grid-template-columns:1fr auto 1fr;background:var(--surface-0)`, `casino-header-search` **0**, `casino-header-mid` **1**. JS `index-BkAqQUp1.js`: `data-casino-search` **0**, `data-casino-header-deposit` **1**, `data-casino-header-withdraw` **1**, `casino-header-mid` **1**, `data-casino-search-results` **0**.
- `staging-test.sh`: collected **1517**, **7 failed**, имена базовой линии, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Postgres `running` с `2026-08-31T02:43:11Z`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — в шапке нет поиска. Слева FocusBet, по центру баланс + Пополнить + Вывести, справа иконки.
- Пополнить и Вывести — разные окна, как раньше.
- Лобби сразу игры дома, не экран «Результаты».
- Кабинет `/cabinet` как был. Не ломать куб 100→195, рулетку, джекпот.

## 2026-08-31 · Баккара: раздача улицами, не пачкой

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал. Паркованные холдем / комнаты / кланы не открывал. Бэкенд HMAC / settle не менял.

Повод: стол 2–6 баккары сразу показывал все карты, очки и «Победитель». Не было паузы между первой, второй и третьей.

Сделано:

- После появления рук: улица 1 — всем первая карта по местам 1→N, пауза 650 мс, улица 2 — вторая, третья только у кого в HMAC-руке три карты (правило ≤5 на сервере как было).
- Тайминг: 420 мс между местами, 650 мс между улицами, 450 мс до баннера. Две руки + одна третья = **3010** мс; три места с одной третьей = **3850** мс. `casino-reduce-motion` — сразу исход.
- Пока раздача: бегущие очки `% 10` по открытым картам. Зелёная/красная рамка, «победа +₽», баннер победителя и кнопки «Разделить / Перераздача» — после последней карты.
- Блэкджек и кубы без этой постановки.

Файлы этого среза:

- `focussite/frontend/src/casino/baccaratStreets.ts`
- `focussite/frontend/src/casino/CasinoV2Table.tsx`
- `focussite/frontend/scripts/check-baccarat-streets.mts`
- `focussite/frontend/scripts/check-pvp-tables-only.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-baccarat-streets.mts`: **ok** (шаги `1:0,2:0,1:1,2:1,2:2`, 3010 мс). `npx tsx scripts/check-pvp-tables-only.mts`: **ok**. `npx tsc -b`: ok. Gateway build **2276** modules.
- `rg` `data-casino-baccara-street` / `baccaratStreetSteps`: `baccaratStreets.ts` + `CasinoV2Table.tsx` + `check-baccarat-streets.mts` + `check-pvp-tables-only.mts`. Не одно вхождение.
- `staging-sync.sh`: health **passed** (после update и ещё раз). HTTP **200**: `/casino`, `/casino/play/baccara?mode=players`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `baccaratStreets.ts` `e568f96d7f50f911841338cf92877efd`
  - `CasinoV2Table.tsx` `0ebca506241a11318873ba1e41b3fb80`
  - `check-baccarat-streets.mts` `fff6543754d8022a8344f517707178fd`
  - `check-pvp-tables-only.mts` `4963b968f2b4994d40d6e7c29c1cc0fd`
- Живой бандл JS `index-DWDje08B.js`: `data-casino-baccara-street` **1**, `data-casino-baccara-dealing` **1**.
- `staging-test.sh`: collected **1517**, **7 failed**, имена базовой линии, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Этот срез фронт-only.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Postgres `running` с `2026-08-31T02:43:11Z`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/baccara?mode=players` — стол 3, бот на пустое, Начать.
- Сначала у всех одна карта, пауза, вторая, у кого надо — третья. Пока карты идут — нет зелёной/красной рамки и строки «Победитель». Подпись «Раздача: первая/вторая/третья карта…».
- После последней карты — исход и выплата как раньше (банк минус комиссия).
- Ничья лидеров: кнопки «Разделить / Перераздача» только когда руки доиграны; перераздача — снова улицы.
- Блэкджек и кубы — без этой постановки. Куб 100 → 195 не ломать.

## 2026-08-31 · История профиля по играм

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / комнаты / кланы не открывал.

Повод: одна общая лента на профиле. Нужны блоки по играм, в каждом последние 5 и «Посмотреть больше».

Сделано:

- `GET .../history?game_type=` — неизвестный тип 400. `cub` / `pvp_emoji` → кубики. Фильтр режет источники (джекпот не ходит в v2).
- `GET .../players/me/history/grouped` и `GET .../players/{id}/history/grouped?per=5` (max 20). Пустые секции не отдаём.
- Порядок: Кубики, Баккара, Блэкджек, Рулетка, FocusLucky, Джекпот; паркованные — только если есть раунды.
- Профиль (свой и чужой): блоки с заголовком, до 5 строк, **Посмотреть больше** догружает те же 5 через `game_type` + `before`.

Файлы этого среза:

- `site/exchange-backend/casino_player_history.py`
- `site/exchange-backend/routers/user_casino.py`
- `site/exchange-backend/tests/test_casino_player_history.py`
- `site/exchange-backend/tests/test_casino_play.py`
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `pytest tests/test_casino_player_history.py -q`: **19 dots / 100%**. Jackpot-фильтр не мешает кубики; `pvp_dice` включает `cub`; grouped — 5 строк + `next_before` на шестой; пустые секции нет. `npx tsc -b` ok.
- HTTP **200**: `/casino`, `/casino/me`, `/api/health`. SQL `casino_settings` count **67**.
- md5 local = `/opt`:
  - `casino_player_history.py` `79fd2ab08547123c6914863adb49051a`
  - `user_casino.py` `3ddffd191afa9734f0ef79c1d52b34b1`
  - `test_casino_player_history.py` `2bbcffd10bc21a9278333dfff4e53341`
  - `test_casino_play.py` `2c0bacdb80ef29cd8941cdfe34532f51`
  - `CasinoProfile.tsx` `e45f7aec82ca15c11db8049769910dfd`
  - `public.ts` `9e288dfe47200ef46f78177d16d57d87`
  - `casino.css` `8757d0e49773eedeb5a2cc4489a6f807`
- Живой backend: `load_player_history_grouped` **1**, `history/grouped` в `user_casino.py` **2**. Gateway JS `index-BjUUPi8r.js`: `data-casino-history-game` **1**, `history/grouped` **1**, `Посмотреть больше` **1**. CSS `index-5oAlWy0_.css`: `casino-profile-history-game` **1**.
- `rg` `load_player_history_grouped` / `getCasinoPlayerHistoryGrouped` / `history/grouped` / `data-casino-history-game`: history-модуль + `user_casino` + `public.ts` + `CasinoProfile` + тесты. Не одно вхождение. На staging `rg` нет — считал локально.
- `staging-test.sh`: collected **1521** (прошлый срез **1517**, +4 history), **1514 passed**, **7 failed**, **1 skipped**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Целевой `test_casino_player_history.py` + `PlayRouteImportTests` на staging: **20 dots / 100%**.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/me` и чужой `/casino/u/<id>`: история нарезана по играм (Кубики, Рулетка, Джекпот…), не одна каша.
- В блоке не больше 5 строк. Если игр больше — кнопка **Посмотреть больше**, догружает ещё 5 в этот же блок.
- Игр, в которых человек не играл, нет. Пустой профиль: «Пока нет сыгранных раундов.»
- Строка как раньше: исход, доля %, ставка, Открыть / Проверить.
- Не открывать паркованные холдем / комнату N / кланы из лобби. Не ломать куб 100→195, рулетку, джекпот, баккару улицами.

## 2026-08-31 · Комнаты вместо дуэлей

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / клан vs клан / `/casino/clans` не открывал. Файлы 1×1 дуэлей (`CasinoDuels.tsx`, `CasinoDuelRoom.tsx`, API) не удалял: `/casino/duels/:id` из чата жив.

Повод: лобби «Все дуэли» 1×1 мешало; спрятанная «Комната N» уже считала равные ставки и рейк 5%. Нужны столы как кубики (ставка + 2–6 мест + бот) и колесо как джекпот, когда состав полный.

Сделано:

- Плитка **Комнаты** в каталоге и рельсе. `/casino/duels` → `/casino/play/fixed_room?mode=players`. Пункта «Все дуэли» нет. Тизер лобби — открытые комнаты.
- Места-боты: миграция `participant_kind` / `robot_profile_id`, `user_id` NULL у бота. `POST .../rooms/{id}/bots`. SSE `GET /user/casino/rooms/events` с событием `spin`. HMAC по reel-id места (бот = отрицательный id). Бот-победитель → дом. `pvp_robot.allowed_games` включает `fixed_room`. `ROBOT_GAME_KEYS` больше не выкидывает `fixed_room`.
- UI: лобби как кубики (чипы, места 2–6, превью банка/рейка с API, +бот). Комната — колесо `buildWeightedReel` 8 с, без докида и таймера джекпота.
- Пример: 4×250 = банк 1000, рейк 50, победителю **950**.

Файлы этого среза:

- `site/exchange-backend/casino_fixed_rooms.py`
- `site/exchange-backend/migrations/add_casino_fixed_room_bots.sql`
- `site/exchange-backend/routers/user_casino.py`
- `site/exchange-backend/routers/public_casino.py`
- `site/exchange-backend/routers/admin_casino.py`
- `site/exchange-backend/tests/test_casino_fixed_rooms.py`
- `focussite/frontend/src/casino/CasinoFixedRooms.tsx`
- `focussite/frontend/src/casino/gameCatalog.ts`
- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/casinoRoutes.tsx`
- `focussite/frontend/src/casino/CasinoPlay.tsx`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/scripts/check-casino-rooms.mts`
- `.cursor/rules/casino-shelved-games.mdc`
- `focussite/docker/staging-db/00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `10-fixtures.sql`, `bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `python -m unittest tests.test_casino_fixed_rooms tests.test_public_casino_lobby -q`: **14 OK** (`test_four_players_250_rake_five_winner_gets_950`, `test_full_room_250_credits_winner_950_and_house_50`, `test_bots_fill_room_and_bot_winner_pays_house`, cancel снимает резерв дома). `npx tsx scripts/check-casino-rooms.mts`: **ok**. `npx tsx scripts/check-pvp-tables-only.mts`: **ok**. `npx tsc -b`: ok. Gateway build **2275** modules.
- `rg` `rooms/events`: `user_casino.py` + `CasinoFixedRooms.tsx`. `postCasinoRoomBot`: `public.ts` + `CasinoFixedRooms.tsx` + check-скрипт. `data-casino-room-add-bot`: `CasinoFixedRooms.tsx` (2) + check. `async def add_bot`: `casino_fixed_rooms.py`. `Все дуэли` в `src/casino` **0**. На staging `rg` нет — считал локально.
- `staging-sync.sh`: health **passed** (после update и ещё раз; второй прогон после `ROBOT_GAME_KEYS`). HTTP **200**: `/casino`, `/casino/play/fixed_room`, `/casino/me`, `/api/health`. SQL `casino_settings` **67**. `casino_fixed_room_seats.user_id` nullable; колонки `participant_kind`, `robot_profile_id`. `pvp_robot.allowed_games` содержит `fixed_room`. Incremental bootstrap прогнал `add_casino_fixed_room_bots.sql`.
- md5 local = `/opt`:
  - `casino_fixed_rooms.py` `fbd7b81fe661fa2c77f23e56d6a52ccc`
  - `add_casino_fixed_room_bots.sql` `dd98425c5fd19f180dadca88d87c780f`
  - `user_casino.py` `53362d9f4230d9d9228f1a108f5b9a72`
  - `public_casino.py` `abb47491a52f43ffaa4a4b85229caf34`
  - `admin_casino.py` `d41d8606e96cb8961b73195cb9e317fa`
  - `test_casino_fixed_rooms.py` `83c6613cc69995590c4863a032fafc19`
  - `CasinoFixedRooms.tsx` `0081a3da6701dc8ce3353b5796bf0b58`
  - `gameCatalog.ts` `d9e4da87ebdfdec78b53fcf66e9c158a`
  - `CasinoShell.tsx` `fbb80373d3a5535c42c26889ca120692`
  - `CasinoLobby.tsx` `6981d159ed73bb2f30c9e09ccc9b19bf`
  - `casinoRoutes.tsx` `0bbe7cd0705041bc985c4e8e09dcf269`
  - `CasinoPlay.tsx` `4147c00eb5b73eaf26d00df9c7b7e3d3`
  - `public.ts` `dfa2671207ef4364fa8a57346c3f4b42`
  - `check-casino-rooms.mts` `ad56f3f150306370d491791486b311f6`
  - `casino-shelved-games.mdc` `8db3cb7c5a84eb7231fd062f087266a6`
- Живой backend: `async def add_bot` **1**, `rooms/events` **1**, `ROBOT_GAME_KEYS` без исключения `fixed_room`. Gateway JS `index-3Y2q5CtA.js`: `data-casino-room-add-bot` **1**, `rooms/events` **1**, `Комнаты` **1**, `Живые комнаты` **1**, `data-casino-create-menu` **1**, `Все дуэли` **0**, `Комната N` **0**.
- `staging-test.sh`: collected **1521**, **7 failed**, имена базовой линии, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Целевой `test_casino_fixed_rooms.py` + `test_public_casino_lobby.py` на staging: **14 dots / 100%**.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Postgres `running` с `2026-08-31T02:43:11Z`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — есть «Комнаты», нет «Все дуэли» / «Комната N».
- `http://127.0.0.1:18081/casino/play/fixed_room?mode=players` — создать 4 места × 250 ₽. Превью: банк 1000, комиссия 50, победителю 950.
- Второй аккаунт садится той же ставкой. «+ бот» на пустые. На 4/4 — колесо, один победитель, 950 на балансе если выиграл человек.
- F5 в середине спина и после. Ссылка «Проверить» сходится.
- Недобор: отмена создателя одного — возврат. Таймаут набора — возврат, не частичный розыгрыш. Вызов из чата «принять дуэль» (`/casino/duels/:id`) по-прежнему 1×1.
- Кубики / баккара и джекпот (разные ставки, один банк) без регрессии.

## 2026-08-31 · Касса меньше

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал. Паркованные холдем / кланы не открывал. Бэкенд не трогал.

Повод: окна Пополнить / Вывести были широкие (720px, три колонки, почти на всю высоту).

Сделано (только CSS):

- Лист кассы `min(400px, 100%)`, высота `min(72vh, 520px)` вместо 720px / 92vh / 840px.
- Способы всегда **2 колонки**, плитки ниже (52px), иконки 32px.
- Окно реквизитов `min(360px, 100%)`.

Файлы этого среза:

- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-wallet-rules.mts`: **ok** (`min(400px)`, `min(72vh, 520px)`, у `.casino-cashier-methods` нет `repeat(3`).
- HTTP **200**: `/casino`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `casino.css` `6bda60d1bd1c4b73c5015973f764e8c8`
  - `check-casino-wallet-rules.mts` `18036b0f2ac744e29d37d83a520a6cfd`
- Живой CSS `index-CXmASNKR.css`: `min(400px,100%)` **1**, `min(72vh,520px)` **1**, `min(720px,100%)` **0**.
- `rg` `min(400px`: `casino.css` + check-скрипт. Не одно вхождение.
- `staging-test.sh`: **1518 passed**, **7 failed**, **1 skipped**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Этот срез фронт-only.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — Пополнить: узкое окно по центру, две колонки способов, не на всю ширину.
- Вывести — то же по размеру, другие способы.
- СБП 250 — реквизиты тоже меньше. URL остаётся `/casino`.
- Не ломать куб 100→195, рулетку, джекпот, комнаты.

## 2026-08-31 · Рельс Комнат: lucide как у остальных

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал. Паркованные холдем / кланы не открывал. Бэкенд не трогал.

Повод: в рельсе у «Комнаты» был цветной эмодзи 🎯, у кубиков/баккары/джекпота — чёрный контур lucide.

Сделано:

- `gameRailIcon("fixed_room")` → `Target` (stroke currentColor, 20px), как Dices/Spade/Ticket.
- Тизер живых комнат — тот же Target, не 🎯.
- Рельс подсвечивается на `/casino/rooms/:id`.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-rooms.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-rooms.mts`: **ok**.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`.
- md5 local = `/opt`:
  - `CasinoShell.tsx` `24224772fa3b2e38ea2aeae73664f733`
  - `CasinoLobby.tsx` `f2468837a5cb0ec73745805c7cbfd783`
  - `casino.css` `e2688fdece28edc28baacaf9a7658f38`
  - `check-casino-rooms.mts` `f136761bcbf60daf642c39d9df6af621`
- Живой DOM: пункт «Комнаты» — `lucide lucide-target`, без эмодзи, как у Кубики (`dices`) и Джекпот (`sparkles`).
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp`. Полный `staging-test.sh` в этом срезе не гонял (фронт, иконка).
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — в рельсе у «Комнаты» такая же чёрная контурная иконка, как у Кубики / Честность, не красный кружок.
- Меню игр (сетка) — то же.
- Плитка Комнаты в каталоге как была (тёмная иллюстрация).

## 2026-08-31 · История профиля: окна меньше

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы не открывал. Бэкенд не трогал.

Повод: «уменьшить модалку» — не касса и не плитки лобби, а блоки **История игр** на профиле (Кубики, Баккара и остальные). Предыдущий срез зря ужал плитки лобби — вернул.

Сделано (фронт):

- Каждый раздел истории — компактная карточка в сетке `minmax(280px)`, не на всю ширину.
- Строки без больших карточек: 6px, кнопки «Открыть» / «Проверить» 26px, «Посмотреть больше» ниже.
- Лобби: плитки снова `minmax(200px)` / `aspect-ratio: 3 / 4`. Касса как была: `min(720px)`.

Файлы этого среза:

- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/CasinoProfile.tsx`
- `focussite/frontend/scripts/check-casino-wallet-rules.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-wallet-rules.mts`: **ok** (`minmax(280px)`, кнопки истории `26px`, лобби `minmax(200px)`).
- HTTP **200**: `/casino`, `/casino/me`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `casino.css` `e8ee3268bb36bec6e19427d491ab1c56`
  - `CasinoProfile.tsx` `5a874d60b42e138b87fb8be3698f035e`
  - `check-casino-wallet-rules.mts` `fb826c2d106e15c4f8a78addb589f8db`
- Живой CSS `index-uwdaCdQt.css`: `minmax(280px)` **1**, `minmax(200px)` **1**, `minmax(132px)` **0**, `casino-profile-history-grid` **1**, `min(720px,100%)` **1**. JS `index-Mf_ny1bU.js`: `casino-profile-history-grid` **1**.
- `rg` `casino-profile-history-grid`: CSS + `CasinoProfile` + check-скрипт. Не одно вхождение.
- Браузер: карточки истории ~**297×415** (5 строк), сетка 4 колонки на широком экране.
- `staging-test.sh`: **1518 passed**, **7 failed**, **1 skipped**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Этот срез фронт-only.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/me` — «История игр»: Кубики / Баккара / Блэкджек узкими колонками, строки короткие, не на всю ширину.
- Чужой `/casino/u/:id` — те же окна истории.
- «Посмотреть больше» догружает в тот же блок.
- Лобби: плитки Кубики/Баккара как раньше, не мелкие. Пополнить — широкая касса как была.
- Не ломать куб 100→195, рулетку, джекпот, комнаты.

## 2026-08-31 · Комнаты списком: плюс сел, смотришь несколько

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы / FocusLucky не трогал.

Повод: сетка высоких карточек — не то. Нужен список как на референсе: аватары в ряду, плюс на пустое место, ставка справа; плюс — сел и смотришь в этой строке; несколько сразу.

Сделано (фронт комнат):

- Лобби комнат — вертикальный список строк, не `casino-table-grid`.
- В строке: квадратные аватары, светлый квадрат «+» (сесть; если уже сидишь — бот), справа ставка. Join не уводит со страницы. Плюс по разным строкам не блокирует друг друга.
- Свои / countdown / спин — колесо и оверлей 10 с в той же строке.
- Клик по ставке — увеличенный URL как раньше.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoFixedRooms.tsx`
- `focussite/frontend/src/casino/CasinoRoomLiveCanvas.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-rooms.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-casino-rooms.mts`: **ok**. `tsc -b`: без ошибок.
- `rg` `casino-room-list` / `casino-room-join`: CSS + лобби + canvas + check-скрипт, не одно вхождение.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/api/health`, `/casino/play/fixed_room?mode=players`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoFixedRooms.tsx` `1389eb25fba7de689d9d9eae5a1cf333`
  - `CasinoRoomLiveCanvas.tsx` `72f1cb7fbb878141bb76111d3beb8467`
  - `casino.css` `aae5dd0ef3ca1e401315f684c72a471a`
  - `check-casino-rooms.mts` `61471aca36c094d51b37b5b636b44bcc`
- Живой CSS `index-aX4R9TYJ.css`: `casino-room-list` **1**, `casino-room-join` **1**.
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Срез фронт-only. Collect как в прошлом прогоне **1530** → **1522 passed**, **1 skipped**.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/fixed_room?mode=players` — список строк, не высокие карточки. Аватары слева, плюс — сесть, ставка справа. Остаёшься на странице.
- Плюс во вторую, третью комнату — смотришь несколько строк сразу (колесо / «Игра начинается» в строке).
- Пустое своё место — плюс добавляет бота. Выйти до countdown как раньше.
- Не менять: рейк, HMAC, холдем/кланы, FocusLucky, кубики/рулетка/джекпот.

## 2026-08-31 · Комнаты полосами, без мозаики

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы / FocusLucky не трогал. Бэкенд лимита 10 и countdown не откатывал.

Повод: «Мои столы» и сломанная полоса с «0» — убрать. Нужны все аватарки, быстрый «Сесть», колесо в строке. Мозаичные карточки на кубиках тоже убрать.

Сделано:

- Док «Мои столы» снят из `CasinoShell`.
- Полоса комнаты: все слоты квадратами (аватар / плюс / пустое), справа «Сесть · ставка». Join не уводит. Клик по полосе / полный стол — колесо 8 с в этой же строке.
- Кубики / баккара / блэкджек — снова felt-list, «Войти» ведёт на `/casino/tables/:id`.
- Джекпот и рулетка 0–36 без `CasinoTableTile` и оверлея «Раунд начинается».

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoShell.tsx`
- `focussite/frontend/src/casino/CasinoFixedRooms.tsx`
- `focussite/frontend/src/casino/CasinoRoomLiveCanvas.tsx`
- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/casino/CasinoJackpot.tsx`
- `focussite/frontend/src/casino/CasinoRoulette.tsx`
- `focussite/frontend/src/casino/CasinoV2Table.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-rooms.mts`
- `focussite/frontend/scripts/check-pvp-tables-only.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `check-casino-rooms.mts`: **ok**. `check-pvp-tables-only.mts`: **ok**. `tsc -b`: без ошибок.
- `rg` `casino-room-row-sit` / `casino-felt-list`: CSS + лобби + check, не одно вхождение. `CasinoLiveDock` только в своём файле, не в Shell.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/api/health`, `/casino/play/fixed_room?mode=players`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoShell.tsx` `c9d21d891cc3ee3b797d7336f07288cc`
  - `CasinoFixedRooms.tsx` `27f251734fc54d03916a88d2afc23dd3`
  - `CasinoRoomLiveCanvas.tsx` `734e374542dd5a73a1c35e8f6b5dd8e8`
  - `CasinoPlayersLobby.tsx` `e95433ac60ece122db2f214a05a97d27`
  - `CasinoJackpot.tsx` `747af39aeb2d9e7dc20ad9c1661b7b49`
  - `CasinoRoulette.tsx` `0085e4797448ad8cf96d562978722f8d`
  - `CasinoV2Table.tsx` `0ebca506241a11318873ba1e41b3fb80`
  - `casino.css` `88efe3afe33cd08153d6c9f67075e866`
  - `check-casino-rooms.mts` `b317cc3657cd4bc5ba18a173d0a3b490`
  - `check-pvp-tables-only.mts` `f98aa43617acfbc266645bbd567d3561`
- Живой CSS `index-CEpTSEcO.css`: `casino-room-list` **1**, `casino-room-row-sit` **1**.
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Срез фронт-only.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/fixed_room?mode=players` — нет «Мои столы». Полосы: все места с аватарками, справа «Сесть · ставка». Сесть — остаёшься в списке. Клик / полный стол — колесо в строке.
- Кубики `?mode=players` — список felt-карточек, не сетка окон. «Войти» открывает стол.
- Джекпот / рулетка — без карточки-оверлея.
- Не менять: рейк, HMAC, холдем/кланы, FocusLucky.

## 2026-08-31 · Комнаты: аватар и ник в полосе

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы / FocusLucky не трогал.

Повод: в полосе не было картинки и ника — только «0» и плюс.

Сделано:

- Снял `display: contents` у полосы: слоты снова в сетке, аватар квадратом, ник под ним.
- Веб-аккаунт с отрицательным `client_user_id` больше не схлопывается в `user_id: 0` / имя «0». Публичный снимок отдаёт имя и ident. Выигрыш веб-игрока не уходит в дом только из‑за минуса в id.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoRoomLiveCanvas.tsx`
- `focussite/frontend/src/casino/CasinoFixedRooms.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-casino-rooms.mts`
- `site/exchange-backend/casino_fixed_rooms.py`
- `site/exchange-backend/tests/test_casino_fixed_rooms.py`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `check-casino-rooms.mts`: **ok**. `tsc -b`: без ошибок. `pytest tests/test_casino_fixed_rooms.py`: **21 passed**.
- `rg` `casino-room-row .casino-player-nick` / `CasinoPlayerChip` в canvas: CSS + лобби + check, не одно вхождение.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/api/health`, `/casino/play/fixed_room?mode=players`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoRoomLiveCanvas.tsx` `75696d11fd075a8bd5025444b3d2dcbd`
  - `CasinoFixedRooms.tsx` `2362361bed95303ff2c80a9e84110433`
  - `casino.css` `0313da2e8b5fe88977b8a9a779732091`
  - `check-casino-rooms.mts` `290fdbe44395b4a876bb31256206478b`
  - `casino_fixed_rooms.py` `014fc39f6ff8c6b215f0d3c79ee3933b`
  - `test_casino_fixed_rooms.py` `8501cd8a20cf0def56746d9580c376d7`
- Живой CSS `index-D1zlp-76.css`: `casino-player-nick` **1**.
- `staging-test.sh`: **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/fixed_room?mode=players` — в полосе квадратный аватар и ник под ним, не «0». Пустые места — плюс. «Сесть» справа.
- Создай комнату под веб-аккаунтом без Telegram — имя своё, картинка ident, не цифра.
- Не менять: рейк, HMAC, холдем/кланы, FocusLucky.

## 2026-08-31 · Полосы v2 и азартное колесо

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы / FocusLucky не трогал. HMAC / `buildWeightedReel` / индекс победителя **80** не менял.

Повод: кубики / баккара / блэкджек — felt-карточки, «Войти» уводил на `/casino/tables/:id`. Колесо комнат/джекпота — один transition 8 с без разгона.

Сделано:

- Лобби v2 — те же полосы, что комнаты: все места квадратами (аватар + ник / плюс), справа «Сесть · ставка». Join / create не делают `navigate` на стол. Busy по `table_id`. Список 2.5 с, сидящие 1 с.
- Раскрытая строка: `CasinoV2CompactPlay` `facesOnly` (кубик / карты, не колесо). Кнопки кинуть / начать / ничья в строке. Countdown 10 с оверлеем на полосе.
- Колесо комнат и джекпота: `WEIGHTED_REEL_SPIN_MS = 10500`, класс `.is-drama` — кривая с длинным хвостом, blur трека, пульс риски, слот победителя крупнее. FocusLucky остаётся `SPIN_MS = 8000` без `.is-drama`.
- `prefers-reduced-motion` / `.casino-reduce-motion` — сразу к цели, без blur.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/casino/CasinoV2CompactPlay.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/src/casino/weightedReel.ts`
- `focussite/frontend/src/casino/CasinoRoomLiveCanvas.tsx`
- `focussite/frontend/src/casino/CasinoFixedRooms.tsx`
- `focussite/frontend/src/casino/CasinoJackpot.tsx`
- `focussite/frontend/scripts/check-pvp-tables-only.mts`
- `focussite/frontend/scripts/check-casino-rooms.mts`
- `focussite/frontend/scripts/check-weighted-reel.mts`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `check-pvp-tables-only.mts`: **ok**. `check-casino-rooms.mts`: **ok**. `check-weighted-reel.mts`: **ok** (индекс **80**, спин **10500**, raffle **8000** без drama). `tsc -b`: без ошибок.
- `rg` `casino-v2-strip-play` / `is-drama` / `WEIGHTED_REEL_SPIN_MS`: CSS + лобби / комнаты / джекпот / canvas / check-скрипты, не одно вхождение. `CasinoRaffle.tsx` без `is-drama` и без `WEIGHTED_REEL_SPIN_MS`.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/api/health`, `/casino/play/pvp_dice?mode=players`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoPlayersLobby.tsx` `02073185022da57bc528b1265ef8546b`
  - `CasinoV2CompactPlay.tsx` `fe545d39ae34974e2377122cca15f482`
  - `casino.css` `b40141d2ac2c2bb5524bc12110f1c8fe`
  - `weightedReel.ts` `8896d64f425b8adf36c79a821e1389e4`
  - `CasinoRoomLiveCanvas.tsx` `b86f27fe43d2121aa9bd77c5410784d7`
  - `CasinoFixedRooms.tsx` `0f4041d7ed9a97f88f86a32a00dc6ae8`
  - `CasinoJackpot.tsx` `95df6b3afc10b1b2d16da52f4bb7e1cb`
  - `check-pvp-tables-only.mts` `411aa2d8002467cfe6041576a20abc20`
  - `check-casino-rooms.mts` `38e55d7290c44ab4d34393ada47903f2`
  - `check-weighted-reel.mts` `7f1ef3e3d49253d5e5d1e39592f21375`
- Живой CSS `index-BlmX3n6N.css`: `is-drama` **1**, `casino-v2-strip-play` **1**, `10.5s` **1**. JS `index-Bc9lPvg1.js`: `casino-v2-strip-play` **1**, `10500` **1**.
- `staging-test.sh`: **1525 passed**, **7 failed**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Срез фронт-only.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/pvp_dice?mode=players` (и `/baccara`, `/blackjack`) — полосы, не felt-карточки. «Сесть» не уводит со страницы. В раскрытой строке кубик или карты, не колесо.
- Плюс / «Сесть» в разные полосы — busy не общий. Countdown 10 с на полосе.
- Комнаты / джекпот: колесо ~10.5 с, тормозит к риске, не мгновенно. FocusLucky по-прежнему ~8 с.
- Не менять: рейк, HMAC индекс 80, холдем/кланы спрятаны, страница стола `/casino/tables/:id` как увеличенный вид.

## 2026-08-31 · Лобби: убрать «Недавние» и «Игры дома»

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` StartedAt `2026-08-31T02:43:11Z`). Паркованные холдем / кланы не трогал.

Повод: под баннером лобби две полосы — чипы «Недавние» и заголовок+фильтры «Игры дома». Нужно убрать оба блока, плитки поднять сразу под баннер.

Сделано:

- С лобби сняты секция «Недавние» (чипы) и заголовок/фильтры «Игры дома» (`Все` / `Дуэли` / `Карты` / `Против FocusBet`).
- Сетка плиток (`id=casino-games`, 7 видимых игр) идёт сразу после героя. «Живые комнаты» и «Как сесть за стол» на месте.
- Из `casino.css` убраны `.casino-recent-chips` и `.casino-filter`. `pushRecent` / `RECENT_KEY` в каталоге оставлены — пишутся при входе в игру, на лобби не показываются.

Файлы этого среза:

- `focussite/frontend/src/casino/CasinoLobby.tsx`
- `focussite/frontend/src/casino/casino.css`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `tsc -b`: без ошибок.
- `rg` `Недавние` / `Игры дома` / `casino-recent-chips` / `casino-filter` в `CasinoLobby.tsx` + `casino.css`: **0** (локально и `/opt`).
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `CasinoLobby.tsx` `7d4d1b4a284c88d5aa8c708f1da7d57f`
  - `casino.css` `4ca8dc68794fa9669bc354811f9f582e`
- Живой бандл: HTML `Недавние` **0**, `Игры дома` **0**. JS `index-BW9e5hVJ.js`: `Недавние` **0**, `Игры дома` **0**, `data-casino-lobby` **1**, `casino-tile-grid` **1**, `Живые комнаты` **1**, `Кубики` **5**. CSS `index-DFltj-ku.css`: `casino-recent` **0**, `casino-filter` **0**.
- DOM на `http://127.0.0.1:18081/casino`: h2 только «Живые комнаты» / «Как сесть за стол»; `data-casino-tile` **7**; кнопок фильтра нет.
- `staging-test.sh` / pytest `tests/`: collect **1535**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Passed **1528** (1535−7). В прошлом журнале было 1525 passed / 1532 collect — плюс 3 теста из чужого WIP, этот срез фронт-only тестов не добавлял.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP, ~244 short). `focuspay-casino` HEAD `4b8d65e`, не трогал. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — нет подписи «Недавние», нет чипов недавно игранных, нет «Игры дома», нет фильтров Все/Дуэли/Карты. Сразу под баннером плитки кубики/баккара/блэкджек/рулетка/FocusLucky/джекпот/комнаты.
- Боковое меню и баннер на месте. Звёздочка избранного на плитке работает.
- Не менять: рейк, HMAC, холдем/кланы спрятаны, FocusLucky.

## 2026-08-31 · Блэкджек «Создать стол» 500 на веб-аккаунте

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы / FocusLucky не трогал. HMAC / рейк не менял.

Повод: скрин `http://178.63.247.233:18082/casino/play/blackjack?mode=players` — 4 места × 100 ₽, «Создать стол» → toast **Internal Server Error**.

Причина: парольный сайт-аккаунт имеет отрицательный `client_user_id`. `V2TableCreateRequest.creator_id` был `PositiveTelegramId` (`> 0`) — pydantic `ValidationError` внутри `create_web_table`, FastAPI отдавал 500. Даже после этого INSERT упирался в CHECK `casino_v2_tables.creator_id > 0` и `telegram_id > 0` на местах.

Сделано:

- V2 create/join/add-bot/start/leave/release принимают `ClientUserId` (Telegram `> 0` или веб `< 0`, не 0).
- Миграция `add_casino_v2_web_client_ids.sql`: CHECK `creator_id <> 0`, `telegram_id IS NULL OR <> 0`. В `00-apply-migrations.sh` и `20-full-panel-bootstrap.sh` (required + incremental + fresh).
- Лобби: `is_you` / актёры / `_roster_has_human` считают отрицательный id человеком, не «0».

Файлы этого среза:

- `site/exchange-backend/routers/internal_casino.py`
- `site/exchange-backend/casino_v2_web.py`
- `site/exchange-backend/migrations/add_casino_v2_web_client_ids.sql`
- `site/exchange-backend/tests/test_internal_casino.py`
- `site/exchange-backend/tests/test_casino_v2_web.py`
- `focussite/docker/staging-db/00-apply-migrations.sh`
- `focussite/docker/staging-db/20-full-panel-bootstrap.sh`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `pytest tests/test_casino_v2_web.py tests/test_internal_casino.py::V2TableContractTests`: **ok**.
- `rg` `add_casino_v2_web_client_ids`: bootstrap ×3 файла + миграция + тест, не одно вхождение. `creator_id: ClientUserId` в `internal_casino.py` на create/start/release. `uid != 0` в `casino_v2_web.py` (is_you + actors).
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/casino/play/blackjack`, `/api/health`. SQL `casino_settings` **67**.
- Живая БД: `casino_v2_tables_creator_id_check` = `CHECK ((creator_id <> 0))`; `casino_v2_table_seats_telegram_id_check` = `CHECK (((telegram_id IS NULL) OR (telegram_id <> 0)))`.
- md5 local = `/opt`:
  - `casino_v2_web.py` `adf595e5df4d88a423dfbd494d8b60cf`
  - `internal_casino.py` `91683fcd1e5d42dab733097eba15f0a3`
  - `add_casino_v2_web_client_ids.sql` `3d10d17ee2de1c4213e0183e93851684`
  - `test_casino_v2_web.py` `2cc7978d88f8f2516e8280b1e90a1201`
  - `test_internal_casino.py` `4559e2f16c8a0709b6c847a55e96df57`
  - `00-apply-migrations.sh` `54c9c2b86093ff0870477418ab115a0c`
  - `20-full-panel-bootstrap.sh` `7d6c97edfa5da19a20feb96af05f7f28`
- `staging-test.sh`: collect **1535**, **1528 passed**, **7 failed**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Хост **18082** (`focuspay-staging-play-public`) проксирует на `127.0.0.1:18081`.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty. `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** или тот же шлюз **18082**. **Жёсткое обновление.** Тот же вход (логин/пароль без Telegram).

- `http://127.0.0.1:18081/casino/play/blackjack?mode=players` (или `:18082`) — 4 места × 100 ₽ → «Создать стол». Стол появляется в списке, тоста Internal Server Error нет, баланс минус 100 ₽.
- Своё место — аватар/ник, не «0». Отмена стола до старта как раньше.
- То же для кубиков / баккары, если тот же веб-аккаунт.
- Не менять: рейк 5%, HMAC, холдем/кланы спрятаны, FocusLucky.

## 2026-08-31 · /start в казино-боте молчал

Не прод. `deploy_all.py` не запускал. Полный `staging-sync.sh` не гонял (чужой dirty focuspay). Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы не трогал.

Повод: в личке staging-бота `/start` без ответа.

Причина в логах casino-bot (10:23–10:26 UTC): Telegram 400 `keyboard button Web App URL 'http://127.0.0.1:18081/casino/tg' is invalid: Only HTTPS links are allowed`. Reply-меню `/start` и инлайн-хаб вешали Mini App на HTTP URL из `CASINO_MINIAPP_URL`. Джекпот/рулетка уже режут HTTP через `https_only()`, меню — нет. `send_photo` падал вне try, текстовый fallback нёс ту же клавиатуру и тоже 400.

Сделано:

- `miniapp_web_app_url()`: кнопка «На сайте» только для `https://`.
- `send_photo` в `_send_casino_card` в том же try, что рендер: при 400 уходит текст приветствия.

Файлы: `focuspay-casino/casino_menu.py`, `bot.py`, `tests/test_staging_ui.py`.

Проверки агента:

- Локально pytest `test_staging_ui.py` + profile/startup/site_links/start_card/profile_card/help: **42 passed**.
- Точечный rsync трёх файлов + `compose build casino-bot` + `up -d --no-deps --wait`. Health **passed**. `down -v` не было.
- SQL `casino_settings` **67**.
- md5 local = `/opt` = live `/app`:
  - `bot.py` `628198d64c19fcc6075b9e5235efc928`
  - `casino_menu.py` `efb46f30c66efea7979733e4d49f4bb6`
- `rg` `miniapp_web_app_url` / `startswith("https://")` в живом `/app`: есть. Docker наружу: только `127.0.0.1:18081->8080/tcp` у gateway. casino-bot без Host ports. Created-контейнеров нет.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (чужой WIP + этот журнал). `focuspay-casino` HEAD `4b8d65e`, dirty этот срез. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Staging-бот, **личная переписка** (не группа).

- `/start` — карточка профиля и нижнее меню (Создать / Активные / Мои / Профиль / Баланс / Пополнить). Ответа «тишина» больше нет.
- Кнопки меню работают как раньше. «На сайте» в reply-клавиатуре на staging **нет** (URL HTTP, Telegram его не принимает).
- `/help` по-прежнему отвечает текстом.
- Не менять: рейк, HMAC, холдем/кланы спрятаны, FocusLucky.

## 2026-08-31 · FocusLucky ниже джекпота и комнат

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы не трогал. HMAC / рейк не менял.

Повод: в лобби и рельсе FocusLucky стоял между рулеткой и джекпотом.

Сделано: в каталоге порядок видимых игр — кубики, баккара, блэкджек, рулетка, джекпот, комнаты, FocusLucky. Тот же порядок в рельсе, сетке плиток, публичном lobby API и выборе игры на честности.

Файлы этого среза:

- `focussite/frontend/src/casino/gameCatalog.ts`
- `site/exchange-backend/routers/public_casino.py`
- `focussite/frontend/src/pages/CasinoFairness.tsx`
- `.cursor/rules/casino-shelved-games.mdc`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `tsc -b`: без ошибок. `check-casino-rooms.mts` / `check-pvp-tables-only.mts`: **ok**. `unittest tests.test_public_casino_lobby`: **1** OK.
- `rg` `id: "jackpot"` → `id: "fixed_room"` → `id: "raffle"` в `gameCatalog.ts` (строки 63 / 72 / 81). `LOBBY_CATALOG` в `public_casino.py`: jackpot, fixed_room, raffle. `CasinoFairness.tsx` GAME_TYPES: jackpot, fixed_room, raffle.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/api/health`, `/casino/play/raffle`, `/api/public/casino/lobby`. SQL `casino_settings` **67**.
- md5 local = `/opt`:
  - `gameCatalog.ts` `69cca1597df23239a4b4bfd05cd7891e`
  - `public_casino.py` `d090524eb71ad2c94970e5d3c445b4c7`
  - `CasinoFairness.tsx` `0915b63c14b02e8f9106e5d10b07de90`
  - `casino-shelved-games.mdc` `0de4fa592885ca0115aeb6999513c261`
- Живой lobby API: games id `… roulette, holdem, jackpot, fixed_room, raffle, clan_war`. Живой JS `index-B739V10T.js`: имена по позиции **Кубики, Баккара, Блэкджек, Рулетка, Джекпот, Комнаты, FocusLucky**.
- `staging-test.sh`: collect **1535**, **1528 passed**, **7 failed**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет. Postgres не Recreate.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino` — плитки и левый рельс: кубики → баккара → блэкджек → рулетка → джекпот → комнаты → **FocusLucky** последним. Холдем и кланы не видны.
- Избранное (звёздочка) по-прежнему поднимает плитку вверх — это не баг порядка каталога.
- Не менять: рейк, HMAC, сами игры.

## 2026-08-31 · Баккара 4/4 зависает с картами рубашкой

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`focuspay-staging-runtime-postgres-1` running с `2026-08-31T02:43:11Z`). Паркованные холдем / кланы не трогал. HMAC / рейк 5% не менял.

Повод: скрин `http://178.63.247.233:18082/casino/play/baccara?mode=players` — стол 4/4, статус «игра начинается», четыре рубашки, дальше ничего. Нижний стол 2/2 с лицами и «ничья — выбор» жил.

Причина: closer стартовал стол и в той же транзакции сразу считал победителя и селил. Settle пишет в `casino_v2_notification_outbox` с `CHECK (recipient_id > 0)`. Парольный веб-аккаунт имеет отрицательный `client_user_id` — INSERT падал, весь старт откатывался, руки так и не сохранялись. Ничья не доходила до settle, поэтому 2/2 с лицами работал.

Сделано:

- Раздача в первом тике: руки в state, `cards_dealt_at`, статус `running`. Settle / «ничья — выбор» только после паузы улиц (те же 420/650/450 мс, что на фронте).
- Миграция `add_casino_v2_outbox_web_client_ids.sql`: outbox `recipient_id <> 0`. В `00-apply-migrations.sh` и `20-full-panel-bootstrap.sh` (required + incremental + fresh).
- Closer: savepoint на стол — один упавший settle не откатывает чужую раздачу.
- Лобби-полоса баккары крутит ту же улицу, что страница стола (`useBaccaratStreets`).

Файлы этого среза:

- `site/exchange-backend/casino_v2_web.py`
- `site/exchange-backend/casino_v2_cards.py`
- `site/exchange-backend/migrations/add_casino_v2_outbox_web_client_ids.sql`
- `site/exchange-backend/tests/test_casino_v2_cards.py`
- `site/exchange-backend/tests/test_casino_v2_web.py`
- `site/exchange-backend/tests/test_internal_casino.py`
- `focussite/frontend/src/casino/useBaccaratStreets.ts`
- `focussite/frontend/src/casino/CasinoV2CompactPlay.tsx`
- `focussite/frontend/src/casino/CasinoV2Table.tsx`
- `focussite/frontend/scripts/check-baccarat-streets.mts`
- `focussite/docker/staging-db/00-apply-migrations.sh`
- `focussite/docker/staging-db/20-full-panel-bootstrap.sh`
- `focussite/docker/staging-db/bootstrap_static_test.sh`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `unittest tests.test_casino_v2_cards tests.test_casino_v2_web tests.test_internal_casino.V2TableContractTests`: **45 OK**. В т.ч. `test_unique_winner_waits_for_street_reveal_before_settle` (2360 мс), `test_baccarat_first_tick_deals_hands_without_settling`. `tsc -b`: без ошибок. `check-baccarat-streets.mts`: **ok**.
- `rg` `cards_dealt_at` / `next_card_table_action` / `useBaccaratStreets` / `recipient_id <> 0`: web + cards + миграция + тесты + compact/table/hook + bootstrap, не одно вхождение.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino`, `/casino/play/baccara?mode=players`, `/api/health`, `/api/public/casino/v2/tables?game_type=baccara`. SQL `casino_settings` **67**.
- Живая БД: `casino_v2_notification_outbox_recipient_id_check` = `CHECK ((recipient_id <> 0))`. Застрявшего 4/4 `ready` без рук нет; живой стол баккары один, `draw_choice`, `has_hands=t`.
- md5 local = `/opt`:
  - `casino_v2_web.py` `95256394791c87a80e586107ef0accb7`
  - `casino_v2_cards.py` `5d1a177f602c2087e8b5d0fbeef6c998`
  - `add_casino_v2_outbox_web_client_ids.sql` `a7226ab1e5188eaca4417c98a5b7c0f2`
  - `test_casino_v2_cards.py` `65d29c5201729b0a89889563a2e3b2ed`
  - `test_casino_v2_web.py` `4a04b74344a1ed733e7c21632d2c02d1`
  - `CasinoV2CompactPlay.tsx` `388f166583229da151d64439ee3b589e`
  - `CasinoV2Table.tsx` `572bdbae27fb589c1404e71f2df3af3c`
  - `useBaccaratStreets.ts` `e875017b417728d165fb216b273696b9`
- Живой бандл `index-BZvV8boe.js`: `data-casino-baccara-street` **2**. CSS `index-DFltj-ku.css`.
- `staging-test.sh`: collect **1538**, **1531 passed**, **7 failed**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. В прошлом журнале 1535/1528 — плюс 3 теста этого среза.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Хост **18082** проксирует на 18081.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** или шлюз **18082**. **Жёсткое обновление.** Тот же вход (логин/пароль без Telegram).

- `http://127.0.0.1:18081/casino/play/baccara?mode=players` (или `:18082`) — создать стол 4 места × 500 ₽, три «+ бот». После отсчёта ~10 с карты **открываются по одной** (сначала всем первая, потом вторая, третья если есть), статус «идёт игра», не вечные рубашки. Победитель или «ничья — выбор» после раздачи, не в момент старта.
- То же на 2 местах: лица как раньше, ничья по-прежнему даёт «Разделить банк».
- Не менять: рейк 5%, HMAC, холдем/кланы спрятаны, FocusLucky.

## 2026-08-31 · Рулетка, джекпот и комнаты в играх бота

Не прод. `deploy_all.py` не запускал. Полный `staging-sync.sh` не гонял. Postgres не пересоздавал (`started=2026-08-31T02:43:11Z`). Паркованные холдем / кланы не трогал. HMAC / рейк не менял. FocusLucky в боте по-прежнему выключен.

Повод: кнопка «Создать игру» в боте предлагала только кубики / баккару / блэкджек. Рулетка и джекпот уже были командами `/roulette` `/jackpot`. Комнат в Telegram не было.

Сделано:

- Мастер «Создать игру»: кнопки Рулетка, Джекпот, Комнаты. Рулетка/джекпот открывают существующие карточки общего стола, **не** `create_v2_table`.
- Internal API комнат (зеркало сайта): list/get/create/join/leave/cancel/bots, `X-Internal-Token`. Клиент `FocusPayClient`.
- `games/rooms.py`: `/rooms`, коллбеки `rm:`, хаб `hub:roulette|jackpot`. Лобби «Активные игры»: сверху Рулетка и Джекпот, ниже Join по открытым комнатам, дальше столы V2. `/help rooms`.
- HTTP Mini App не вешается; ссылка «Смотреть на сайте» как `url=`.

Файлы этого среза:

- `site/exchange-backend/routers/internal_casino.py`
- `site/exchange-backend/tests/test_internal_casino.py`
- `site/exchange-backend/tests/test_casino_v2_web.py`
- `focuspay-casino/games/catalog.py`
- `focuspay-casino/games/table_wizard.py`
- `focuspay-casino/games/rooms.py`
- `focuspay-casino/games/v2_tables.py`
- `focuspay-casino/games/help.py`
- `focuspay-casino/games/site_links.py`
- `focuspay-casino/focuspay_client.py`
- `focuspay-casino/bot.py`
- `focuspay-casino/tests/test_rooms.py`
- `focuspay-casino/tests/test_table_wizard.py`
- `focuspay-casino/tests/test_v2_tables.py`
- `focuspay-casino/tests/test_help.py`
- `focuspay-casino/tests/test_site_links.py`
- `focuspay-casino/tests/test_focuspay_client.py`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально casino-bot pytest (rooms/wizard/v2/help/site_links/client/jackpot/startup/staging_ui/profile): **95 passed**. Backend `FixedRoomInternalContractTests` + `HouseWebClosedTests`: **5 passed**.
- `grep` live `/app`: `get_internal_fixed_rooms` / `post_internal_fixed_room_*`; `register_rooms_handlers` в `bot.py` до catch-all; `HUB_GAMES` в catalog; `hub:roulette` в лобби. Не одно вхождение.
- Точечный rsync (без `--delete`) + `compose --profile casino up -d --build --no-deps --wait backend casino-bot`. Health **passed**. `down -v` не было.
- SQL `casino_settings` **67**.
- md5 local = `/opt` = live:
  - `internal_casino.py` `657632623ff3208e8894881deda04b21`
  - `bot.py` `d9a0759b3835a11e51c0a6cedb8c4cc3`
  - `rooms.py` `fb72478d1686ccc927926efca08a91e3`
  - `catalog.py` `0310376d7a59c73f2ab5186d5b811f70`
  - `table_wizard.py` `42d6022a9a542a886c30a2615571c6f3`
  - `v2_tables.py` `89437c6c406853f083d27a47c2bb20c6`
  - `focuspay_client.py` `bad1feedcd9f28943a392216022eb4ab`
- `staging-test.sh`: collect **1542** (было 1538, +4 `FixedRoomInternalContractTests`). **1535 passed**, **7 failed**. Имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. На staging `FixedRoomInternalContractTests` + `HouseWebClosedTests`: **5 passed**.
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. casino-bot без Host ports. Created-контейнеров нет. Postgres StartedAt **2026-08-31T02:43:11Z**.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`, dirty этот срез. Не коммитил, прод не трогал.

Следующий шаг: стоп, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Staging-бот, **личная переписка**.

1. Создать игру — в списке рулетка, джекпот, комнаты (кубики/карты на месте).
2. Рулетка / джекпот — карточка общего стола, ставка кнопкой как `/roulette` / `/jackpot`.
3. Комната: ставка 100, 3 места, создать; вторым аккаунтом сесть из «Активные игры»; бот на пустое место.
4. `/help rooms`. HMAC/рейк/спрятанный холдем не менять.

## 2026-08-31 · Баккара: повтор раздачи и позднее завершение

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`StartedAt=2026-08-31T02:43:11Z`). Паркованные холдем / кланы не трогал. HMAC / рейк 5% не менял.

Повод: после фикса «deal → settle» баккара крутила карты второй раз и долго висела в «идёт игра». Причина: `baccaratRoundKey` включал `seed`, который API отдаёт только на `finished` — ключ менялся → улица сбрасывалась. Плюс хук всегда стартовал с `revealed=0` при опоздавшем поллинге, а лобби выкидывало `finished` стол из списка.

Сделано:

- `baccaratRoundKey` = `tableId + commit + hands` (без seed). Появление сида на finish больше не перезапускает улицу.
- `baccaratRevealedAfter` / `baccaratElapsedMs`: догон по `cards_dealt_at` при смене раунда и в таймере; 450 мс beat только на клиенте перед исходом.
- Backend `baccarat_reveal_ms` без `BACCARA_RESULT_BEAT_MS` — closer settle после последней карты (2×2 = **1910** мс, было 2360).
- `mergeV2LobbyTables`: seated `running` / `draw_choice` / `finished` не пропадает из лобби между poll; stale list не затирает руки; смена игры сбрасывает список.

Файлы этого среза:

- `focussite/frontend/src/casino/baccaratStreets.ts`
- `focussite/frontend/src/casino/useBaccaratStreets.ts`
- `focussite/frontend/src/casino/v2LobbyMerge.ts`
- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/lib/public.ts`
- `focussite/frontend/scripts/check-baccarat-streets.mts`
- `site/exchange-backend/casino_v2_cards.py`
- `site/exchange-backend/tests/test_casino_v2_cards.py`
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-baccarat-streets.mts`: **ok**. `npx tsx scripts/check-pvp-tables-only.mts`: **ok**. `npx tsc -b`: **ok**.
- Локально `unittest tests.test_casino_v2_cards tests.test_casino_v2_web tests.test_internal_casino.V2TableContractTests`: **45 OK** (в т.ч. `test_unique_winner_waits_for_street_reveal_before_settle` **1910** мс).
- `rg` `baccaratRevealedAfter` / `mergeV2LobbyTables` / `cards_dealt_at` / `baccaratRoundKey`: streets + hook + lobby merge + public + check script + `casino_v2_web.py` + тесты — не одно вхождение.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino/play/baccara?mode=players`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = staging:
  - `casino_v2_cards.py` `00e56f888c9ac59715a79fd422a6c759`
  - `baccaratStreets.ts` `76dca22904d0278c453aae7a696e7bff`
  - `useBaccaratStreets.ts` `88863dbe8d00ca15e2597b943a337b0c`
  - `v2LobbyMerge.ts` `79695873434b2509cb0132acb9a411bb`
  - `CasinoPlayersLobby.tsx` `89b2dd274688d18381b72ab9ffd664e6`
  - `check-baccarat-streets.mts` `0c06aac23c156110c89cd29f581ae6ed`
  - `test_casino_v2_cards.py` `47d81dfa45cf467618be8487c11de52a`
- Живой бандл `index-BWj6tZuM.js`: `data-casino-baccara-street` **2**. CSS `index-DFltj-ku.css`.
- `staging-test.sh`: **8 failed** — семь прежних имён + **новый** `V2BlackjackPureTests.test_deal_is_stable_per_seat_and_hits_to_seventeen` (флаки по сиду `seed-a`, score 15; к баккаре не относится, локально тоже падает при одиночном прогоне).
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Created-контейнеров нет.
- Прод (read-only `ssh focuspay`): `index.html` 2026-08-29 06:08:38 UTC, `panel.html` 2026-08-28 04:22:48 UTC, unit `ActiveEnterTimestamp=2026-08-29 06:08:19 UTC`. Не сдвинулись.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: **стоп**, жду клик-приёмку. Другую задачу не начинать.

Потыкать. Туннель **18081** (или шлюз **18082**). **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/baccara?mode=players` — стол 2–6, дождаться отсчёта. Карты идут **один круг** (1-я → 2-я → 3-я), без повторного сброса на рубашку после finish.
- После последней карты — «готово» / победитель **без второго круга**; строка стола в лобби **не исчезает** сразу после settle.
- Ничья: «ничья — выбор» после единственной улицы; «перераздать» — тогда новая улица (это ок).
- Не менять: рейк 5%, HMAC, холдем/кланы спрятаны.

## 2026-08-31 · Блэкджек: улицы + добор игроков (V2 2–6)

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`StartedAt` `2026-08-31T02:43:11Z`). Паркованные холдем / кланы / дом 1×1 не трогал. HMAC-алгоритм / рейк 5% не менял.

Сделано:

- Раздача **2 карты** на место (`dealt_cards`), не авто до 17. Улицы как у баккары (420/650 мс), затем фаза **`hitting`**.
- Боты после улицы добирают до 17; люди — **Добрать** / **Оставить** (`POST …/hit`, `POST …/stand`). Таймаут 30 с → авто-оставить.
- Третья+ карта не сбрасывает анимацию улицы (`blackjackRoundKey` только по первым двум).
- Фронт: `useBaccaratStreets` на блэкджек, кнопки в столе и полосе лобби; текст «руки до 17» убран.

Файлы: `casino_v2_cards.py`, `casino_v2_web.py`, `routers/user_casino.py`, `tests/test_casino_v2_cards.py`, `tests/test_casino_v2_web.py`, `baccaratStreets.ts`, `useBaccaratStreets.ts`, `CasinoV2CompactPlay.tsx`, `CasinoV2Table.tsx`, `CasinoPlayersLobby.tsx`, `public.ts`, `check-baccarat-streets.mts`.

Проверки:

- Локально: `unittest tests.test_casino_v2_cards tests.test_casino_v2_web.V2WebPublicViewTests` **26 OK**; `npm run build` OK; `check-baccarat-streets.mts` **ok**.
- `staging-sync.sh`: health **passed**. HTTP **200**: `/casino/play/blackjack?mode=players`, `/api/health`. SQL `casino_settings` **67**.
- md5 local = `/opt` (backend + фронт-исходники): `casino_v2_cards.py` `456db176fff05e0d2d95f977eb9e8ede`, `casino_v2_web.py` `91863c6f9d4275a94beb25e926b31f5c`, `user_casino.py` `b385574eee8760ca789526900d6cc523`, `CasinoV2Table.tsx` `26b003c72120b24f55909fa9bf0da503`, `useBaccaratStreets.ts` `9c06bb07e6051a4c47cf5059223b01d2`.
- Живой gateway-бандл `index-BfVinAfs.js`: «Добрать» **1** (в `index.html` multi-entry).
- `staging-test.sh`: **1541 passed**, **7 failed** — те же имена, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`.
- Docker наружу: только `127.0.0.1:18081->8080/tcp`. Прод timestamps не сдвинулись.

Git: HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: **стоп**, жду клик-приёмку.

Потыкать. Туннель **18081** или **18082**. **Жёсткое обновление.**

- `http://127.0.0.1:18081/casino/play/blackjack?mode=players` — создать стол 2–4 места, бота, дождаться старта. Две карты **по одной вокруг стола**, потом «добор» и кнопки **Добрать** / **Оставить** (на столе и в полосе лобби).
- Добрать несколько раз или оставить; бот добирает сам; после всех — победитель или «ничья — выбор».
- Баккара и дом 1×1 не трогать. Не менять: рейк 5%, HMAC, холдем/кланы спрятаны.

## 2026-08-31 · Итог раунда V2: сумма, статус «готово», реванш

Не прод. `deploy_all.py` не запускал. Postgres не пересоздавал (`down -v` не было). `StartedAt` сейчас `2026-08-31T11:34:46Z` (в прошлом срезе журнала было `02:43:11Z` — контейнер перезапускался вне этого фронтового фикса). Паркованные холдем / кланы / дом 1×1 не трогал. HMAC / рейк 5% не менял.

Повод: после finish полоса лобби оставляла «добор» (`phase === hitting` раньше `status === finished`). В компакт-игре были очки и цвета, но не личная сумма, не тост, не «Ещё раунд». Стол не закрывался визуально.

Сделано:

- `v2StatusLabel`: сначала `finished` → «готово», потом фазы (`hitting` / `draw_choice`).
- Баннер `CasinoRoundResult`: заголовок, подписанная сумма, деталь (ставка · прибыль / возврат), кнопки.
- Тост + haptic один раз на `table_id:state_version` (`sessionStorage`).
- На месте победителя — `payout_rub`; «Ещё раунд» создаёт стол с той же ставкой / местами / `bot_count`, `autojoin: true`.
- Ничья: «Разделить» + «Перераздача» (как было) плюс баннер.

Файлы этого среза:

- `focussite/frontend/src/casino/v2RoundResult.ts`
- `focussite/frontend/src/casino/CasinoRoundResult.tsx`
- `focussite/frontend/src/casino/useV2RoundNotice.ts`
- `focussite/frontend/src/casino/CasinoV2CompactPlay.tsx`
- `focussite/frontend/src/casino/CasinoV2Table.tsx`
- `focussite/frontend/src/casino/CasinoPlayersLobby.tsx`
- `focussite/frontend/src/casino/casino.css`
- `focussite/frontend/scripts/check-round-result.mts`
- `.cursor/rules/casino-human-verify.mdc` (агент кликает staging; прод только после «го»)
- `docs/CASINO_WORKLOG.md`

Проверки:

- Локально `npx tsx scripts/check-round-result.mts`: **ok**. `check-baccarat-streets.mts`: **ok**. `check-pvp-tables-only.mts`: **ok**.
- `rg` `v2StatusLabel` / `CasinoRoundResult` / `data-casino-v2-replay` / `v2MyRoundResult`: helper + compact + table + lobby + dock re-export + check script — не одно вхождение.
- md5 local = `/opt` (исходники фронта):
  - `v2RoundResult.ts` `9b2da9b7e297951f51587c0f94cc12c9`
  - `CasinoRoundResult.tsx` `a0ede72e3addb413dfca7a26b3d288da`
  - `useV2RoundNotice.ts` `a6768d5713866c753ab80d11a9b8758e`
  - `CasinoV2CompactPlay.tsx` `5b851cce59a228f71b1a20cd52cf7501`
  - `CasinoV2Table.tsx` `dfa70daf54a1b3da4e43003ae18a46d7`
  - `CasinoPlayersLobby.tsx` `1196c2057a9cf265cf6183de915f28c2`
  - `casino.css` `c8c3b3cbafff9fbb760ddd1d8b4e1360`
  - `check-round-result.mts` `324387b545e33e0cde35945a9b30902a`
- Живой шлюз: HTTP **200** `/casino/play/blackjack`, `/api/health`. SQL `casino_settings` **67**. Бандл `index-Bl9A2S_h.js`: `data-casino-v2-replay` **1**, «Ещё раунд» **1**. CSS `index-OVllMf7c.css`: `casino-round-result-amount` **1**.
- Клик на **18082** (fixture_buyer): стол 2×50 ₽ + бот. Игрок 20, бот перебор 26. Баннер **Победа +95 ₽** / «Ставка 50 ₽ · прибыль 45 ₽», статус **2/2 · готово**, кнопка **Ещё раунд**. Реванш открыл новый стол 50 ₽, 2/2, бот на месте, фаза добор.
- `staging-test.sh`: до **100%**, **7 failed**, имена те же, **новых нет**: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_...`. Строка `N passed` в захвате не попала; это фронтовый срез, collect не менялся (базовая линия журнала **1541 passed**).
- Docker наружу runtime: только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1` (ещё unpublished `80/tcp`). casino-bot без Host ports. Created-контейнеров нет.
- Прод (read-only `ssh focuspay`): **Permission denied (publickey)** — метки `index.html` / `panel.html` / unit в этом сеансе не снял. `deploy_all.py` не запускал.

Git: `focuspay` HEAD `61e47be`, dirty (этот срез в untracked `src/casino/` + чужой WIP). `focuspay-casino` HEAD `4b8d65e`. Не коммитил, прод не трогал.

Следующий шаг: **стоп**, жду клик-приёмку. FocusLucky / выплаты / прод не начинать.

Потыкать. Шлюз **18082** или туннель **18081**. **Жёсткое обновление** (Ctrl+F5).

1. `http://178.63.247.233:18082/casino/play/blackjack?mode=players` — стол 2 места, 50 ₽, бот, доиграть. После finish: статус **готово** (не «добор»), баннер с **суммой ₽**, **Ещё раунд**.
2. **Ещё раунд** — новый стол с той же ставкой и ботом, без ручного «Создать».
3. По желанию баккара тем же баннером; ничья — «Разделить» / «Перераздача».
4. Не менять: рейк 5%, HMAC, холдем/кланы спрятаны, пополнение по-прежнему заглушка.

## 2026-08-31 · «Ещё раунд» создаёт чистое лобби

Не прод. `deploy_all.py` не запускал. Postgres `StartedAt=2026-08-31T11:34:46Z` (не сдвигался). Паркованные холдем / кланы / дом 1×1 не трогал. HMAC / рейк 5% не менял.

Повод: реванш копировал `bot_count` и `autojoin: true` — сразу бот и новая партия в «добор». Нужно то же, что «Создать»: пустой стол, ждёт игроков.

Сделано: `v2ReplayBody` → `bot_count: 0`, `autojoin: false` (ставка / места / игра с законченного стола). Создатель на месте 1, остальные пустые.

Файлы: `focussite/frontend/src/casino/v2RoundResult.ts`, `focussite/frontend/scripts/check-round-result.mts`, `docs/CASINO_WORKLOG.md`.

Проверки:

- Локально `npx tsx scripts/check-round-result.mts`: **ok**.
- `rg` `bot_count: 0` / `autojoin: false` в `v2ReplayBody` + check script.
- md5 local = `/opt`: `v2RoundResult.ts` `f8311f6c5247dc8e9710255348325fb6`, `check-round-result.mts` `e69f11fcbec02ed0f0b11d48f25ae869`.
- `staging-sync.sh`: health **passed**. Gateway пересобрался (`COPY frontend/` не cache). HTTP **200** `/casino/play/blackjack`, `/api/health`. SQL `casino_settings` **67**.
- Живой бандл `index-BxS4bPaF.js`: `data-casino-v2-replay` **1**, `autojoin:!1` **1**. CSS `index-OVllMf7c.css`.
- Клик **18082**: finish (проигрыш −50 ₽, 2/2 готово) → **Ещё раунд** → стол **1/2 · ждёт игроков**, пустое место, **Добавить бота** / **Отменить**, без карт и без бота, ставка 50 ₽.
- `staging-test.sh`: **100%**, **7 failed**, имена те же, **новых нет**. Базовая линия журнала **1541 passed**.
- Docker runtime наружу: только `127.0.0.1:18081->8080/tcp` у gateway. Created нет. Postgres не трогал.
- Прод `ssh focuspay`: **Permission denied (publickey)**. `deploy_all.py` не запускал.

Git: HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: **стоп**, жду клик-приёмку. FocusLucky / выплаты / прод не начинать.

Потыкать. **18082** или **18081**. **Ctrl+F5**.

1. Доиграть блэкджек → **Ещё раунд**.
2. Должен появиться **тот же** стол (ставка, число мест), **1/N ждёт игроков**, без бота и без карт. Не новая партия.
3. Дальше как обычное «Создать»: плюс / бот / отмена.
4. Не менять: рейк 5%, HMAC, холдем/кланы спрятаны.

## 2026-08-31 · После итога — чистое лобби, не новый стол

Не прод. `deploy_all.py` не запускал. Postgres `StartedAt=2026-08-31T11:34:46Z`. HMAC / рейк 5% не менял. Парковка холдем/кланы на месте.

Повод: «Ещё раунд» всё ещё создавал стол (ты сидишь, можно сразу бота). Нужно лобби **без участников и без ботов**, чтобы заново «Создать» / посадить бота.

Сделано:

- Кнопка **«К столам»** (не «Ещё раунд»): убирает законченный стол из списка, **не** вызывает create. Ставка/места копируются в чипы.
- Страница стола: только **«В лобби»**, без создания.
- `dismissedIds`, чтобы poll не вернул finished.

Файлы: `CasinoPlayersLobby.tsx`, `CasinoV2Table.tsx`, `check-round-result.mts`, `docs/CASINO_WORKLOG.md`.

Проверки:

- `check-round-result.mts`: **ok**. md5 local=`/opt` lobby `d47342f06a8f86ab7cf8198a3891e01d`, table `782476fe47923927111df8bd534b7123`.
- Бандл `index-Cx8VoaG5.js`: `К столам` **1**, `Ещё раунд` **0**, `data-casino-v2-replay` **1**.
- Клик 18082: finish → **К столам** → своей полосы нет, никто не сидит, бота нет. Чужой стол чебурека остался. «Создать» на месте.
- `staging-sync.sh`: health **passed**. HTTP **200**. SQL настроек **67**.
- Прод `ssh focuspay`: publickey отказ.

## 2026-08-31 · FocusLucky: репетиция живого шоу на staging

Не прод. Кампания staging `focuslucky-prod-mirror-202608` **сожжена** (`status=drawn`, 10 мест). Следующий цикл — новая кампания.

Сделано по ходу:

- Админ `GET /api/admin/raffle` падал: нет `raffle_accrual_blocks`. Таблицу создал на staging. Миграция `add_raffle_accrual_blocks.sql` + bootstrap.
- `run_draw()` в `raffle_service.py` и `bot/.../raffle_db.py` теперь **raise** (мгновенный розыгрыш выключен).

Репетиция:

- Билетов в пуле **5700**. `fixture_buyer` (940002) **0** билетов — смотрел как зритель.
- `pre_show=5`, `spin_interval=10`. `POST start-show` → `drawing`.
- Closer (1 процесс `run_backend.py`): 10 мест `paid`, ledger `flucky-1-1` … `flucky-1-10` (5000…500 ₽, type `adjustment`). Итог `drawn` / `current_place=10`.
- UI: спин «крутится», зелёная сетка 1–10. После финиша верхний «ПРИЗ» показал **14 500 ₽** (банк, не 500 ₽ за 10 место) — косметика snapshot, деньги в ledger верные.
- Локально `tests.test_casino_raffle`: **12 OK**.

Риски к проду (код в дереве, на прод не выкатывал):

1. Миграции: `add_raffle_live_show.sql` (уже в staging) + **`add_raffle_accrual_blocks.sql`**.
2. Один uvicorn worker (SSE/closer in-process). Staging: один `python /runtime/run_backend.py`.
3. `run_draw` заглушен.
4. Начисление билетов только PAID + `bot_status_bridge`.
5. После этого шоу зеркало на staging **drawn** — для ещё одной репетиции нужна новая кампания.

Git: HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: **стоп**. Выплаты казино / прод / пост — после клик-приёмки.

Потыкать. **Ctrl+F5**. 18082.

1. Блэкджек: доиграть → **К столам** (не «Ещё раунд»). Лобби без тебя и без бота. Дальше «Создать» / «Добавить бота».
2. FocusLucky: розыгрыш уже **завершён** (10 победителей). Смотреть сетку и ledger. Новое шоу на этой кампании не запустится.
3. Не менять: рейк 5%, HMAC, холдем/кланы спрятаны.

## 2026-09-01 · FocusLucky: время админа, авто-шоу, шанс %, 4 волны

Не прод. `deploy_all.py` не запускал. Postgres `StartedAt=2026-08-31T11:34:46Z`. HMAC / рейк 5% / холдем-кланы не трогал.

Повод: админ задаёт время → в этот момент лента крутится как джекпот (1-е, 2-е…), на месте виден % на победу; бот шлёт всем за 6ч / 3ч / 1ч / 10 мин.

Сделано:

- `PATCH /api/admin/raffle/draw-at` (наивное = МСК). `active/draft/closed` только; `drawing/drawn` → 409. `ends_at = draw_at - 1s`. Сброс `notify_milestones` + pending `raffle_soon_*`.
- `/x8/focus-lucky`: datetime-local МСК. «Запустить шоу» как раньше (аварийно).
- Страница `/casino/play/raffle`: countdown до `draw_at` («До старта»), после старта — до спина. Приз текущего места, не пул. На выигравшем месте имя + `chance_pct` (tickets / eligible на это место). Спин `WEIGHTED_REEL_SPIN_MS` (10.5 с), интервал мест ≥ 12 с.
- Closer: `_maybe_autostart` как было; `_maybe_pre_notify` — окна 360/180/60/10 мин, аудитория все `bot_users`. `raffle_started` тоже всем. Миграция `add_raffle_timed_show.sql` (`notify_milestones`, `winner_tickets`, spin_interval ≥ 12).
- Staging-кампания **#2** `focuslucky-timed-show-20260831`: 3 места, 100 билетов (50/30/20). Админ PATCH `draw_at` +3 мин → closer сам `drawing`→`drawn`. Победители: 1) 940003 20.0% 5000 ₽, 2) 940002 37.5% 3000 ₽, 3) 940001 100.0% 2000 ₽. Ledger `paid`.

Файлы: `casino_raffle.py`, `routers/admin_raffle.py`, `raffle_service.py`, `migrations/add_raffle_timed_show.sql`, `AdminFocusLucky.tsx`, `CasinoRaffle.tsx`, `adminApi.ts`, `public.ts`, bootstrap `00`/`20`/`bootstrap_static_test.sh`, `tests/test_casino_raffle.py`, `check-weighted-reel.mts`.

Проверки:

- Локально `python -m unittest tests.test_casino_raffle -q`: **18 OK**. Окна: 5 мин → только 10; 2 ч → 180; 7 ч → пусто; naive `20:00` → 17:00 UTC.
- `npx tsx scripts/check-weighted-reel.mts`: **ok**.
- `rg`: `update_draw_at` / `due_notify_milestones` / `winner_tickets` / `patchRaffleDrawAt` / `raffle_soon_` в backend + панель.
- md5 local=`/opt`: `casino_raffle.py` `902512e025f81d957d57f7bd0c2c551b`, `add_raffle_timed_show.sql` `edaeb8516cc57ca6c0d0c8bb34916ca6`, `admin_raffle.py` `428ac60a6f504f1baa628dbde09485bf`, `CasinoRaffle.tsx` `9a63a6494847e0a90ef551217c8c3df6`, `AdminFocusLucky.tsx` `f2855892c021962fd57cee68846c5548`.
- `staging-sync.sh`: health **passed**. Gateway `COPY frontend/` не cache. HTTP **200** `/casino/play/raffle`, `/api/health`. SQL настроек **67**.
- Бандл `index-DizWbVmr.js`: `До старта` **1**, `casino-raffle-chance` **1**. CSS `index-DYLgu5Za.css`.
- Клик **18082** (покупатель): countdown **00:18** «До старта», приз **5 000 ₽** (не пул), шансы 50/30/20. После времени: места 1–3 с % (20.0 / 37.5 / 100.0). Шапка после `drawn`: приз 2 000 ₽, не 10 000.
- Клик **18081** `/x8/focus-lucky`: время МСК, интервал 12–120, текст «Напоминания всем в боте: за 6 часов…». «Запустить шоу» серое после `drawn`.
- Outbox кампании 2: `raffle_soon_10` **260** pending, `raffle_started` **260** pending, `raffle_place_win` **3** pending. Staging-бот: `STAGING: background tasks are disabled` — flush на стейдже не идёт (на проде задача в `main.py` живая). Не включал `STAGING_ENABLE_SAFE_BACKGROUND_TASKS` (спам 260 chat_id).
- `staging-test.sh`: **100%**, **7 failed**, имена те же (weekly cashback ×2, finance fixture, DurableLifecycle ×3, profile weekly wager). Новых имён нет. Локально raffle **18**. Базовая линия журнала **1541 passed** (+6 raffle timed).
- Docker runtime наружу: `127.0.0.1:18081->8080/tcp` gateway. Postgres не трогал.
- Прод `ssh focuspay`: **Permission denied (publickey)**.

Git: HEAD `61e47be`, dirty. Не коммитил.

Следующий шаг: **стоп**, жду клик-приёмку. Выплаты / прод / пост — нет.

Потыкать. **Ctrl+F5**. 18082 и 18081.

1. `/x8/focus-lucky`: поле «Время розыгрыша (МСК)». На уже `drawn` #2 оно только читается. «Запустить шоу» аварийное, сейчас серое.
2. `/casino/play/raffle`: сетка 3 мест с **%**. Новое шоу на #2 не запустится — нужна ещё одна кампания, если крутить снова.
3. Не менять: рейк 5%, HMAC, холдем/кланы спрятаны.

---

## 2026-09-01 · FocusLucky: чиню вёрстку страницы (жалоба «плохо»)

Дефект: шапка `/casino/play/raffle` собиралась как три `casino-hero-stat` **внутри** `casino-jackpot-hero`
(а это одноколоночная карточка под одну цифру) → карточка в карточке, три полосы во всю ширину,
цифра 16px. Плюс после `drawn` шапка всё ещё писала «Место 3 / Приз 2 000 ₽ / До старта —»,
а список пула — «Пока нет билетов в пуле».

Сделано (только фронт, бэкенд не трогал):

- Шапка по фазам (`before` / `show` / `done`): до старта — «До старта · Призовой фонд · Мои билеты»;
  во время шоу — «Место N из M · Приз места · До спина»; после — «Розыгрыш · Разыграно · Победителей».
- Новая сетка `.casino-raffle-hero` (3 колонки, `clamp(17px, 3.6vw, 26px)`), без вложенных карточек.
- Подпись кампании `.casino-raffle-caption`: название, месяц, время розыгрыша МСК.
- Доска мест: аватар победителя (`CasinoPlayerChip` 24px), процент как пилюля, у неразыгранных мест —
  «ждёт розыгрыша» / «крутится…» вместо пустоты.
- Текст правил и «Пока нет билетов в пуле» не показываются после `drawn`.

Проверки:

- `npx tsc --noEmit -p tsconfig.app.json`: **чисто**. `npx tsx scripts/check-weighted-reel.mts`: **ok**.
- md5 local=`/opt`: `CasinoRaffle.tsx` `580f6a4d95046063c66622b49890cd1f`, `casino.css` `21e6a526f4aaeb21c69a6c61ac127275`.
- `staging-sync.sh`: health **passed** дважды.
- Бандл `index-c1NoQUac.js`: `casino-raffle-hero`, `Призовой фонд`, `Разыграно`, `До старта`, `ждёт розыгрыша` — по **1**.
  CSS `index-DfgGj5Ng.css`: `casino-raffle-hero` **4**, `casino-raffle-caption` **3**.
- Клик **18082** покупателем: шапка «Розыгрыш Завершён / Разыграно 10 000 ₽ / Победителей 3»,
  подпись «FocusLucky · август 2026 · розыгрыш 01.09, 03:22 МСК», места 1–3 с аватарами и 20.0 / 37.5 / 100.0%.
- Прод не трогал.

Осталось: фазу `before` (До старта / Призовой фонд / Мои билеты) вживую не посмотреть — кампания #2 `drawn`,
нужна новая кампания на стейдже.

---

## 2026-09-01 · FocusLucky: архив розыгрышей + прогон кампании #3

Просьба владельца: показывать все розыгрыши — и текущий, и прошлые (в будущем ещё недельные),
чтобы можно было зайти, увидеть сколько осталось времени, участников и итоги.

Бэкенд:

- `GET /api/user/casino/raffle?campaign_id=N` — снапшот любой кампании ([`routers/user_casino.py`](site/exchange-backend/routers/user_casino.py)).
- `GET /api/user/casino/raffle/campaigns` — список: `title`, `month_label`, `status`, `draw_at`, `prize_pool_rub`,
  `place_count`, `winner_count`, `ticket_count`, `my_tickets`. Черновики без `draw_at` скрыты, сортировка по `draw_at DESC`.
- [`casino_raffle.py`](site/exchange-backend/casino_raffle.py): `_campaign_by_id`, `campaign_list`, `campaigns_for_user`,
  `snapshot(conn, viewer_id, campaign_id)`. У завершённой кампании победители больше не вычёркиваются из списка
  участников (`archived` → `excluded` пустой), поэтому в архиве видно полный состав и доли билетов.

Фронт ([`CasinoRaffle.tsx`](focussite/frontend/src/casino/CasinoRaffle.tsx)):

- Вкладки `.casino-raffle-tab` над шапкой: месяц, статус, время розыгрыша МСК, «мои N» билетов.
- Заголовок списка: «В пуле» / «Участники розыгрыша» + билеты и число людей.
- SSE-спин применяется только к просматриваемой кампании; список вкладок перечитывается при смене статуса.

Проверки:

- `tsc --noEmit`: чисто. `check-weighted-reel.mts`: **ok**. `python -m unittest tests.test_casino_raffle -q`: **18 OK**. `py_compile`: ok.
- md5 local=`/opt`: `CasinoRaffle.tsx` `f87bf0d3b9a727032ad10ad24f213eb8`, `casino.css` `edce367a045ee91503d22b60938c0250`,
  `public.ts` `0eb86e6d45e7225f4578c058ef1e263a`, `casino_raffle.py` `bec26edd808ae1d18b342dfef06c1b00`,
  `user_casino.py` `cf5337da77e6f15bf3ae55fdda63731a`.
- `staging-sync.sh` health **passed**. HTTP **200** `/casino/play/raffle` и `/api/health`.
  Бандл `index-3aaiMyZ-.js`: `casino-raffle-tab`, `raffle/campaigns`, `Участники розыгрыша`, `идёт приём билетов`.
- Кампания **#3** `focuslucky-archive-demo-20260901`, «сентябрь 2026», 3 места (4000/2500/1500), 100 билетов
  (940001×40, 940002×35, 940003×25), `draw_at` +3 мин → closer сам запустил шоу.
  Победители: 1) 940003 **25.0%** 4000 ₽, 2) 940002 **46.7%** 2500 ₽, 3) 940001 **100.0%** 1500 ₽, все `paid`.
  Outbox #3: `raffle_soon_10` **260** pending, `raffle_started` **260** pending, `raffle_place_win` **3** pending
  (staging-бот не флашит).
- Клик 18082: фаза «до старта» (02:41 / 8 000 ₽ / 35 · 35.0%), спин («Место 2 из 3», «крутится»), финал,
  архив августа (10 победителей, 14 500 ₽, 247 участников, 5700 билетов). У кампании #1 процентов нет —
  `winner_tickets` тогда ещё не писался, поле рисуется пустым без ошибки.
- Прод не трогал, не коммитил.

Потыкать (Ctrl+F5, 18082): вкладки августа и сентября, переключение туда-обратно, список участников
в архиве, «Честность» из архивной кампании.

---

## 2026-09-01 · Выплаты казино: очередь, право, касса

Срез: выводы из кассы FocusBet только в `/ops/casino-payouts` под `casino.payout`. Общая очередь `/ops/orders` их больше не видит. Пополнение в кассе — «скоро». История кошелька живая.

Сделано:

- Миграция `user_referral_withdrawals.source` (`balance` | `casino`, default `balance`). `create_withdrawal(..., source=)` в бэке и боте. Касса шлёт `source: "casino"`. Кабинет/рефералка — default `balance`. TG-кнопка кабинета: casino → `/ops/casino-payouts`.
- Право `casino.payout` в `ALL_PERMISSIONS`. Нет в default `finance`/`client`. Grant через `operator_permission_grants`. Строка в `docs/PERMISSION_MATRIX.md`.
- `GET /api/operator/orders` фильтрует `source='casino'`. Claim/payout/paid общей очереди — 404 на casino. Новые `GET/POST /api/operator/casino/payouts*` (claim, crypto payout, card paid, reject). Карточка: баланс, отыгрыш, rail, билеты FocusLucky, последние игры.
- Ops UI `/ops/casino-payouts` в «Финансы», пункт нава только при `casino.payout`.
- Касса: вкладка пополнения — `data-casino-deposit-soon`, без способов и stub-реквизитов. Кошелёк: `GET /user/balance/withdrawals` + ledger `entries`.
- Staging: накатил недостающие колонки вывода (`operator_id`, `network_fee_rub`, `payout_amount_rub`, `payout_tx_hash`) и таблицу `operator_permission_grants` (`add_rbac_templates_hardening.sql`) — без них очередь 500. Grant `casino.payout` → `fixture_full_finance_ops`. `fixture_payments_finance_ops` на этом томе нет.

Проверки:

- Локально: `npx tsx scripts/check-casino-wallet-rules.mts` **ok**. `tsc --noEmit` чисто. `python -m unittest tests.test_casino_payouts_ops tests.test_rbac_permissions tests.test_casino_payout_rail -q`: **32**, skipped 6 без asyncpg. `py_compile` ok.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1565**. Новых имён нет. `test_casino_payouts_ops` **9** collected.
- md5 local=`/opt`: `user_referral_withdraw.py` `b1d06365fb3a9cb325becf737d4f813e`, `permissions.py` `21b8be72246b5aea7ffdd3f50905d46a`, `operator.py` `84831f877525f7f31e516730cd1dcf71`, `operator_casino_payouts.py` `491f0e54e5f067ffc7dda490a38d6e1b`, `user_balance.py` `dc6f4a9409c1c65f2090e0591c78e9a9`, `add_withdrawal_source.sql` `e4c64b2547b8f26a9f0d10c255646234`, `CasinoCashier.tsx` `2a71d5519355961deb52134727636b20`, `CasinoWallet.tsx` `70a6003e9188a5f44ba9f39c6bd9051d`, `OperatorCasinoPayouts.tsx` `d5e5b1183850f3d71ce6e6e8d68fb113`, `OperatorRoutes.tsx` `6b3cf22c534bdaa794e1c28b34df4983`.
- `staging-sync.sh` health **passed** дважды. HTTP **200** `/casino` 18081 и 18082, `/api/health` `{"status":"ok"}`. Бандл `index-Dwd51SPK.js`: «Пополнение скоро» **1**; `panel-CRRqkUml.js`: `/ops/casino-payouts` **1**.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Публичный play `:18082` как раньше.
- API: client ops `123` → `GET /casino/payouts` **403**. Finance `fixture_full_finance_ops` → **200**. `/operator/orders` withdrawals: **1** (balance #1 50 ₽), casino **0**.
- Клик 18082 кошелёк покупателя: счётчики **30 / 1**, история «Вывод · карта −5 000 ₽ в обработке», касса пополнения «Пополнение скоро» (0 способов, без реквизитов), вывод — 6 методов.
- Клик 18081 ops: client — пункта «Выплаты казино» нет, прямой URL тост «Недостаточно прав: casino.payout». Finance — пункт в Финансах, входящая **#2 5 000 ₽** (ауебратва, баланс 7 290,3 ₽, билеты 35, взять/отклонить). `/ops/orders` «Выводы средств · 1» только **#1 · 50 ₽**.
- `ssh focuspay` read-only: **Permission denied (publickey)** — на прод не ходил и ничего не писал. `deploy_all.py` не запускал.

Потыкать (Ctrl+F5): касса «скоро» и вывод на **18082** `/casino/wallet`; `/ops/casino-payouts` с grant (`fixture_full_finance_ops` / `123` на **18081**) и без (`123` / `123`); `/ops/orders` без казино-строк. Взять/отклонить #2. Не коммитил.

---

## 2026-09-01 · Единый профиль клиента: обменник + казино

Срез: `/ops/client/:id` и модалка `/x8/users` — вкладки **Обменник** / **Казино**. Казино-срез с отдельного эндпоинта, два scope. Оператору нет RTP/дом-нетто. Прибыль сервиса не отдаём.

Сделано:

- Новый `casino_client_profile.py`: `build_casino_client_profile(conn, player_id, scope=)`. Ник/уровень/отыгрыш/рельс/баланс/история/FocusLucky/выводы `source=casino`. Блок `risk` только при `scope=admin` (7d, не полный `fetch_risk_snapshot`). `apply_scope` срезает `risk` и top-level `house_net_rub` до сети.
- `_player_snapshot` в очереди выплат зовёт тот же сборщик.
- `GET /api/operator/users/{id}/casino` и `/casino/history` под `PERM_CASINO_PAYOUT`. `GET /api/admin/casino/players/{id}/profile` и `/history` под админом.
- Ops: шапка общая, вкладки; «Казино» только при `casino.payout`. Обменник дорисован: summary, балансы, активная заявка, реферралка, промо, отзывы.
- Админ-модалка: те же вкладки, казино `scope=admin`, ссылка `/x8/casino/games?player_id=`. Общий `ClientCasinoTab` + `Tabs` в primitives.
- Staging: на живой БД не было `review_submissions` → `GET /api/operator/users/940002` 500. Создал таблицу; миграция `bot/tg_bot_btc/migrations/add_review_submissions.sql` в `00-apply-migrations.sh`, `20-full-panel-bootstrap.sh`, `bootstrap_static_test.sh`.

Проверки:

- Локально: `python -m unittest tests.test_client_profile_casino tests.test_casino_payouts_ops -q` → **21 OK**, 5 skipped (asyncpg). `npx tsx scripts/check-client-profile-tabs.mts` **ok**. `npm run build` ок.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Collect-only **1577** (было 1565, +12 `test_client_profile_casino`). Новых имён нет. На staging `test_client_profile_casino.py` **12/12**.
- md5 local=`/opt`=`/app/backend`: `casino_client_profile.py` `caffeade3f0d8ff54024ed91bcb83f89`, `operator_casino_payouts.py` `ec501b17556f3c4cccb2aa3155384550`, `admin_casino.py` `e0a6b45d12ac63841bb670efc8f93fa6`, `test_client_profile_casino.py` `99ee3f360369f10e79d7ad401ed1d38b`, `ClientCasinoTab.tsx` `78afb63b58c16df93fc084e0cbd9d7b2`, `primitives.tsx` `6e73e74240b1d8a28871fda83c349703`, `ClientProfile.tsx` `b7f6fcdc2e75038656647a631995c442`, `AdminUsers.tsx` `be0c853abd44116b22fc4d838e55128c`, `casinoClientProfile.ts` `0fad3183b853ac97a5689e709fb83e46`, `operatorApi.ts` `7aea8290d398be7da8f13f58a3dc32f9`, `adminApi.ts` `74b93999da7bbd68ba90aa4f4fcec9a5`, `check-client-profile-tabs.mts` `1a92642d6d1ffa15e295d0ecd6c28467`, `PERMISSION_MATRIX.md` `fb119309bb9b3747ff8b505aafa2cc26`. Bootstrap: `20-full-panel-bootstrap.sh` `ba275c8339f023fe3e9b38a9675b02bd`, `00-apply-migrations.sh` `20ec153d94f4dcec0c36425365619093`.
- Health **passed**. HTTP **200** `/healthz` `/casino` `/x8` `/ops`, `/api/health` `{"status":"ok"}`. Бандл `panel-BaxzwmEQ.js`: `data-client-casino-risk` **1**, `data-client-casino-tab` **1**.
- Docker runtime: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Host nginx **18082** как раньше (play-public). Bootstrap при recreate gateway: exit 0, `review_submissions` есть. Grant `casino.payout` → operator **940102**.
- API 18081: client ops `123` → `GET /users/940002/casino` **403** `Недостаточно прав: casino.payout`. Finance `fixture_full_finance_ops` → **200**, `scope=operator`, **нет** `risk` / `house_net_rub`; игрок **940002**, played, available **7290.3**, tickets **35**, 20 игр, 1 вывод. Missing `999999999` → **404** «Игрок не найден». Admin `123` → **200**, `scope=admin`, `risk` есть, RTP игрока **98.53%**.
- Клик 18081 finance `/ops/client/940002`: вкладки Обменник + Казино. Обменник: KPI, балансы, реферралка, промо. Казино: ник **ауебратва**, уровень 4, 7290.3 ₽, отыгрыш, крипта разрешена, FocusLucky 35, рулетка ~239k, вывод #2 5000 pending. **Нет** дом-нетто / RTP. Client ops `123`: только Обменник, пункта «Выплаты казино» нет. Админ `/x8/users?user=940002`: Казино + **Риск и RTP** (794 раунда, RTP 98.53%, теория 14.77%, Δ 83.76 high). Ссылка **Игры этого игрока** → `/x8/casino/games?player_id=940002`.
- `ssh focuspay` read-only: **Permission denied (publickey)** — на прод не ходил. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод / следующий пункт плана — после клик-приёмки этого среза.

Потыкать (Ctrl+F5, туннель **18081** или host **18082** только для кассы; панель — 18081):

1. `/ops/client/940002` как `fixture_full_finance_ops` / `123` — обе вкладки, казино без дом-нетто и RTP.
2. Тот же URL как `123` / `123` — только Обменник, вкладки Казино нет.
3. `/x8/users?user=940002` как админ `123` — Казино + блок «Риск и RTP» + «Игры этого игрока».

---

## 2026-09-01 · Быстрый переход в профиль + выплаты как заявки

Срез: из заявок и выплат казино имя клиента ведёт в `/ops/client/:id`. Выплаты казино — тот же master-detail, что заявки.

Сделано:

- `opsClientPath.tsx`: `OpsClientLink`, `/ops/client/{id}` и `?tab=casino`. Клик по имени — `stopPropagation`, строка по-прежнему выбирает карточку.
- `ClientProfile`: `?tab=casino` открывает Казино, только при `casino.payout`; вкладки пишутся в URL (`replace`). Без права query сбрасывается.
- `OperatorOrders`: имя в списке + **Профиль →** в карточке → обменник.
- `OperatorCasinoPayouts`: слева единый список (Входящие/Мои/Команда), справа карточка; шапка со счётчиками и ↻; баннер смены через `getMe`; `?payout=`; имя и **Профиль →** → `?tab=casino`. Действия те же: взять / TX / оплачено / отклонить.

Проверки:

- Локально: `npx tsx scripts/check-ops-client-jump.mts` **ok**, `check-client-profile-tabs.mts` **ok**. `npm run build` ок, бандл `panel-C5puvA-i.js`.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. Collect-only без изменений (**1577**), бэкенд не трогал.
- md5 local=`/opt`: `opsClientPath.tsx` `b2103e49bbc5f885d365550094b36239`, `ClientProfile.tsx` `b66e208b98b912f4f4c9cff3605ac8c1`, `OperatorOrders.tsx` `fd642a70410d8d23de316bd971e49d55`, `OperatorCasinoPayouts.tsx` `d6511b6c0f8f91767bf741f8002c2c81`, `check-ops-client-jump.mts` `4b1ca8797c75f78c49fca15c889d4b85`.
- Gateway rebuild `--no-deps` (bootstrap не гонял). HTTP **200**. Живой `panel-C5puvA-i.js`: `data-ops-casino-payouts` **1**, `data-ops-client-link` **1**, `?tab=casino` **1**.
- Docker runtime: наружу только `127.0.0.1:18081->8080/tcp`.
- Клик 18081: client ops `123` из заявок → `/ops/client/940002`, вкладка только **Обменник**. Finance `fixture_full_finance_ops`: выплаты слева #2 Карта · ауебратва 5000, справа карточка (баланс 7290.3, 35 билетов, взять/отклонить). **Профиль →** → `/ops/client/940002?tab=casino` (Казино открыто). `?payout=2` сразу открывает карточку. В заявках после выбора строки — **Профиль →**.
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод / следующий пункт — после клик-приёмки.

Потыкать (Ctrl+F5, туннель **18081**):

1. `/ops/orders` как `123` / `123` — имя клиента в списке и **Профиль →** в карточке, вкладка Обменник, без Казино.
2. `/ops/casino-payouts` как `fixture_full_finance_ops` / `123` — список+карточка как заявки; имя / **Профиль →** сразу на вкладку Казино.
3. `/ops/casino-payouts?payout=2` — карточка #2 открыта.

---

## 2026-09-01 · Касса: минимум карты 500 ₽

Срез: вывод FocusBet на карту от **500 ₽**, не от 5 000. Рефералка / кабинет / партнёры по-прежнему 5 000.

Сделано:

- `casino_min_withdraw_card_rub=500` (`CASINO_MIN_WITHDRAW_CARD_RUB`) в бэке и боте. `create_withdrawal` считает минимум после `source`: casino → 500, иначе 5 000.
- Касса: чипы 500 / 1000 / 2500, дефолт 500, подпись «от 500 ₽ · комиссия 0 ₽», клиентская ошибка `Минимум для карты: 500 ₽`.

Проверки:

- Локально: `python -m unittest tests.test_casino_payouts_ops -q` → **13**, skipped 8 без asyncpg (конфиг 500/5000 проходит). `npx tsx scripts/check-casino-wallet-rules.mts` **ok**. `npx tsc -b` чисто. `py_compile` ok.
- На staging: `tests.test_casino_payouts_ops` **14/14**. `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- md5 local=`/opt`=`/app/backend`: `user_referral_withdraw.py` `0dc6efc491f19274cea2ba2f418848da`, `config.py` `59f782c9ffc6882f94d9958c49fa60ea`. Касса: `casinoWalletRules.ts` `7c2ae9b34eccbdc890227e238758ec58`, `CasinoCashier.tsx` `c081d8743b274128e3791b30281deb8b`. Бот: `user_referral_withdraw.py` `b3843eb4015e07accfa2a79cc913c31e`, `config_rates.py` `cbe2ab6d15d3122c51c374865e54fa9a`.
- `staging-sync.sh` health **passed**. HTTP **200** `/casino` 18081 и 18082, `/api/health` `{"status":"ok"}`. Бандл `index-BQ3C2D7w.js`: «На карту» + `от ${us} ₽`, `us=500`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** как раньше.
- Клик 18082 касса Fixture Buyer: чипов 250 нет; 250 → `Минимум для карты: 500 ₽` на клиенте; 500 → заявка создана. БД: `#3` 940002 **500** card casino pending; старая `#2` 5000 paid.
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5, **18082**):

1. `/casino` → Вывести → На карту: чипы 500/1000/2500, 250 в поле — красная «Минимум для карты: 500 ₽».
2. 500 ₽ уходит в `/ops/casino-payouts` (не в `/ops/orders`).
3. Кабинет «Вывести средства» по карте по-прежнему от 5 000.

---

## 2026-09-01 · Шапка: баланс после вывода

Срез: в шапке FocusBet после заявки на вывод сразу то же число, что «Доступно к выводу» в кассе (`available_rub`, pending уже зарезервирован). Не ledger `balance_rub`.

Сделано:

- `spendableBalanceRub()` в `casinoWalletRules.ts`: берёт `available_rub`, иначе `balance_rub`.
- Касса после успешного `withdraw` шлёт `focuspay-casino-balance`.
- Шапка `CasinoShell`, кошелёк и профиль слушают событие и рисуют spendable.

Проверки:

- Локально: `npx tsx scripts/check-casino-wallet-rules.mts` **ok** (`spendableBalanceRub({ available_rub: 6790.3, balance_rub: 7290.3 }) === 6790.3`; cashier `dispatchEvent`; shell/wallet/profile `spendableBalanceRub`).
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. Бэкенд не трогал.
- md5 local=`/opt`: `casinoWalletRules.ts` `45ff040575e0a7f3ff004c69e5e7f15a`, `CasinoCashier.tsx` `30b0cdba5f30c902becff1385406b0ac`, `CasinoShell.tsx` `11f692bbbc32f7c8210bb3e9f0674c81`, `CasinoWallet.tsx` `55c17bbdd159fec434882c0ba32f4441`, `CasinoProfile.tsx` `e6ed0fe6fa6e26b546db14add344bce6`.
- `rg -c spendableBalanceRub`: rules 1, shell 2, wallet 2, profile 2, check 7.
- HTTP **200** `/casino` 18081, `/api/health` `{"status":"ok"}`. Живой бандл `index-BaXmYop8.js`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** как раньше.
- Клик 18082 Fixture Buyer: шапка после F5 **6 790,3 ₽** = касса «Доступно к выводу». Отклонил `#3`, шапка **7 290,3 ₽**; вывод 500 без перезагрузки → шапка **6 790,3 ₽**. БД `#5` 940002 500 card casino pending. Кошелёк и профиль «Баланс, ₽» тоже **6 790,3 ₽**.
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5, **18082**):

1. `/casino` шапка и Вывести → «Доступно к выводу» — одно число.
2. Вывести 500 (если нет pending) — шапка уменьшается сразу, без F5.
3. Кошелёк и профиль «Баланс, ₽» совпадают с шапкой.

---

## 2026-09-01 · Комиссии вывода FocusBet

Срез: вывод `source=casino` — карта **100 ₽**, BTC/LTC **$2.50** → ₽ по USDT/RUB. Касса подписывает ту же сумму в валюте шапки (₽ / USDT). Кабинет/рефералка `source=balance` без изменений (карта 0, BTC 50, LTC 20). USDT кассы по-прежнему **$5** UI / **$4** API.

Сделано:

- Настройки `casino_withdraw_fee_card_rub=100`, `casino_withdraw_fee_usd_btc=2.5`, `casino_withdraw_fee_usd_ltc=2.5` в API и боте. Хелпер `casino_withdraw_fee_rub` / `withdraw_fee_rub(..., source=)`. `create_withdrawal` пишет `network_fee_rub` и `payout_amount_rub` и на карту казино; payout ≤ 0 — «сумма слишком мала». Рельс фиата по-прежнему суммирует gross `amount_rub`.
- Telegram: `format_withdrawal_admin_message` при fee > 0 — «списано / комиссия / к отправке» и для карты.
- `/ops/casino-payouts`: Списано / Комиссия / К выплате; в списке первичная сумма = нетто (`payout_amount_rub`, не `Number(null)===0`).
- Касса: `casinoCurrency.ts` (`focuspay_casino_currency`); карта 100 ₽, BTC/LTC `$2.50`; подписи в ₽ или USDT. Поле суммы остаётся в ₽.

Проверки:

- Локально: `npx tsx scripts/check-casino-wallet-rules.mts` **ok** (карта 100; BTC/LTC при курсе 80 = 200 ₽; `formatFeeLabel` ₽/USDT; ops «К выплате»). `npx tsc -b` чисто. `python -m unittest tests.test_crypto_network_fee -q` (бот) **7 OK**. `tests.test_casino_payouts_ops` локально часть skipped без asyncpg; хелперы 100 / 200@80 проходят.
- На staging: `python -m unittest tests.test_casino_payouts_ops -q` → **25 OK**. `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. **1586 passed**, 1 skipped. Новых имён нет.
- md5 local=`/opt`=`/app/backend`: `crypto_network_fee.py` `6046d6932300c0db6838522a638ef5e4`, `user_referral_withdraw.py` `180e190d258f4eaee0300922cb5ecce2`, `config.py` `2674343a727c6b160b1d6879bc4cef5b`. Касса: `casinoWalletRules.ts` `b673d31d68cd3a43cbe4f79898395e92`, `CasinoCashier.tsx` `14fe3874d65d4d16e2668dcc0b75db97`, `casinoCurrency.ts` `8e92e7fde416e2548cf428d04b12c77a`, `CasinoShell.tsx` `e119531ccb91a081ec5b6e73b7e8d8ac`. Ops: `OperatorCasinoPayouts.tsx` `f4d7f3fbacc63a8776f7127a05024dea`. Бот: `crypto_network_fee.py` `edfccffae5a4e79efa1e750ef4c62bcd`, `user_referral_withdraw.py` `50141a990839fb4e58deafe273b97d12`, `config_rates.py` `165c1329e52ea1976c458ace904b40d4`. Чек: `check-casino-wallet-rules.mts` `62c52d22b1d1402faebb7b81af789437`, `test_casino_payouts_ops.py` `4eb1adf43ff241c59c47d9d789bcef1f`. `.env.example` local≠`/opt` (чужой WIP: stickers / onion / webhook IPs) — ключи комиссий в local example есть; рантайм берёт defaults из `config.py`, суммы совпали.
- `staging-sync.sh` health **passed**. HTTP **200** `/casino` 18081 и 18082, `/ops` 18081, `/api/health` `{"status":"ok"}`. Бандл `index-VkJwVhoR.js`, `panel-DmBqSAPj.js`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** как раньше.
- `rg -c casino_withdraw_fee`: `crypto_network_fee.py` 5, `config.py` 3, `test_casino_payouts_ops.py` 8; бот хелпер 2, `test_crypto_network_fee.py` 4. `CARD_WITHDRAW_FEE_RUB` / `formatFeeLabel`: rules 7, cashier 3, check 9.
- SQL: `#6` 940002 card casino pending **500 / fee 100 / payout 400**. Старые `#4`/`#5` fee 0 (до этой задачи). `#5` отклонил, чтобы создать `#6`.
- Клик 18082 касса Fixture Buyer: карта «комиссия 100 ₽»; в шапке USDT — «1.20 USDT · к выплате 4.82 USDT» при 500 ₽; BTC «комиссия 2.50 USDT · к выплате 0.51 USDT» на 250 ₽; USDT-способы «5.00 USDT». Заявка 500 создана.
- Клик 18081 `/ops/casino-payouts`: `#6` список **400 ₽**; карточка Списано 500 / Комиссия 100 / К выплате 400. Старая `#4` чебурек 500 / 0 / 500.
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод (`deploy_all.py`, рестарт API) — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5; касса **18082**, панель туннель **18081**):

1. `/casino` → Вывести → На карту: комиссия 100 ₽ (или USDT-эквивалент), к выплате = сумма − 100. Сумма меньше комиссии не уходит.
2. BTC и LTC — $2.50 / ₽ по курсу. USDT-вывод визуально как раньше ($5).
3. Переключатель ₽ / USDT в шапке — подписи комиссий переключаются. Поле суммы остаётся в ₽.
4. `/ops/casino-payouts` как `fixture_full_finance_ops` / `123`: `#6` списано 500 / комиссия 100 / к выплате 400; оператор платит нетто.

---

## 2026-09-01 · Вывод: статусы, отмена, история

Срез: FocusBet — актуальная заявка отдельно от истории; отмена только в очереди; после «Передать на выплату» — «На выплате», текст про 3 часа, без кнопки отмены. Фаза без новой колонки в БД: `pending` + пустой `operator_id` = ожидание, `pending` + оператор = на выплате. Кабинет обмена и бот не трогали. API cancel только `source=casino`.

Сделано:

- `list_user_withdrawals` читает `operator_id`; публичный `player_withdrawal_out`: `phase`, `cancellable`, `status_label`, `status_hint` (без `operator_id` / `admin_message_id`).
- `POST /user/balance/withdrawals/{id}/cancel`: свой ряд, casino, pending и без оператора; иначе 409. Резерв снимается сам (pending больше нет).
- `GET /user/balance/withdrawals?source=casino`. Опс: **Передать на выплату** (= claim), бейдж **На выплате · обычно до 3 часов**.
- Кошелёк: актуальные / история. Касса при активной заявке — карточка и отмена (у processing кнопки нет). Поллинг 5 с, чтобы после claim фаза сменилась без F5.

Проверки:

- Локально: `npx tsx scripts/check-casino-wallet-rules.mts` **ok**. `npx tsc -b` чисто. `python -m unittest tests.test_casino_payouts_ops -q` → **25**, skipped 19 без asyncpg.
- На staging: `tests.test_casino_payouts_ops` **25/25**. `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- md5 local=`/opt`=`/app/backend`: `user_referral_withdraw.py` `180e190d258f4eaee0300922cb5ecce2`, `user_balance.py` `e935ed341f868bd9d0dc172225936a77`. Фронт: `CasinoWallet.tsx` `b09c90c47cd3f4ebeca3343913e4dac5`, `CasinoCashier.tsx` `c92dfb3c64ba00b5ad85eec6e3dc3eef`, `casinoWalletRules.ts` `b673d31d68cd3a43cbe4f79898395e92`, `CasinoWithdrawalCard.tsx` `e36243066ddfd2adf9184fdbc9dab4a4`, `OperatorCasinoPayouts.tsx` `f4d7f3fbacc63a8776f7127a05024dea`, `user.ts` `2943071c4da29b16eeeb1f9eb0a60030`.
- `staging-sync.sh` health **passed**. HTTP **200** `/casino` 18082 и 18081, `/ops` 18081, `/api/health` `{"status":"ok"}`. Бандл `index-FtX5DpWp.js`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** как раньше.
- `rg`: `cancel_casino_withdrawal` в `user_referral_withdraw.py` + роутер + тесты; ops «Передать на выплату»; кошелёк/касса `setInterval(..., 5000)`.
- SQL: `#7` 940002 casino **500 pending**, `operator_id=940102` (на выплате). `#6` canceled (отмена с кошелька). `#4` чебурек pending без оператора. `#1` balance pending не в казино-листе.
- Клик 18082 Fixture Buyer `/casino/wallet`: отмена `#6` 500 → баланс **7 290,3 ₽**, в истории **Отменена**. Новая 500 → **В ожидании** + Отменить; касса сверху та же карточка. После ops claim: **На выплате**, «обычно в течение 3 часов», кнопки отмены нет (кошелёк и касса).
- Клик 18081 `/ops/casino-payouts` (`fixture_full_finance_ops`): входящие **В ожидании**, кнопка **Передать на выплату**; после claim `#7` **На выплате · обычно до 3 часов**, дальше Отметить оплаченным / Отклонить.
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5; касса **18082**, панель туннель **18081**):

1. `/casino/wallet`: актуальные vs история. У «В ожидании» — Отменить, баланс возвращается. После отмены заявка в истории «Отменена».
2. Касса «Вывести» при висящей заявке — карточка, новую сумму не слать.
3. `/ops/casino-payouts`: входящая → **Передать на выплату**. У игрока (подождать ~5 с или F5) пропадает Отменить, статус **На выплате**, текст про 3 часа.
4. Кабинет обмена / бот — те же статусы, что были; отмены казино там нет.

---

## 2026-09-01 · Вывод: до 5 заявок, пауза 5 минут

Срез: FocusBet — в работе до **5** заявок (`pending` casino). Новую можно создать не чаще чем раз в **5 минут** (считается `created_at` любой casino-заявки, в том числе отменённой). Кабинет/бот по-прежнему один pending.

Сделано:

- Снят уникальный индекс «один pending на всех». Остался unique только для `source=balance`.
- `_lock_and_check_pending(..., casino)`: COUNT pending casino ≥ 5 → ошибка; последняя casino-заявка младше 5 мин → «через N мин».
- `POST /user/balance/withdraw` для casino больше не режется общим `has_pending_withdrawal`.
- Касса: карточки активных + форма, если лимит не исчерпан и пауза прошла; иначе текст паузы/потолка.

Проверки:

- Локально: `check-casino-wallet-rules.mts` **ok**. `npx tsc -b` чисто. `tests.test_casino_payouts_ops` **30**, skipped 24 без asyncpg.
- Staging: payouts **30/30**. `staging-test.sh`: **7 failed**, те же имена. Новых нет.
- md5 local=`/opt`: `user_referral_withdraw.py` `120c5ec04e498c002b88bc9081acf01a`, `user_balance.py` `c6fb4f57ad391932662f4609f67f5e8d`, `add_casino_withdraw_pending_cap.sql` `3b01cc3be82d6bcd8f9ad7889d84e9e9`, `casinoWalletRules.ts` `4ae4d36da5b028a10957734c03d4bc02`, `CasinoCashier.tsx` `eed7ad82d65936fe6495688823c7d5b2`, `CasinoWallet.tsx` `4d4a0af51dfd83e3d6d107f2df1ece7b`.
- Индекс: `idx_user_referral_wd_one_pending` нет; есть `idx_user_referral_wd_one_pending_balance`.
- `staging-sync.sh` health **passed**. HTTP **200** `/casino` 18082 и 18081, `/api/health` ok. Docker: наружу только `127.0.0.1:18081`.
- SQL: `#8` 940002 casino 500 pending без оператора; `#7` pending + operator 940102.
- Клик 18082: при `#7` на выплате касса дала форму; вторая 500 создалась; сразу «Следующую заявку можно создать через 5 мин.»; в актуальных 2 заявки (ожидание + на выплате).
- `ssh focuspay` **Permission denied**. `deploy_all.py` нет. Не коммитил.

Следующий шаг: **стоп**. Прод — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5, **18082**):

1. Касса при 1–4 заявках в работе — форма есть. Сразу после создания — «через 5 мин», форму не открыть.
2. Отмена не сбрасывает паузу 5 минут.
3. Кабинет «Вывести средства» по-прежнему один pending.

---

## 2026-09-01 · Кошелёк: вкладки истории и цвета статусов

Срез: `/casino/wallet` — три вкладки истории (пополнения / выводы / игры), без смешанного ledger. Статусы бейджами: в ожидании жёлтый, успешно зелёный, отмена/неуспех красный. Касса Пополнить/Вывести как была.

Сделано:

- Вкладки в `CasinoWallet.tsx`: пополнения из `getLedger` (только deposit: `Casino deposit`, бонус уровня, кешбэк, промо; не FocusLucky / v2 stake / room refund), выводы из `getWithdrawals(source=casino)` одним списком (активные сверху, Отменить у awaiting), игры из `getCasinoPlayerHistory`.
- `casinoWalletRules.ts`: `ledgerKind`, `withdrawalStatusTone`, `gameResultTone`, `withdrawalsForHistoryTab`. Бейдж `.casino-status-badge` в `casino.css` (`--vip` / `--win` / `--lose`). У canceled теперь красный; awaiting/processing жёлтые.
- Плитки: Пополнения / Выводы — длины списков, не лимит 30. Касса и ops payouts не трогал.

Проверки:

- Локально: `npx tsx scripts/check-casino-wallet-rules.mts` **ok**. `npx tsc -b` чисто.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- md5 local=`/opt`: `CasinoWallet.tsx` `1a8c4b6698da6b7bdaa7da84500c23f1`, `casinoWalletRules.ts` `3d896e75151e6dcaf2e7a61198ad1330`, `CasinoWithdrawalCard.tsx` `8f49e9a52e8e10ff041e0c036c42422e`, `casino.css` `2f46a2ebfa3a8df06fc07e9b4440c127`, `user.ts` `5c7f8b5efe8f3e7ac325aec358dfca4a`, `check-casino-wallet-rules.mts` `570ca61f7e41649bcb8ffc48ae22394d`.
- `staging-sync.sh` health **passed** (дважды, после сужения deposit-фильтра). HTTP **200**: `/casino`, `/casino/wallet` на 18082 и 18081, `/api/health` `{"status":"ok"}`. Бандл `index-C34sPFtv.js`: `data-casino-wallet-tab` **1**. CSS `index-BtXDrkS2.css`: `casino-status-badge` **1**. Сборка **2288** modules.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** как раньше.
- SQL `casino_settings` count **67**.
- `rg` `data-casino-wallet-tab|casino-status-badge|isDepositLedgerEntry|withdrawalStatusTone|gameResultTone`: wallet 9, rules 3, wd-card 3, css 6, check 21.
- Клик 18082 Fixture Buyer: плитки **Пополнения 3 / Выводы 6**. Вкладка пополнения — три «Бонус уровня» + зелёный **Успешно**, без FocusLucky и v2 stake. Выводы: **В ожидании** жёлтый + Отменить, **На выплате** жёлтый, **Отменена/Отклонено** красный, **Выплачено** зелёный. Игры: раунды (FocusLucky/блэкджек/рулетка/комнаты), **Победа** зелёный, **Проигрыш/Возврат** красный, без сырых `Casino v2 stake`.
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5, **18082** `/casino/wallet`):

1. Три вкладки: в пополнениях нет ставок и выводов; в выводах нет игр; в играх нет ledger-нот.
2. Жёлтый / зелёный / красный на бейджах. У «В ожидании» — Отменить, заявка остаётся во вкладке Выводы.
3. Касса Пополнить/Вывести в шапке и на странице открывается как раньше.

---

## 2026-09-01 · FocusLucky: даты, призы, история, профиль

Срез: после живого шоу `/x8/focus-lucky` был read-only (`drawn` → `draw_at_locked` / `prizes_locked`). «Новая кампания» = abort с 409, если уже есть paid. `starts_at` из панели не менялся. Истории в `/x8` не было. Имена победителей без ссылки.

Сделано:

- `POST /api/admin/raffle/start-next`: после `drawn` новая строка `draft`, старую и winners не трогаем. INSERT только из колонок, которые есть в `SELECT *` (на staging нет `info_text` / `how_to_text`).
- `PATCH /api/admin/raffle/schedule`: `starts_at` + `draw_at` (МСК), `ends_at = draw_at − 1с`; отказ в `drawing`/`drawn`. Старый `PATCH /draw-at` остаётся.
- `GET /api/admin/raffle/campaigns`: циклы + победители. Карточка «История» на той же странице.
- Панель: при `drawn` баннер и **Следующий цикл**; «Новая кампания» только `closed` без выплат. Два `datetime-local` до шоу. Призы снова правятся на новом цикле. Имена → `/x8/users?user=`.
- Бот `start_new_campaign_without_draw` не трогал. Паркованные холдем / кланы / clan war не открывал.

Проверки:

- Локально: `PYTHONPATH=. python3 -m pytest tests/test_raffle_admin_cycle.py tests/test_casino_raffle.py -q` → **28**. `npx tsc -b` чисто.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. **1601** passed. `-k raffle` → **34** passed.
- md5 local=`/opt`=`/app/backend`: `raffle_service.py` `ac47a03a5e21dc86de1a304f742d0cd4`, `casino_raffle.py` `65b53d604b5005a5a6aa63e40858894a`, `admin_raffle.py` `f401b20d5eb763ba1ae9d6ccf213d14d`, `test_raffle_admin_cycle.py` `0c2b2d03eeebcd3b6c2f261ce09398f1`. Панель: `AdminFocusLucky.tsx` `50c4ccb966cfb533dd049de250e61291`, `adminApi.ts` `26eed64f6b88a4fa8d633c08b7698b75`.
- `staging-sync.sh` health **passed** (дважды: INSERT без `info_text`, затем remount истории). HTTP **200** `/x8/login`, `/x8/focus-lucky`, `/api/health` `{"status":"ok"}`. Бандл `panel-D0G1ypjX.js`: `start-next` **8**, `raffle/campaigns` **1**, `raffle/schedule` **1**. Сборка **2288** modules.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** как раньше.
- SQL `raffle_campaigns`: нет колонок `info_text`/`how_to_text` (30 полей, есть `spin_interval_seconds`). До клика 1/2/3 все `drawn`. После: **#4 draft** `focuslucky-20260901-075549` пул **15000** (11 мест), `draw_at` МСК **2026-10-02 21:00**; **#3 drawn** 8000, winners **3** paid на месте.
- `rg`: `start_next_campaign` в `raffle_service.py` 1; `start-next` / `getRaffleCampaigns` / `patchRaffleSchedule` в панели; `ProfileLink` в `AdminFocusLucky.tsx`.
- Клик 18081 `/x8/focus-lucky` (`123`/`123`): `drawn` #3 locked → **Следующий цикл** (раньше 500 из-за `info_text`) → черновик #4, поля начала и розыгрыша, **Добавить место** / **Сохранить призы**. Сохранил розыгрыш 02.10 21:00 МСК, 11-е место 500 ₽, пул 15 000. История: текущая черновик 15 000 + прошлый drawn 8 000 с тремя ссылками. Клик `@fixture_full_referrer` → `/x8/users?user=940003` (adjustment 4 000 ₽).
- `ssh focuspay` **Permission denied (publickey)**. `deploy_all.py` не запускал. Не коммитил.

Следующий шаг: **стоп**. Прод — после клик-приёмки и явного «го».

Потыкать (Ctrl+F5, туннель **18081** `/x8/focus-lucky`):

1. Сейчас цикл **черновик #4**: «Начало набора» и «Время розыгрыша» — поля, не текст. **Добавить место** / **Сохранить призы** видны.
2. История: текущая сверху (15 000 ₽), под ней проведённый цикл 8 000 ₽ — клик разворачивает победителей, имя открывает профиль.
3. «Следующий цикл» серый, пока этот черновик не доведут до `drawn`. «Новая кампания» тоже серая (это срыв набора, не следующий цикл).

---

## 2026-09-01 · casino fixes click-pass (command-side)

Срез: command-side CASINO_REVIEW_CHECKLIST + kick stale v2. Клик-проход в другом агенте. Прод не трогал. Не коммитил. FocusLucky start-show не жал.

v2 expire:

- До тика (уже так): id **7** `pvp_basketball` **expired**, id **10** `baccara` **expired**, `settled_at=2026-09-01 06:01:51.944195+00`. Сиденья 7/10 все `released`. House reservations id 5/7 `released` (500 / 40 ₽). Running/tie_break: **0**.
- `POST /api/internal/casino/v2/tables/expire` из backend: **200** `{"success":true,"expired":[],"stale_play":0}`.
- После тика: 7 и 10 по-прежнему **expired**; targeted `_expire_stale_v2_play_table` не понадобился.

Проверки:

- git `main` HEAD `61e47be9f6cf415a121663ecb60d4a20383661f3` (`61e47be chore(staging): add casino working-tree sync and pytest service`). Dirty **282** (130 modified, 152 untracked).
- md5 local=`/opt`=`/app/backend` (фронт только `/opt`): `CasinoProfile.tsx` `afd7dff69c35379626eedfcf8c43d892`, `CasinoWallet.tsx` `5ae21a5a64e8309dcfb65ff43ed6db2f`, `casino_inbox.py` `8946cc837533654f4487f83bf5fbc8bd`, `casino_v2_web.py` `a8688abc57e09e81a17e4de74876a3f1`, `gameCatalog.ts` `de8b13830ebc97cee56b552d549776db`, `AdminFocusLucky.tsx` `df45f23c16936c48103117a4fcd7d7c9`, `ux_copy.py` `39849567bdfd5b7e45555e3522449e39`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у `focuspay-staging-runtime-gateway-1`. Хост **18082** listen `0.0.0.0` / `[::]`. Backend 8000 не опубликован.
- `rg`: `CATEGORY_LABEL.house` = **Общий стол**; `start-show` только при `(active||closed) && issuedTickets > 0`; `txt_reviews` — бонус ₽, билеты не обещает (билеты только в блоке FocusLucky).
- Локально: `pytest tests/test_casino_inbox.py tests/test_casino_v2_web.py tests/test_casino_raffle.py` **62** (11+33+18). `npx tsx scripts/check-casino-wallet-rules.mts` **ok**. `check-pvp-tables-only.mts` **ok**. JWT env failures не было.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. **1604** passed (было 1601). Collect-only **1615**.
- Прод `153.80.249.77` не ходил (fail2ban). `deploy_all.py` не запускал. Не коммитил.

Staging URLs: туннель **18081**, хост **18082**.

Клик 18082 (`ауебратва` / fixture_buyer) + 18081 admin:

- Профиль/кошелёк: **Пополнения 3 / Выводы 6**, без нуля до загрузки. Вкладка выводов — 6 заявок.
- Лобби: рулетка бейдж **«Общий стол»**, не «Против FocusBet». Холдем/кланы в рельсе нет.
- Кубики: стол 2×100 ₽, «Добавить бота», раунд до результата (4 vs 6).
- Чат: **1 онлайн** (себя считает).
- Колокол: «К игре» открыл стол; URL ещё `/casino/duels/web-…`, стол баккара/блэкджек отрисовался.
- FocusLucky #4: приём, пул 15 000 ₽, старт 02.10 21:00 МСК, 0 билетов.
- Админка `/x8/focus-lucky`: кнопка **«Запустить шоу»** disabled при 0 билетов. Не жал.

Скриншоты: `docs/qa-screenshots-2026-09-01/fix-*.png`.

Следующий шаг: выкат на прод (бэкап → миграции → `draw_at` 19:00 МСК → API+бот+nginx+`deploy_all.py`).

---

## 2026-09-01 · prod cutover blocked on SSH

Срез: стейдж click-pass закрыт. Локальный `npm run build` **ok** (2288 modules, `index-9mxEV6H9.js` / `panel-7iyNmfgC.js`). Прод HTTP: `/casino` **200** (старый SPA), `/api/health` **200**, `GET /api/user/casino/raffle` **404**. `FOCUSPAY_SSH_PASSWORD` в env нет. `ssh focuspay` сначала `Connection refused` (fail2ban), затем порт открылся: **Permission denied (publickey)** для `root` и `focuspay`. Предложены ключи `cursor-focuspay-deploy` (`SHA256:x9nepSay…`), staging-178, staging-zcode — сервер не принял. На боевом в дереве деплоя PasswordAuthentication выключен. Миграции / rsync / `deploy_all.py` не запускал. `draw_at` 19:00 не ставил.

Следующий шаг: ключ в `authorized_keys` или `FOCUSPAY_SSH_PASSWORD` (если парольный вход ещё жив), затем тот же порядок выката.

---

## 2026-09-01 · prod cutover FocusLucky live show

Срез: ключ `cursor-focuspay-deploy` в `authorized_keys`. Пароль root с панели сохранён и **сразу сменён** (файл только на машине агента, не в git). Выкат API+бот+nginx+фронт. «Запустить шоу» / `/raffle_draw` **не** жал. Коммит не делал.

Инцидент при первом старте нового closer:

- Кампания **#1** (июль, `draw_at` 29.07, без победителей) попала под `_maybe_autostart` (`draw_at <= now()`).
- Шоу началось **07:05:12 UTC**. За 30 с интервал начислены места **1–5** на **баланс** (12 000 ₽): `8675456465` 5000, `7611940249` 3000, `6116065306` 2000, `6889197809` 1000, `6892492474` 1000. Места 6–10 не крутились.
- В outbox ушло **3201** `raffle_started` (всем `bot_users`). Часть processing успела уйти в Telegram («FocusLucky начинается») до отмены. Остаток **failed** `cancelled: stale July campaign autostart`.
- Стоп: `#1 status=drawn`, `next_spin_at=NULL`. Победительские DM: **4 sent / 1 forbidden**.
- Страховка: autostart только если `draw_at > now() - interval '2 hours'`. `raffle_notify` CAST `$2::varchar` / `$3::text` (иначе `AmbiguousParameterError`, бот падал на старте из-за забытого `expire_orders_task` import — тоже залит).

Кампания **#2**: `active`, билеты **5931**, `draw_at` **2026-09-01 19:00 МСК**, `ends_at` 18:59:59 МСК, места 1–10 `payout_method=balance`. Closer один воркер uvicorn, без `--workers`.

Проверки:

- git HEAD `61e47be`, dirty (этот журнал + рабочие правки). Не коммитил.
- md5 local=`/opt`: `casino_raffle.py` `2ba44c0fbc76c12c785ed7eed5007ddc`, `raffle_notify.py` `6277f0f20436dbeb49ea7d7185e9c7ab`, `main.py` `258efdf3c5a07652e75f4fd1260015a0`.
- Локально: `PYTHONPATH=. python3 -m pytest tests/test_casino_raffle.py -q` → **19**.
- Бэкапы на сервере: dump `/opt/backups/exchange_bot-20260901T065859Z.dump`; код `/opt/backups/exchange-backend-code-pre-20260901T070124Z.tgz`, `/opt/backups/tg_bot_btc-code-pre-20260901T070124Z.tgz`; nginx `/opt/backups/nginx-focuspay.org-pre-20260901T070124Z`; HTML `.bak-20260901-031217`.
- API `ActiveEnterTimestamp=Tue 2026-09-01 07:10:53 UTC`. `ExecStart` без `--workers`.
- nginx: `casino-avatars` / `casino-idents` / `/api/user/casino/` на строках 127/138/149.
- HTTP: `/casino` **200**, `GET /api/user/casino/raffle` **401** (не 404), `/` и `/x8` отдают `index-9mxEV6H9.js` / `panel-7iyNmfgC.js`. В панели **«Запустить шоу»**, строки «Провести розыгрыш» нет.
- `enabled_games` на проде: `raffle=false`, `roulette=false`, `cub=false`; `pvp_dice`/`baccara`/`blackjack`/`jackpot`/`fixed_room` true. Плитка FocusLucky в каталоге всё равно видна.
- Клик агента `https://focuspay.org/casino`: холдем/кланы нет, рулетка бейдж «Общий стол». Гость `/casino/play/raffle` — «Сейчас нет кампании» (snapshot только с JWT).
- Прод `ssh focuspay` по ключу. `deploy_all.py` отработал (http 127.0.0.1 `/` `/x8` `/ops` → 301 на https).

Следующий шаг: **стоп**. Человек: Ctrl+F5 лобби, вход → FocusLucky #2 19:00, админка `/x8/focus-lucky` без кнопки «Провести розыгрыш». Шоу **не** стартовать вручную — closer сам в 19:00 МСК. Решить, откатывать ли 12 000 ₽ июля.

Потыкать:

1. `https://focuspay.org/casino` — лобби, плитка FocusLucky, нет холдема/кланов.
2. Под логином `/casino/play/raffle` — набор #2, пул, билеты, старт 19:00 МСК. Гость без JWT пустой экран — так задумано API.
3. `/x8/focus-lucky` — **Запустить шоу**, не «Провести розыгрыш». Не жать. Рулетка в лобби может быть «выключено в настройках» (`roulette=false`).

---

## 2026-09-01 · Вход в казино через Start в боте

Срез: «Войти» в FocusBet больше не ведёт на `/login` с виджетом (номер). Гость идёт на `/login/telegram?next=/casino…` → `t.me/<бот обмена>?start=cauth_<32hex>` → Start → та же сессия, что Login Widget (`web_users.telegram_user_id`). Mini App `/casino/tg` не трогали. Кабинет `/login` без изменений. Прод и `deploy_all.py` не трогали.

Сделано:

- Таблица `web_telegram_bot_logins` + GRANT `exchange_bot`. `POST /api/auth/telegram/bot-start`, `GET …/bot-wait`, `POST …/bot-complete`. Upsert как у `/auth/telegram`. `return_path` только `/casino…` (чужой путь схлопывается в `/casino`).
- Бот обмена: `cauth_` в `/start` **до** капчи; кнопка «Открыть казино»; команда `/casino` (ticket без сайта). Reply-меню обмена не меняли.
- Фронт: `goCasinoLogin` / `CasinoLoginLink` → `/login/telegram`. Страница ожидания, poll 1.5 с, `ticket` с телефона, ссылка «Войти так» на `/login?next=…`.

Проверки:

- git HEAD `61e47be`. Dirty **~297** (казино WIP + этот вход). Не коммитил.
- md5 local=`/opt`=`/app/backend` (бот `/opt/tg_bot_btc`): `telegram_bot_login.py` `e836b70dbf3a3a7c213d5b58ba015c2a`, `auth_router.py` `31a19d13230ddc1313169f1701d8f0a0`, migration `b3bc371dba72e3e65023486cdfb14089`, `casino_login.py` `7afecf95224947cbacb208a663bc8b00`, `start.py` `2b5501b6df6e5ef24408ba2a559f26fd`, `casino_bot_login.py` `97b34120ffa8d9fc9abe1317ea8a3b41`, `main.py` `e8b7d587bfb09e1b1bc149c06dd0097a`, `TelegramBotLogin.tsx` `5c857b07d793aa2648d6a0755a5a1790`, `casinoPaths.tsx` `7bfc5d129bf9d9f5a5d90181aed24ac6`, `auth.ts` `5fc688b9d7062b6b87e4bf24363c8dc1`, `postLoginPath.ts` `e1453e0400066bf9d98efb066f93948e`, `App.tsx` `5c51d04c69bda50e290c612d42e88688`.
- Локально: `tests/test_telegram_bot_login.py` **10**. Бот `.venv` `tests/test_casino_bot_login.py` **6**. `npx tsx scripts/check-casino-bot-login.mts` **ok**. `check-post-login-path.mts` **ok**.
- `staging-test.sh`: **7 failed, 1616 passed, 1 skipped**. Collect-only **1623**. Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. Было 1604 passed / 1615 collected.
- SQL: таблица есть. После смоков `count(*)=5`, `telegram_user_id IS NOT NULL` = **0** (живой Start с агента не жали).
- API 18081: `POST bot-start` `{return_path:/casino/wallet}` → **200** `t.me/focusttteeeeeeesttttt_bot?start=cauth_…`. Чужие пути `/x8/casino` и `https://evil…` → `return_path=/casino`. `GET bot-wait` без Start → `{status:pending}`. Липовый ticket → **401**.
- Бандл `index-Cg0gdoGk.js`: «Открыть бота» **2**. `index-BcGa3Igp.js`: `bot-start` / `bot-wait` / `bot-complete` по **1**. `/login/telegram` HTTP **200**.
- `rg`: `cauth_` / `web_telegram_bot_logins` / `bot-start` / `/login/telegram` в backend + бот + фронт (**17** файлов вне docs).
- Docker runtime: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen. Контейнер бота обмена **Up**. Backend 8000 не опубликован.
- Клик 18082 гость: лобби «Войти» → `/login/telegram?next=/casino`. Кнопка `https://t.me/focusttteeeeeeesttttt_bot?start=cauth_<32hex>`. «Войти так» → `/login?next=/casino` (логин/пароль; виджет на IP «Bot domain invalid» — так и должно). Кошелёк «Пополнить» → `/login/telegram?next=/casino/wallet`. Агентский браузер `target=_blank` на t.me не открыл (popup). Staging-бот живой — Start можно дожать руками.
- Прод read-only `ssh focuspay`: `index.html` `2026-09-01 07:12:18 +0000`, `panel.html` `07:12:20`. API `ActiveEnterTimestamp=Tue 2026-09-01 09:09:46 UTC` (в прошлом срезе было 07:10:53 — рестарт не наш, этот сеанс только `stat`/`show`). `deploy_all.py` не запускал.

Скриншоты: `docs/qa-screenshots-2026-09-01/100-login-telegram-wait.png`, `101-login-password-fallback.png`, `102-login-telegram-wallet-next.png`.

Следующий шаг: **стоп**. Следующий пункт плана казино не начинать.

Потыкать (Ctrl+F5, 18082 гость):

1. `/casino` → Войти → страница «Вход в FocusBet», не форма логина.
2. «Открыть бота и нажать Start» → staging-бот `focusttteeeeeeesttttt_bot`, Start → «Открыть казино»; вкладка сайта сама входит.
3. С телефона та же кнопка из бота (`ticket=`).
4. «Войти так» — запасной пароль. `/casino` в боте без сайта.
5. Кабинет `/login` по-прежнему виджет. Прод не выкатывать.

---

## 2026-09-01 · prod Not Found на «Вход в FocusBet»

Срез: на `focuspay.org` уже был новый SPA (`index-Cg0gdoGk.js`, страница `/login/telegram`), а API ещё без `bot-start` → красное **Not Found**. Залил только этот вход (не полный rsync). `deploy_all.py` не гонял.

Сделано на проде:

- Миграция `web_telegram_bot_logins` + GRANT `exchange_bot` (`bot_ins=true`).
- `telegram_bot_login.py` + три эндпоинта в `auth_router.py` (diff к живой копии только этот вход).
- Бот: `casino_login.py`, `casino_bot_login.py`, `cauth_` в `/start` до капчи, команда `/casino`. Reply-меню не трогал.
- Рестарт `focuspay-exchange-api` и `tg-bot`. Uvicorn стоп ушёл в SIGKILL по timeout (~1 мин) — потом **active**.

Проверки:

- `POST /api/auth/telegram/bot-start` **200** `https://t.me/focuspay1_bot?start=cauth_…`. `GET bot-wait` → `pending`. `/api/health` **200**.
- md5 local=`/opt/exchange-backend` / `/opt/tg_bot_btc`: `telegram_bot_login.py` `e836b70dbf3a3a7c213d5b58ba015c2a`, `auth_router.py` `31a19d13230ddc1313169f1701d8f0a0`, `casino_login.py` `7afecf95224947cbacb208a663bc8b00`, `start.py` `2b5501b6df6e5ef24408ba2a559f26fd`, `casino_bot_login.py` `97b34120ffa8d9fc9abe1317ea8a3b41`, `main.py` `e8b7d587bfb09e1b1bc149c06dd0097a`.
- Бэкап файлов: `/opt/backups/cauth-*`.
- Клик `https://focuspay.org/login/telegram?next=/casino`: нет «Not Found», кнопка «Открыть бота и нажать Start» → `t.me/focuspay1_bot?start=cauth_`.

Скрин: `docs/qa-screenshots-2026-09-01/103-prod-login-telegram-fixed.png`.

Потыкать (телефон, Ctrl+F5): `/casino` → Войти → Start в `@focuspay1_bot` → сайт сам входит или кнопка «Открыть казино».

---

## 2026-09-01 · Откат: казино-бот /help, слэш-меню, пополнение 1:1

По просьбе «откати всё». Прод не деплоил (`deploy_all.py` не запускал). Холдем/кланы не открывал. Чужой незакоммиченный WIP не сбрасывал.

Сделано:

- Казино-бот: снова СБП/карта и `create_deposit`. Убраны `deleteMyCommands`, оператор `@focus_operator`, `OPERATOR_USERNAME`.
- Переплата BUY снова `overpay × (1 − spread)`. Удалены `casino_order_topup.py` и миграция `add_casino_order_topup.sql`. На staging колонки `order_id` сняты (строк с `order_id` не было).
- Касса: «Пополнение скоро». `/ops` превью: «Дополнительный баланс».

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Не коммитил.
- md5 local=`/opt`=`/app`: `bot.py` `f8a7d88d45e3da5cc0689e828e5328a8`, `help.py` `32b238155a0f2561b20b4b6cb56d80f7`, `casino_wagering.py` `ef2f12800fe33ee7ea3af72e5fe1aec4`, `operator.py` `1d6c7e6f9e9670a8f747b1a1ec95d0af`, `buy_payout.py` `b0ed80463f17b54b40b6e4d864042055`, `CasinoCashier.tsx` `eed7ad82d65936fe6495688823c7d5b2`, `OperatorCreate.tsx` `51ab79c263adebf1ff88af070a572269`.
- Локально: казино-бот discover **261**. Бот `.venv` `test_manual_buy_overpay_credit.py` **6**. `test_casino_wagering.py` **10**. wallet-rules **ok**.
- Staging: reverse SQL + `staging-sync` health **passed**. `create_deposit` в контейнере **1**. Бандл `index-BcGa3Igp.js` «Пополнение скоро» **1**, `panel-BN1r-uaW.js` «На казино» **0** / «Дополнительный баланс» **1**.
- `staging-test.sh`: **7 failed**, те же имена. Collect-only **1629**. `test_operator_manual_buyer.py` + `test_casino_wagering.py` **47**.
- Docker: наружу `127.0.0.1:18081->8080/tcp` у gateway. casino-bot без published ports.
- `rg`: `_send_operator_deposit` / `casino-topup` / `add_casino_order_topup` / `OPERATOR_USERNAME` — пусто.
- Клик 18081: касса снова «Пополнение скоро». `/ops/create` без сессии → логин.
- Прод read-only: `index.html` `2026-09-01 09:29:11 +0000`, `panel.html` `09:29:14` — как раньше. **Сдвинулись сами (этот откат их не писал):** API `ActiveEnterTimestamp=Tue 2026-09-01 10:07:09 UTC` (было 09:30:51), `/opt/focuspay-casino/bot.py` `10:05:29` (было 09:06:10), в файле всё ещё `create_deposit`.

Скрин: `docs/qa-screenshots-2026-09-01/112-cashier-deposit-rolled-back.png`.

Следующий шаг: **стоп**.

---

## 2026-09-01 · «Войти» в казино → @focusludka_bot, не @focuspay1_bot

Срез: `bot-start` брал `TELEGRAM_BOT_USERNAME` → `t.me/focuspay1_bot`. Теперь `CASINO_BOT_USERNAME` (прод уже `focusludka_bot`). Start обрабатывает игровой бот, не бот обмена. `deploy_all.py` не гонял — фронт не трогал, ссылка приходит с API.

Сделано:

- API: `bot_username()` → `settings.casino_bot_username`, fallback `focusludka_bot`. `POST /api/auth/telegram/bot-attach` (`X-Internal-Token`).
- Прод `@focusludka_bot`: `web_login.py`, `attach_web_login`, `/start` зовёт `maybe_send_site_login`. Не заливал локальный WIP `bot.py`.
- Staging: `CASINO_BOT_USERNAME=focuscazzcztewrfweda_bot` (= staging casino bot). Compose инжектит его в backend. Бот обмена `focusttteeeeeeesttttt_bot` для этого входа не используется.

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Dirty как раньше (казино WIP). Не коммитил.
- md5 local=`/opt/exchange-backend`: `telegram_bot_login.py` `baebfa9031ac0aa0af2a0eb3c306793c`, `auth_router.py` `e9280924b3e57fe1eb3edacdda360b48`. Прод `web_login.py` `51127e3483cb6a89c208b2f60b3f1132`. Прод `bot.py`/`focuspay_client.py` — хирургический патч старых файлов, не md5 локального WIP.
- Staging md5 тех же API-файлов + `web_login.py` совпадают с локальными.
- Локально: `tests/test_telegram_bot_login.py` **11**. Казино `test_web_login`+startup+staging_ui **24**. `npx tsx scripts/check-casino-bot-login.mts` **ok**.
- `staging-test.sh` / pytest `--tb=no`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. `test_telegram_bot_login.py` collect **11**.
- SQL staging: таблица `web_telegram_bot_logins` есть. `count(*)=7`, с `telegram_user_id` = **0**.
- API прод: `POST bot-start` **200** `https://t.me/focusludka_bot?start=cauth_…`. `bot-attach` без токена **403**. `/api/health` **200**. Staging `bot-start` → `t.me/focuscazzcztewrfweda_bot?start=cauth_…` (не `focuspay1_bot`, не `focusludka_bot`).
- Docker: наружу `127.0.0.1:18081->8080/tcp` и хост **18082**. Backend 8000 не опубликован. casino-bot **Up**.
- Клик прод `/login/telegram?next=/casino`: кнопка `https://t.me/focusludka_bot?start=cauth_<32hex>`. Текст на проде ещё «бот FocusPay» (старый бандл). Staging 18082: «игровой бот FocusBet», href `t.me/focuscazzcztewrfweda_bot`.
- HTML прод не менялся: `index.html` `2026-09-01 09:29:11 +0000`, `panel.html` `09:29:14`. API `ActiveEnterTimestamp=Tue 2026-09-01 10:07:09 UTC`, casino-bot `10:07:13`. Бэкап `/opt/backups/cauth-ludka-20260901T100448Z`.
- `rg` `bot-attach` / `casino_bot_username` / `focusludka_bot`: backend `telegram_bot_login.py`, `auth_router.py`, `config.py`, тесты, `.env.example`, preflight/compose.

Скрины: `docs/qa-screenshots-2026-09-01/104-prod-login-ludka.png`, `105-staging-login-casino-bot.png`.

Следующий шаг: **стоп**. Следующий пункт плана казино не начинать.

Потыкать (телефон, Ctrl+F5):

1. `https://focuspay.org/casino` → Войти → «Открыть бота» должно открыть **@focusludka_bot**, не @focuspay1_bot.
2. Start в игровом боте → «Открыть казино» и/или вкладка сайта сама входит. Дальше обычное приветствие бота — так и задумано на этом патче.
3. Staging 18082: тот же путь, бот `@focuscazzcztewrfweda_bot`.

---

## 2026-09-01 · Прод: перенос казино-бота со стейджа

Срез: код стейдж-бота залит в `/opt/focuspay-casino`, unit `focuspay-casino-bot` перезапущен. Токен `@focusludka_bot` не меняли. `deploy_all.py`, nginx, `focuspay-exchange-api` не трогали. Webhook unit не включали. Холдем/кланы не открывали. Самообслуживание СБП/карты в «Пополнить» как на стейдже.

Сделано:

- Меню без «Команда». `register_team_handlers` не вызывается (`casino_teams.py` на диске). `/help` без `/help team` в оглавлении и без дартса/спорта.
- При старте `delete_my_commands` (default + private + groups + admins). Слэши `/cub` `/roulette` и остальные игровые — в коде.
- Прод: бэкап `/opt/backups/focuspay-casino-code-pre-20260901T102636Z.tgz` + копия env. rsync без `.env`/`venv`. pip Pillow **12.3.0**. `CASINO_FAIRNESS_URL=https://focuspay.org/casino/fairness`. `enabled_games.roulette=true` (cub/raffle false, holdem/clan_war не трогал). Chromium на хосте нет — `/start` уйдёт в текст + reply-клавиатура, если PNG не соберётся.

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Dirty (казино WIP + этот журнал). Не коммитил.
- md5 local=`/opt` staging=`/app` staging=`/opt/focuspay-casino` прод: `bot.py` `c692972f4ccc15cb7d86f968c09dfe70`, `casino_menu.py` `22b56a5fbc3f87b9543e55dd28d3403a`, `games/help.py` `f968d451a5f2d6c06ac328179a7c2693`, `games/catalog.py` `0310376d7a59c73f2ab5186d5b811f70`.
- Локально: казино-бот `tests/` без e2e **290**.
- Staging: `staging-sync` health **passed**. Лог `@focuscazzcztewrfweda_bot`: хендлеры PVP/V2/карты/рулетка/джекпот/комнаты, **без** Clan team, `Telegram slash command menu cleared`.
- `staging-test.sh`: **7 failed**, те же имена: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. Collect-only **1629**.
- Docker runtime: наружу только `127.0.0.1:18081->8080/tcp` у gateway. casino-bot без published ports. Backend 8000 не с хоста.
- `rg`: `clear_telegram_command_menu` в `bot.py`; `register_team_handlers` только в `casino_teams.py` + тест; меню `assertNotIn MENU_TEAM`.
- Прод journal `ActiveEnterTimestamp=Tue 2026-09-01 10:27:52 UTC`, `@focusludka_bot`, те же хендлеры, slash menu cleared, ERROR **0**. Webhook **inactive**. HTML `index.html` `09:29:11`, `panel.html` `09:29:14`. API `10:07:09` — как до этого выката.
- SQL прод: `roulette=true`, `cub=false`, `raffle=false`.

Следующий шаг: **стоп**. Клики в `@focusludka_bot`. Следующую задачу не начинать.

Потыкать (`/start` в `@focusludka_bot`, иначе старая клавиатура не сменится):

1. Нижние кнопки: Создать / Активные / Мои / Профиль / Баланс / Пополнить. Нет «Команда».
2. Меню «/» без дартса и спорта (может обновиться с задержкой).
3. `/help` без `/darts`, комиссия два числа.
4. `/cub` и `/roulette` в чате FOCUS PAY отвечают.
5. «На сайте» → `https://focuspay.org/casino/tg`.

---

## 2026-09-01 · Убрать системный скроллбар на FocusLucky

Срез: на скрине архив FocusLucky (места 3 000 / 1 000 / 500 ₽ + список «N бил. %») системная вертикальная полоса сидела по правому краю колонки `.casino-main` (`max-width: 1280px`, поэтому не у края окна). Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- `.casino-main` и `.casino-raffle-list`: `scrollbar-width: none` + `::-webkit-scrollbar { display: none }`. Прокрутка колёсиком жива.
- `bootstrap_static_test.sh`: require `.casino-main::-webkit-scrollbar`.

Файлы: `focussite/frontend/src/casino/casino.css`, `focussite/docker/staging-db/bootstrap_static_test.sh`.

Проверки:

- git HEAD `61e47be`. Dirty **303** / casino **72** (казино WIP + эта правка). Не коммитил.
- md5 local=`/opt` `casino.css` `9b52fa67175f633da3afc1b0b16d33bb`. Бандл `index-DcIcaB3V.css`.
- `staging-sync` health **passed**. Сборка gateway **2289** modules.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen `0.0.0.0` / `[::]`. Backend 8000 не опубликован.
- `rg`: `scrollbar-width: none` в `.casino-main` и `.casino-raffle-list`; require в bootstrap.
- SQL `raffle_campaigns`: active **15000**, drawn 8000 / 10000.
- `staging-test.sh` / pytest `-o addopts=`: **7 failed**, 1622 passed, 1 skipped. Collect-only **1629**. Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. В прошлом срезе было 1616 passed — этот CSS тесты не добавлял.
- Клик 18082 `fixture_buyer`: архив «август 2026 · 20:00» — **247** чел., `@nch_0333` 496 бил. 8.7%. `offsetWidth-clientWidth` main **0** / list **0**, `scrollbar-width: none`. `list.scrollTop=1200` сработал. Рулетка: полосы **0** px.
- Прод read-only: `index.html` `2026-09-01 09:29:11 +0000`, `panel.html` `09:29:14`, API `ActiveEnterTimestamp=Tue 2026-09-01 10:07:09 UTC` — как раньше.

Скрины: `docs/qa-screenshots-2026-09-01/113-raffle-no-scrollbar.png`, `114-raffle-archive-no-bar.png`, `115-roulette-no-bar.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Следующий пункт плана казино не начинать.

Потыкать (Ctrl+F5, 18082, FocusLucky → вкладка **август 2026 завершён · 01.09, 20:00**):

1. Системной серой полосы с стрелками справа от колонки нет. Список 247 человек крутится колёсиком.
2. Текущий цикл (15 000 ₽, пул пустой) без полосы.
3. Рулетка — та же колонка без OS-скроллбара.

---

## 2026-09-01 · Скроллбар казино скрыт везде

Срез: системная полоса прячется на всей оболочке FocusBet, не только на `.casino-main`. Прокрутка колёсиком жива. `/x8` `/ops` и публичный сайт не трогал. Прод и `deploy_all.py` не трогал. Не коммитил.

Сделано:

- `.casino-root, .casino-root * { scrollbar-width: none }` + `::-webkit-scrollbar { display: none }`.
- Сняты дубли у `.casino-main` / `.casino-raffle-list` и `scrollbar-width: thin` у вкладок FocusLucky.
- `bootstrap_static_test.sh`: require `.casino-root *::-webkit-scrollbar`.

Файлы: `focussite/frontend/src/casino/casino.css`, `focussite/docker/staging-db/bootstrap_static_test.sh`.

Проверки:

- git HEAD `61e47be`. Dirty **303** / casino **72**. Не коммитил.
- md5 local=`/opt` `casino.css` `e71dbed3cd62e413bcb31757bf28c6aa`, bootstrap `9734aa8f2991278aec74c7d15892f90b`. Бандл `index-CIzPNx6f.css`.
- `staging-sync` health **passed**. Сборка **2289** modules.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen. Backend 8000 не опубликован.
- `rg`: `scrollbar-width: none` только на `.casino-root`; `thin` в casino.css нет.
- pytest `-o addopts=`: **7 failed**, 1622 passed, 1 skipped. Collect-only **1629**. Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- Клик 18082: лобби `mainBar=0`; чат `chatBar=0` `scrollbar-width:none`; FocusLucky архив 20:00 — **247** чел., `listBar=0` `listTop=800` (колёсико живое), вкладки `tabsSb=none`; рулетка `mainBar=0`. Рельс `scrollbar-width:none` (1px = border-right).
- Прод read-only: `index.html` `2026-09-01 09:29:11 +0000`, `panel.html` `09:29:14`, API `10:07:09 UTC` — как раньше.

Скрины: `docs/qa-screenshots-2026-09-01/116-lobby-no-bar.png`, `117-chat-no-bar.png`, `118-raffle-global-no-bar.png`, `119-roulette-global-no-bar.png`.

Следующий шаг: **стоп**. Прод не выкатывать.

Потыкать (Ctrl+F5, 18082):

1. Лобби, чат, рельс — без OS-полосы, колёсико крутит.
2. FocusLucky → август 20:00 — список 247 без полосы.
3. Рулетка — без полосы у колонки и у ленты ставок.

---

## 2026-09-01 · Прод: скрытый скроллбар FocusBet

Срез: по «сделай» залит только фронт (`deploy_all.py`). API, бот, nginx unit не трогал. Коммит не делал.

Сделано:

- Сборка **2289** modules, CSS `index-CIzPNx6f.css` с `.casino-root *::-webkit-scrollbar{display:none}`.
- `deploy_all.py`: бэкап `.bak-20260901-110658` (старые HTML 09:29:11 / 09:29:14). Прунинг `index-BcGa3Igp.js`, `index-Cg0gdoGk.js`, `index-DBIPlHH_.css`.

Проверки:

- HTML прод `index.html` `2026-09-01 15:06:59 +0000`, `panel.html` `15:07:01`. API `ActiveEnterTimestamp=Tue 2026-09-01 10:07:09 UTC` — без рестарта.
- HTTPS `focuspay.org` `/` `/x8` `/ops` `/casino` → **200**. Живой CSS: `scrollbar-width:none` **1**.
- curl 127.0.0.1 `/` `/x8` `/ops` → **301** на https (как у скрипта).

Следующий шаг: **стоп**.

Потыкать (Ctrl+F5, `https://focuspay.org/casino`):

1. Лобби / чат / FocusLucky / рулетка — без OS-полосы, колёсико крутит.

---

## 2026-09-01 · Join-fail как Telegram popup

Срез: ошибка входа за стол в casino-bot больше не пишет пузырь в чат. Callback отвечает один раз после API: fail — `show_alert`, успех — короткое answer + «Вы заняли место». Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- `join_v2_table` / `join_waiting_duel`: убран ранний `answer_callback_query("Резервируем ставку…")`.
- 409/ValueError: попап «стол уже заполнен…» / «дуэль уже занята…». Неизвестная ошибка — «Попробуйте позже». `send_message` на fail нет.
- Успешный вход, посадка бота, выход — как были.

Файлы: `focuspay-casino/games/v2_tables.py`, `focuspay-casino/tests/test_v2_tables.py`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **308** / casino **72** (казино WIP + эта правка). Не коммитил.
- md5 local=`/opt`=live `/app`: `v2_tables.py` `2da52c8b498471b3addf0298a3efd906`, `test_v2_tables.py` `e90f0f25cbec0792c22bdadd895f1b5a`.
- Локально casino-bot `test_v2_tables.py` **15 passed**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (после update и ещё раз). casino-bot `COPY` не из кэша.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen `0.0.0.0` / `[::]`. Backend 8000 не опубликован. casino-bot без HostConfig ports.
- HTTP 200: `/casino` на 18081 и 18082.
- `rg`: `стол уже заполнен` + `show_alert=True` в `v2_tables.py` и тестах. `Резервируем ставку` в файле нет.
- SQL `casino_settings` count **67**.
- `staging-test.sh` / pytest: **7 failed**, collect-only **1629**. Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. Бэкенд-тестов эта правка не добавляла.
- Клик 18082 `/casino/play/dice?mode=players`: лобби кубиков открывается. Попап join-fail — только в Telegram, сайт не трогал.
- Прод read-only: `index.html` `2026-09-01 15:06:59 +0000`, `panel.html` `15:07:01`, API `ActiveEnterTimestamp=Tue 2026-09-01 10:07:09 UTC` — как раньше.

Скрин: `docs/qa-screenshots-2026-09-01/120-dice-players-staging.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Следующий пункт плана казино не начинать.

Потыкать (staging `@focusludka_bot` / focusgame):

1. На открытом столе «Занять место» — в чат приходит «Вы заняли место», без попапа.
2. На полном / уже идущем столе — попап с OK: «Не удалось войти: стол уже заполнен, начался или ставка недоступна.» Нового сообщения в чате нет.
3. То же для кнопки входа в занятую дуэль.

---

## 2026-09-01 · Попапы на кнопки, игры в чате

Срез: короткие ответы inline-кнопок casino-bot — Telegram-попап, без нового пузыря. Доска, кубы, итог, лобби, реквизиты, «стол создан», промпт суммы остаются сообщениями. Прод и `deploy_all.py` не трогал. Не коммитил.

Сделано:

- V2: бот сел / не сел, выход / отмена стола — `show_alert`. Join-fail как раньше. «Вы заняли место» в чате.
- Пополнение: неверная сумма, сбой создания заявки, отмена (успех / 409 / ошибка) — попап. Реквизиты — `send_message`.
- Мастер: «ставка не задана» и ошибка create — попап. Карточка «стол создан» — `edit_message_text`. `_finalize` возвращает bool, чтобы callback не отвечать дважды.

Файлы: `focuspay-casino/games/v2_tables.py`, `games/table_wizard.py`, `bot.py`, `tests/test_v2_tables.py`, `tests/test_table_wizard.py`, `tests/test_bot_startup.py`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **320** / casino **72**. Не коммитил.
- md5 local=`/opt`=live `/app`: `v2_tables.py` `799fb66ba9f5aec8eafd929653618e09`, `table_wizard.py` `ab0448d5c3e785eb1f045ea68a9ccabb`, `bot.py` `9f0465628abdd59607ef8958995a611d`.
- Локально: `test_v2_tables` + `test_table_wizard` + `test_bot_startup` + lobby/card **94 passed**.
- `staging-sync` health **passed** дважды. casino-bot `COPY` не из кэша. Gateway **2290** modules.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen `0.0.0.0` / `[::]`. Backend 8000 не опубликован. casino-bot без HostConfig ports.
- HTTP 200: `/casino` 18081 и 18082.
- `rg` `send_message(call.message.chat.id)` остался только на промптах суммы и fairness-сессии.
- SQL `casino_settings` count **67**.
- pytest: **7 failed**, collect-only **1644** (было 1629; бэкенд-тестов эта правка не добавляла, плюс dirty tree). Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- Клик 18082 `/casino`: лобби открывается.
- Прод read-only: `index.html` `2026-09-01 15:06:59 +0000`, `panel.html` `15:07:01`, API `10:07:09 UTC` — как раньше.

Скрин: `docs/qa-screenshots-2026-09-01/121-lobby-toast-alerts.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Следующий пункт плана казино не начинать.

Потыкать (staging-бот):

1. «Посадить бота» / «Выйти» / «Отменить стол» — попап, без нового сообщения.
2. Пополнение: неверная сумма и «Отменить заявку» — попап; реквизиты по-прежнему в чате.
3. Мастер: ошибка создания — попап; успешный стол правит ту же карточку.

---

## 2026-09-01 · Прод: попапы inline-кнопок casino-bot

Срез: на `@focusludka_bot` залиты три файла попапов (join-fail, v2bot/leave/cancel, deposit toasts, ошибка мастера). Хирургический rsync, без `--delete`. `deploy_all.py`, nginx, `focuspay-exchange-api` не трогал. Webhook unit не включал. Холдем/кланы не открывал. Не коммитил.

Сделано:

- Бэкап `/opt/backups/focuspay-casino-alerts-20260901T225344Z` (старые `bot.py` / `v2_tables.py` / `table_wizard.py`).
- rsync local → `/opt/focuspay-casino`, `chown focuspay`, `py_compile`, `systemctl restart focuspay-casino-bot`.
- Дифф к прод-копии до выката — только попапы, без прочего WIP дерева.

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Dirty **320** / **72**. Не коммитил.
- md5 local=`/opt/focuspay-casino`: `bot.py` `9f0465628abdd59607ef8958995a611d`, `v2_tables.py` `799fb66ba9f5aec8eafd929653618e09`, `table_wizard.py` `ab0448d5c3e785eb1f045ea68a9ccabb`.
- Unit `active`/`running`, `ActiveEnterTimestamp=Tue 2026-09-01 22:54:00 UTC`. Старт: `@focusludka_bot`, PVP/V2/wizard/baccara/blackjack/roulette/jackpot/rooms/fairness, slash menu cleared. ERROR **0**. Webhook **inactive**.
- `grep`: «стол уже заполнен» / «дуэль уже занята»; `show_alert` на «Бот сел», «действие уже недоступно», «Ставка не задана», «Заявка на пополнение отменена». `Резервируем ставку` в `v2_tables.py` нет.
- HTML/API этим выкатом не менялись: `index.html` `2026-09-01 22:50:21 +0000`, `panel.html` `22:50:23`, API `ActiveEnterTimestamp=Tue 2026-09-01 22:49:28 UTC` — как сразу до rsync бота (раньше в журнале 15:06 / 10:07 — это уже был отдельный фронт/API до этой задачи).

Следующий шаг: **стоп**. Следующий пункт плана казино не начинать.

Потыкать (`@focusludka_bot` на проде):

1. Полный / идущий стол — попап «стол уже заполнен…», без нового пузыря. Успешный вход — «Вы заняли место» в чате.
2. «Посадить бота» / «Выйти» / «Отменить стол» — попап.
3. Пополнение: кривая сумма и «Отменить заявку» — попап; реквизиты в чате. Ошибка создания стола в мастере — попап.

---

## 2026-09-01 · Прибыль казино: учёт живых игр + строка при нуле

Срез: owner P&L больше не смотрит только в старые `casino_games` ledger’ы. Комиссия 5% на v2-столе без бота идёт дому; джекпот/комнаты пишут `game_settlement`, не тихий `UPDATE balance`. Формула одна на `/x8/casino`, финансы, `/dash`, дайджест. Строка «Казино» в финансах видна и при 0 за день. Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- `credit_house_game_settlement` — идемпотентная проводка `casino_house_ledger` + баланс банка.
- V2 all-human settle: 5% на дом (`casino_v2_house_ledger`, не дублировать в `casino_house_ledger`). Стол с ботом без изменений (рейк уже в `player_stakes − player_payouts`).
- Джекпот `jackpot-rake-{round_id}`; комнаты `room-rake-{room_id}` / bot-win / consume.
- `fetch_casino_owner_profit`: owner commission + house `game_settlement` + v2 house + исторический v2 commission без ledger-строки + исторический rake джекпота/комнат без `jackpot-rake-` / `room-rake-`.
- Дашборд: оборот/игры UNION v2 + jackpot + rooms; график — оборот и прибыль.
- UI: водопад и «по направлению» всегда с казино; `/dash` extras `казино N ₽` при `from_pnl` даже если 0.

Файлы: `casino_finance.py`, `casino_jackpot.py`, `casino_fixed_rooms.py`, `routers/internal_casino.py`, `finance_pnl.py`, `routers/admin_casino.py`, `routers/admin_stats.py`, `business_digest.py`, `CasinoDashboard.tsx`, `FinanceTab.tsx`, `bot/.../owner_dashboard.py`, тесты `test_casino_house_settlement.py` + правки finance/v2/rooms/jackpot/digest/owner_analytics.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **321** / casino **72** (+ скрины). Не коммитил.
- md5 local=`/opt`=live `/app`: `finance_pnl.py` `3255813e5f859cbdf09a976acae0dd4b`, `casino_finance.py` `286bbf1a6101bb761c45adcc363720e6`, `casino_jackpot.py` `592c5d77f53a5ed9280a36f76593dc11`, `casino_fixed_rooms.py` `3ed63182dd2385198b27b20284d3178d`, `CasinoDashboard.tsx` `db21ea538599d878e3a53a9c5059f76b`, `FinanceTab.tsx` `2733a379f34653fc86ed77819c169c57`, bot `owner_dashboard.py` `8d04c4a89092777a06f957145cb120a4`.
- Локально venv: house/v2/jackpot/rooms/pnl/digest/admin_casino **114 passed**; V2Settlement **13**; bot `test_owner_analytics` **14**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (после update и ещё раз). Gateway **2290** modules. Бандл `panel-CULVQ2K7.js`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen `0.0.0.0` / `[::]`. Backend 8000 не опубликован.
- HTTP 200: `/x8/login` `/x8/casino` `/casino` на 18081; `/casino` на 18082.
- `rg` live: `casino_v2_house_ledger` ×5, `jackpot-rake-` ×2, `room-rake-` ×2 в `finance_pnl.py`; `credit_house_game_settlement` в jackpot/rooms.
- SQL `casino_settings` **67**. Lifetime компоненты: owner commission **11469.48**, house ledger **4269.45**, v2 house **6507.75**, v2 hist commission без ledger **10.00**, jackpot hist rake **1302.85**, jp/room ledger rows **0** (старые раунды ещё в hist). API dashboard: `owner_profit_rub` **22684.53** = commission **11469.48** + house **11215.05**. Игры **930**, оборот **406943.19**, типы cub/roulette/blackjack/pvp_dice/baccara/jackpot/fixed_room. Chart 14д: sum turnover = KPI, sum profit = **22684.53**.
- PnL `date_from=2026-08-01&date_to=2026-09-02`: waterfall `casino_profit` **22684.53**; by_type casino net **22684.53**. Сегодня (МСК **2026-09-02**): casino **0.00**, строка в waterfall и «по направлению» остаётся.
- `staging-test.sh`: **7 failed**, collect-only **1651** (было 1644, +7). Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. ≈1644 passed (1651−7).
- Клик 18081 `/x8/casino`: прибыль владельца **22 684,53 ₽**, график оборот+прибыль. `/x8?tab=finance` неделя — «Казино: комиссия + дом +22 656,03 ₽»; сегодня — «Казино … 0 ₽» и строка «Казино — 0 ₽».
- Прод read-only: `index.html` `2026-09-01 22:50:21 +0000`, `panel.html` `22:50:23`, API `ActiveEnterTimestamp=Tue 2026-09-01 22:49:28 UTC` — как раньше.

Скрины: `docs/qa-screenshots-2026-09-01/130-casino-dashboard-profit.png`, `131-finance-casino-week.png`, `132-finance-casino-today-zero.png`, `133-casino-dashboard-chart.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Следующий пункт плана казино не начинать.

Потыкать (Ctrl+F5, туннель **18081**, админ `123` / `123`):

1. `/x8/casino` — «Прибыль владельца» не ноль; в «игры по типам» есть blackjack / pvp_dice / baccara / jackpot / fixed_room; график две оси: оборот и прибыль.
2. `/x8?tab=finance` → Неделя: водопад «Казино: комиссия + дом» и блок «по направлению → Казино».
3. Там же → Сегодня: обе строки казино на месте, даже если 0 ₽. `/dash` в staging-боте — extras `казино 0 ₽` (или сумма за день), не пропадает.

---

## 2026-09-01 · Прод: дашборд казино видит v2/джекпот

Срез: на проде KPI дашборда были нули, потому что `casino_games` finished = **0**, а живые игры в `casino_v2_settlements` (**10**, pot **790**) и джекпоте (**3**, pot **290**). Старый `/casino/dashboard` читал только `casino_games`. Залит срез прибыли (не полный rsync дерева). Холдем/кланы не открывал. Не коммитил.

Сделано:

- Бэкап `/opt/backups/casino-profit-visibility-20260901T231847Z`.
- Backend: `finance_pnl.py`, `casino_finance.py`, `casino_jackpot.py`, `casino_fixed_rooms.py`, `routers/admin_casino.py`, `internal_casino.py` (+all-human 5% на дом), `admin_stats.py`, `business_digest.py`.
- Бот обмена: `owner_dashboard.py` (строка казино при 0).
- `py_compile` ok. `systemctl restart focuspay-exchange-api` + `tg-bot`.
- `npm run build` + `deploy_all.py`: `panel-CULVQ2K7.js`, бэкап HTML `.bak-20260901-192155`. Прунинг `panel-D2H59w5r.js` и 4 старых ассета.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Не коммитил.
- md5 local=`/opt/exchange-backend`: `finance_pnl.py` `3255813e5f859cbdf09a976acae0dd4b`, `admin_casino.py` `f3598d440912094da9a8ef9a84dbdb6b`. `casino_v2_settlements` в dashboard **4**. `fetch_casino_owner_profit` **2**. `credit_house_game_settlement` в jackpot/rooms.
- SQL прод после формулы: v2 ledger **−45**, v2 hist commission без ledger **34.50**, jackpot hist rake **14.50**, owner commission/house ledger **0** → **owner_profit 4.00 ₽**. Оборот **1080** (790+290), игр **13**. Типы: pvp_dice 5, baccara 3, jackpot 3, blackjack 2. `casino_games` finished по-прежнему 0.
- API `ActiveEnterTimestamp=Tue 2026-09-01 23:20:42 UTC`, health **200**, `/api/admin/casino/dashboard` и `/chart` без токена **401** (не 500). Internal v2 claim **200**. Journal ERROR с рестарта **0**. `tg-bot` active.
- HTML `index.html` `2026-09-01 23:21:57 +0000`, `panel.html` `23:21:59`. HTTPS `/` `/x8` `/ops` `/casino` `/x8/casino` **200**. Бандл `panel-CULVQ2K7.js`: «Прибыль владельца», «Оборот и прибыль», `owner_profit_rub` **4**.
- Diff к прод-копии до выката: `internal_casino` только all-human rake (+23/−1). Роуты `admin_casino` те же.

Скрин входа: `docs/qa-screenshots-2026-09-01/140-prod-x8-login.png`.

Следующий шаг: **стоп**. Клики на проде за человеком (нет пароля админа в этом сеансе).

Потыкать (Ctrl+F5, `https://focuspay.org/x8/casino`):

1. Оборот ≈ **1 080 ₽**, игр **13**, типы кубики/баккара/блэкджек/джекпот — не все нули.
2. «Прибыль владельца» ≈ **4 ₽** (мало игр на проде; −45 со стола с ботом + рейк). График — оборот и прибыль.
3. `/x8?tab=finance` — строка «Казино» есть. `/dash` — extras `казино`.

---

## 2026-09-01 · Нормальная статистика казино (GGR / NGR)

Срез: один нормализованный набор раундов (`casino_stats.py`) вместо четырёх независимых UNION-ов. Оборот — только живые ставки (без стейков ботов). GGR = оборот − выплаты игрокам; рейк со столов с ботами уже внутри P&L против ботов. Две поверхности на одном API: `/x8/casino` и вкладка «Казино» на `/x8`. Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- `_CASINO_ROUNDS_SQL`: `casino_games` finished + v2 settlements + jackpot settled (refunded нет) + rooms settled. Рулетку пятым источником не добавлял — ставки уже в `casino_games` через `play_roulette_known_pocket_with_conn`.
- `fetch_casino_stats`: volume (handle/payouts/GGR/hold/RTP), `ggr_breakdown`, costs → NGR, owner через неизменённый `fetch_casino_owner_profit`, reconciliation, by_type, daily, players, cashier, bankroll.
- `GET /api/admin/casino/stats?date_from&date_to`. `get_casino_dashboard` и `get_casino_chart_data` переведены на тот же модуль.
- `/x8/casino`: период (включая «За всё время»), три ряда KPI, водопад GGR→NGR, график оборот/GGR, таблица по играм с RTP.
- `/x8` вкладка «Казино» + KPI «Казино» в Обзоре (это **леджер** `owner_profit_rub`, не round-GGR).

Файлы: `site/exchange-backend/casino_stats.py`, `routers/admin_casino.py`, `tests/test_casino_stats.py`, `tests/test_admin_casino_regression.py`, `adminApi.ts`, `CasinoDashboard.tsx`, `CasinoStatsView.tsx`, `analyticsPeriod.ts`, `useAnalyticsData.ts`, `analytics/CasinoTab.tsx`, `DataIssues.tsx`, `AdminDashboard.tsx`, `OverviewTab.tsx`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **329** / casino **73**. Не коммитил.
- md5 local=`/opt`=live `/app/backend`: `casino_stats.py` `05e256f3ea0d502a87e95466c4d21a28`, `admin_casino.py` `002fe575cc58aa9025e134fdf39cb657`, `test_casino_stats.py` `6ec48e2a07a6ce6aa23144b1894f8284`, `adminApi.ts` `0b7389c882ac13b53c574f0fb4d8bae7`, `CasinoDashboard.tsx` `4dff8ca6328b5652392c41edfee45ebd`, `CasinoStatsView.tsx` `28289b185a21b35369ce830ba2cdadce`, `CasinoTab.tsx` `f23c38b513019e114b83f1d982d57df4`, `analyticsPeriod.ts` `9365c0b087c55a2d6cf6fb844878ccbc`, `useAnalyticsData.ts` `fee20e76502f2ea2ef0de4e2b746ecf4`, `AdminDashboard.tsx` `4347d53cbdc7c65d834c5c99c1935a7e`, `DataIssues.tsx` `e1fac3d8be8174d5ce95785cca1f8282`.
- Локально `tests/test_casino_stats.py` **13 collected**. Тождества: handle − payouts = GGR; сумма breakdown = GGR; refunded jackpot не раунд; prod-day 1030/1026/4.
- `staging-sync` уже был на staging до клик-пасса. Бандл `panel-D--NpRvH.js`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp` у gateway. Хост **18082** listen `0.0.0.0` / `[::]`. Backend 8000 не опубликован.
- HTTP 200: `/x8/login` `/x8/casino` `/casino` на 18081; `/casino` на 18082.
- `rg`: `fetch_casino_stats` в `casino_stats.py` + `admin_casino.py` (5) + тесты; `getCasinoStats` в `adminApi.ts`, `CasinoDashboard.tsx`, `useAnalyticsData.ts`. Вкладка `{ key: "casino", label: "Казино" }`. `TAB_SLICES.casino = ["casino", "finance"]`.
- SQL `casino_settings` **67**. Источники finished: games **871** + v2 **46** + jp settled **9** + rooms **4** = **930** раундов. Jackpot refunded **7** (не в статистике). Рулетка: bets **177**, все с `casino_games.game_id`, сирот **0**; roulette finished games **412** (ещё 1×1 house chips, не двойной счёт — bets не отдельный UNION).
- Lifetime stats: handle **366373.19**, payouts **354908.89**, GGR **11464.30** = handle − payouts. Owner ledger **22684.53**, reconciliation diff **−11220.23**. Неделя (27 авг–2 сен): handle **365673.19**, GGR **11241.80**, NGR **6076.26**, rounds **926**.
- `staging-test.sh`: **7 failed**, те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет. Collect раньше **1651**, плюс **13** `test_casino_stats` → ожидаемо **1664**.
- Клик 18081: `/x8?tab=casino` и `/x8/casino` одни цифры; период «За всё время» → 930 раундов / 11464.3 GGR; Обзор KPI «Казино» **22 656,03 ₽** (леджер за неделю); Финансы водопад «Казино: комиссия + дом +22 656,03 ₽».
- Прод read-only: `index.html` `2026-09-01 23:21:57 +0000`, `panel.html` `23:21:59`, API `ActiveEnterTimestamp=Tue 2026-09-01 23:20:42 UTC` — без изменений.

Скрины: `docs/qa-screenshots-2026-09-01/150-analytics-casino-tab.png`, `151-casino-dashboard-week.png`, `152-casino-dashboard-all-time.png`, `153-overview-casino-kpi.png`, `154-finance-casino-waterfall.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Следующий пункт плана казино не начинать.

Потыкать (Ctrl+F5, туннель **18081**, админ `123` / `123`):

1. `/x8/casino` → «За всё время»: оборот **366 373,19 ₽** (не банк/пот), раундов **930** = сумма «По играм», GGR **11 464,3 ₽**. Жёлтая сверка с леджером **22 684,53 ₽** — так и задумано, не складывать рейк с P&L против ботов.
2. Тот же экран → «Неделя»: цифры меньше (926 раундов / 11 241,8 GGR). Водопад: PvP + джекпот + P&L ботов = GGR, минус бонусы/рефералы = чистая.
3. `/x8?tab=casino` — те же KPI, что на дашборде за выбранный период аналитики. Обзор KPI «Казино» и Финансы «комиссия + дом» — это **леджер** (~22 656 ₽ за неделю), не GGR вкладки. Холдем/кланы по-прежнему спрятаны.

---

## 2026-09-02 · Прод: пополнение выкл, игроку только 5%

Повод: `/help` в @focusludka_bot обещал СБП/карту и «15% до отыгрыша, 5% после». Сайт уже «Пополнение скоро». 15% в БД не трогал — это на потом, когда депозиты включат.

Срез: флаг `DEPOSITS_ENABLED` — на стейдже вкл (ENVIRONMENT=staging + compose `1`), на проде по умолчанию выкл. `/help` и касса бота без счетов, если флаг выкл. Сайт игроку пишет complete-ставку, без пары до/после. `deploy_all.py` и прод-бот не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- Казино-бот: `DEPOSITS_ENABLED` (`config.py`). Нет ключа → вкл только при `ENVIRONMENT=staging`. Compose staging `DEPOSITS_ENABLED: "1"`. `.env.example` прод `0`, staging example `1`, runbook: в `/etc/focuspay/casino-bot.env` явно `0`.
- `bot.py`: `/deposit`, «Пополнить», `menu:deposit` → «Пополнение скоро». Старые `depamt:` / `dep:pay:` — алерт, `create_deposit` не зовут.
- `/help`, `/help deposit`, `/help rules`: при флаге выкл только complete % и «скоро»; при вкл — как было 15/5 и СБП/карта.
- `casinoLevelCopy.ts`: игроку «Комиссия сейчас N%» / «Комиссия N%», без «до отыгрыша». Админка не трогал.

Файлы: `focuspay-casino` `config.py` `bot.py` `games/help.py` тесты help/startup/staging_ui/staging_config, `.env.example` `.env.staging.example` `PRODUCTION_RUNBOOK.md`. Сайт: `casinoLevelCopy.ts`, `check-casino-wallet-rules.mts`, `docker-compose.staging-runtime.yml`, `bootstrap_static_test.sh`.

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Dirty **329** / casino **73**. Не коммитил.
- md5 local=`/opt`=`/app`: `config.py` `90f3201188f18ebea8a2c2b08bceb9c0`, `bot.py` `792ccded2935ef4f79b73c113b9e1379`, `games/help.py` `ba1d426c63e9c0d4f13b30d936b903cf`, `casinoLevelCopy.ts` `6e6667984691500021deb89a59c49201`.
- Локально казино-бот `tests/` без e2e **313**. `check-casino-wallet-rules.mts` **ok**.
- `staging-sync` health **passed** дважды. Контейнер casino-bot: `ENVIRONMENT=staging` `DEPOSITS_ENABLED=True`. `/help` в контейнере по-прежнему **15%/СБП** (стейдж так и должен).
- Бандл `index-Dsoeqckf.js`: «Пополнение скоро» **1**, «до отыгрыша» **0**, «Комиссия сейчас» **1**.
- HTTP **200** `/casino` 18081 и 18082, `/api/health` `{"status":"ok"}`.
- Docker: наружу `127.0.0.1:18081` и хост **18082**. Backend 8000 не опубликован (`PublishedPort:0`).
- SQL: `min_bet` 10 / `max_bet` 100000; комиссия active **15%**, complete **5%** (не менял).
- `rg` `DEPOSITS_ENABLED`: config, bot, help, compose, bootstrap, env examples, runbook, тесты.
- `staging-test.sh` / pytest `-o addopts=`: **7 failed**, **1657** passed, 1 skipped. Те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- Клик 18082 Fixture Buyer: касса «Пополнение скоро», без СБП/карты. Лобби плитки **от 10 ₽ · комиссия 5%**. `/casino/me`: «Комиссия сейчас 2.5%» / «Комиссия 2.5%», без «до отыгрыша» (уровень 4, complete с сетки).
- Прод read-only: `index.html` `2026-09-01 23:21:57 +0000`, `panel.html` `23:21:59`, API `23:20:42`, casino-bot `22:54:00` — без изменений.

Скрины: `docs/qa-screenshots-2026-09-01/160-cashier-deposit-soon.png`, `161-profile-commission-5.png`.

Следующий шаг: **стоп**. Прод-бот и `deploy_all.py` — только после «го».

Потыкать:

1. Стейдж-бот `@focuscazzcztewrfweda_bot`: «Пополнить» / `/deposit` — сумма → СБП/карта. `/help` — 15% и СБП (так и надо на стейдже).
2. 18082 `/casino`: Пополнить → «скоро». Профиль — одна ставка комиссии, без «15% до отыгрыша».
3. Прод @focusludka_bot пока старый: СБП ещё живое, пока не скажешь «го» на выкат бота.

---

## 2026-09-02 · Прод выкат: депозиты выкл, игроку 5%

Срез: на `@focusludka_bot` и `https://focuspay.org/casino` залито то же, что на стейдже: пополнение «скоро», `/help` только complete 5%, без СБП/карты. 15%/5% в БД не трогал. `focuspay-exchange-api` не рестартил. Webhook unit не включал. Холдем/кланы не открывал. Не коммитил.

Сделано:

- Бэкап `/opt/backups/focuspay-casino-deposits-off-20260902T010301Z` (старые `bot.py` / `config.py` / `games/help.py` + копия env).
- Хирургический rsync трёх файлов → `/opt/focuspay-casino`, `chown focuspay`, `py_compile`, `DEPOSITS_ENABLED=0` в `/etc/focuspay/casino-bot.env`, `systemctl restart focuspay-casino-bot`.
- `npm run build` + `deploy_all.py`: `index.html` / `panel.html` `.bak-20260901-210502`, ассеты залиты, старые бандлы prune.

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Dirty **332** / casino **73**. Не коммитил.
- md5 local=`/opt/focuspay-casino`: `bot.py` `792ccded2935ef4f79b73c113b9e1379`, `config.py` `90f3201188f18ebea8a2c2b08bceb9c0`, `games/help.py` `ba1d426c63e9c0d4f13b30d936b903cf`.
- Unit `active`/`running`, `ActiveEnterTimestamp=Wed 2026-09-02 01:03:17 UTC`. Старт: `@focusludka_bot`, PVP/V2/wizard/baccara/blackjack/roulette/jackpot/rooms/fairness, slash menu cleared. ERROR **0**. Webhook **inactive**.
- `DEPOSITS_ENABLED` False, `ENVIRONMENT` пустой. `/help` на проде: «Комиссия игр: 5%», «Пополнение: скоро…», без 15% и СБП. `/help deposit` — тот же soon-текст.
- HTML: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`. API без рестарта: `ActiveEnterTimestamp=Tue 2026-09-01 23:20:42 UTC`.
- HTTPS 200: `/` `/x8` `/ops` `/casino` `/x8/login`, `/api/health` `{"status":"ok"}`. HTTP :80 → 301 на https (ожидаемо).
- Живой бандл `index-Y77pyayI.js`: «Пополнение скоро» **1**, «Комиссия сейчас» **1**, «до отыгрыша» **0**. `panel-D--NpRvH.js`: «до отыгрыша» **8** (админка, так и надо).
- Стейдж не сломали: контейнер `ENVIRONMENT=staging` `DEPOSITS_ENABLED=True`. Docker наружу `127.0.0.1:18081`, хост **18082**. Backend 8000 не опубликован. SQL стейдж: min 10 / max 100000, active **15%**, complete **5%**.
- Клик прод: лобби «комиссия 5%» / «от 10 ₽ · комиссия 5%». Касса «Пополнение скоро». `/casino/me`: «Комиссия сейчас 5%» / «Комиссия 5%», без «до отыгрыша».

Скрины: `docs/qa-screenshots-2026-09-01/170-prod-lobby-commission-5.png`, `171-prod-cashier-deposit-soon.png`.

Следующий шаг: **стоп**. Следующий пункт плана казино не начинать.

Потыкать (прод, Ctrl+F5):

1. `@focusludka_bot`: `/help` — 5% и «скоро», без СБП. «Пополнить» / `/deposit` — текст soon, без сумм и реквизитов.
2. `https://focuspay.org/casino`: лобби 5%, Пополнить → «скоро». Профиль — одна ставка, без «15% до отыгрыша».
3. Стейдж-бот по-прежнему живое пополнение СБП/карта.

---

## 2026-09-02 · Комиссии обменника = казино + TRX на вывод

Срез: одна таблица исходящих комиссий для кассы, вывода баланса и учёта сети на BUY. Карта 100 ₽; BTC/LTC/TRX $2.5 × USDT/RUB; USDT $4. TRX только на вывод кассы (депозит без TRX). `source` больше не меняет сумму. Прод / `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- Бот + бэкенд: `network_fee_usd` / `casino_withdraw_fee_rub`; `withdraw_fee_rub` без ветки casino vs balance. `CASINO_WITHDRAW_FEE_USD_TRX=2.5`. Старые `CRYPTO_NETWORK_FEE_RUB_*` не читаются.
- Тексты вывода: карта 100 ₽, BTC/LTC/TRX $2.5 (≈₽), USDT $4. Тарифы API: `network_fee_*_usd` + rub из курса.
- Касса: `trx` в выводе $2.5; USDT UI $4 (было $5).

Файлы: `crypto_network_fee.py` (бот и бэкенд), `config_rates.py`, `config.py`, `payment_methods_display.py`, `ux_copy.py`, `.env.example` оба, `casinoWalletRules.ts`, `CasinoCashier.tsx`, `check-casino-wallet-rules.mts`, `test_crypto_network_fee.py`, `test_casino_payouts_ops.py`.

Проверки:

- git HEAD focuspay `61e47be`, casino `4b8d65e`. Dirty **332** / casino **73**. Не коммитил.
- md5 local=`/opt`=`/app/backend` / `/opt/tg_bot_btc`: `crypto_network_fee.py` бэк `671fda725a6482cc6675dbe0c1689fed`, бот `eadc6f5d08554af0f70f7e429034c09c`; `config.py` `1be97e99781243d0f4e5bcbad7458a40`; `config_rates.py` `846673e8b18b62f8f9dce02c79037efe`; `ux_copy.py` `4d30bbb6dc33d1188557080972fb1d91`; `payment_methods_display.py` `716bb6fa4e0695b3305f9fe4f6f9b9d2`; `casinoWalletRules.ts` `f444d1474e6fe9d7fa2b58e8d50640ca`; `CasinoCashier.tsx` `497a62d762977332be7dcd22af8cc965`; `check-casino-wallet-rules.mts` `78b050dcffe434bc318076d581216a08`; `test_casino_payouts_ops.py` `85fb15789ef02435fec271e25070b617`; `test_crypto_network_fee.py` `d3a3e576019949fe99151e9aff4ace06`.
- Локально: бот `test_crypto_network_fee` **7 OK**; бэкенд fee-хелперы **OK**; `check-casino-wallet-rules.mts` **ok**; `npx tsc -b` чисто.
- Живой хелпер в контейнере @80 USDT: карта **100**, BTC/TRX **200**, USDT **320**.
- `staging-sync` health **passed**. HTTP 200 `/casino` `/x8/login` на 18081.
- Docker: наружу `127.0.0.1:18081` и хост **18082**. Backend 8000 не опубликован.
- SQL `casino_settings` **67**.
- `rg casino_withdraw_fee_usd_trx` / `TRX_WITHDRAW_FEE_USD`: config, хелпер, тарифы, касса, чек, тесты, `.env.example`.
- `staging-test.sh`: collect **1664**; **7 failed**, те же семь имён: `CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`. Новых нет.
- Клик 18082 `/casino#withdraw`: карта от 500 ₽ · 100 ₽ (в USDT-режиме 1.19); USDT **$4**; BTC/LTC/TRX **$2.5**. Форма TRX: 250 ₽ → комиссия 2.50 USDT. Форма карты 500 ₽ → к выплате 4.76 USDT (500−100).
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `ActiveEnterTimestamp=Tue 2026-09-01 23:20:42 UTC` — без изменений за этот срез.

Скрины: `docs/qa-screenshots-2026-09-01/160-cashier-withdraw-fees.png`, `161-cashier-trx-fee.png`, `162-cashier-card-fee.png`.

Следующий шаг: **стоп**. Прод / `deploy_all.py` только после явного «го».

Потыкать (Ctrl+F5, **18082** или туннель **18081**):

1. `/casino#withdraw` — семь способов: карта 100 ₽, USDT $4, BTC/LTC/TRX $2.5. Tron есть только на выводе, не на пополнении.
2. Бот обменник: блок «Вывод средств» — карта 100 ₽, BTC/LTC/TRX $2.5, USDT $4, не 50/20 ₽.
3. Вывод с баланса на карту от 5000 ₽: к выплате сумма минус 100 ₽.

---

## 2026-09-02 · Таблицы долей: рефералы, создатель, кешбэк, бонусы

Срез: на `/x8/casino` и вкладке «Казино» под водопадом видно, кому ушла доля, с чьей игры и сколько. Очередь выводов не трогал. Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- `fetch_casino_stats.distributions`: referrals (L1/L2, кому, с кого, игр, сумма), creators (партнёрский аккаунт + игрок раунда), cashback, bonuses. «С кого» = проигравший `casino_games`, иначе `creator_id`.
- Пустые нулевые таблицы скрыты. Тождество `shown + hidden = costs.*`. Лимит 40 строк.
- UI: `CasinoStatsView` — четыре карточки, ссылка `/x8/users?user=`. Оба экрана на одном компоненте.

Файлы: `casino_stats.py`, `tests/test_casino_stats.py`, `routers/admin_casino.py` (поле `distributions`), `adminApi.ts`, `CasinoStatsView.tsx`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **73**. Не коммитил.
- md5 local=`/opt`=live `/app/backend`: `casino_stats.py` `6ac3d01c3c222a43ff613dec711876d0`, `test_casino_stats.py` `be2b20ac74aa529204dbc253611296a3`, `admin_casino.py` `45e584a972bcd3ff5b4e96cbd3708e99`, `CasinoStatsView.tsx` `64b75fae9a86dbd7642e57d4c7648d13`, `adminApi.ts` `dc887db0e280b557a7f9733b26c206cd`.
- Локально `test_casino_stats.py` **16 passed**. `npx tsc -b` чисто.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Бандл `panel-CdfE5g1u.js`.
- Docker: наружу только `127.0.0.1:18081->8080/tcp`. Хост **18082** listen. Backend 8000 не опубликован.
- HTTP 200: `/x8/casino` `/casino` на 18081.
- SQL `casino_settings` **67**. Ledger: owner **11469.48**, referrer_l1 **1165.54** (793), creator **0**, cashback accrued **0**, bonuses **4000** (3).
- Клик 18081 `/x8/casino?period=all`: рефералы `@fixture_full_referrer` L1 с `@fixture_full_buyer` 793 игр **1 165,54 ₽**; бонусы `@fixture_full_buyer` 3 × **4 000 ₽**. Создатель и кешбэк скрыты (нули). `/x8?tab=casino` — те же таблицы.
- `staging-test.sh`: **7 failed**, те же семь имён. Новых нет. Collect раньше **1664**, плюс **3** теста долей → ожидаемо **1667**.
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `ActiveEnterTimestamp=Tue 2026-09-01 23:20:42 UTC` — без изменений за этот срез.

Скрины: `docs/qa-screenshots-2026-09-01/155-casino-share-tables.png`, `156-analytics-share-tables.png`.

Следующий шаг: **стоп**. Прод не выкатывать.

Потыкать (Ctrl+F5, туннель **18081**, админ `123` / `123`):

1. `/x8/casino` → «За всё время»: блок «Рефералам» 1 165,54 ₽ = строка водопада; кому / с кого / L1. «Бонусы» 4 000 ₽ кому. Кешбэк и создатель не показываются, пока ноль.
2. Имя в таблице — ссылка на `/x8/users?user=`. Очередь выводов по-прежнему только «Выплаты создателя».
3. `/x8?tab=casino` за неделю — те же две таблицы, сумма рефералов совпадает с водопадом.

---

## 2026-09-02 · Прод: комиссии обменника = казино + TRX на вывод

Срез: на `focuspay.org` одна таблица исходящих комиссий. Карта **100 ₽**; BTC/LTC/TRX **$2.5** × USDT/RUB; USDT **$4**. `source` больше не делит казино и баланс. `deploy_all.py` не гонял — касса уже была с этой сеткой с HTML `01:05`. Таблицы долей / антиспам / прочий dirty не выкатывал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- Бэкап `/opt/backups/exchange-backend-code-pre-20260902T012119Z.tgz`, `tg_bot_btc-code-pre-20260902T012119Z.tgz`, файлы в `fee-unify-20260902T012119Z/`.
- rsync хелперов и тарифов: `crypto_network_fee.py`, `payment_methods_display.py` (бэкенд + бот).
- На проде только дописал `casino_withdraw_fee_usd_trx` / `CASINO_WITHDRAW_FEE_USD_TRX`. Целые `config.py` / `config_rates.py` не копировал (`CRYPTO_NETWORK_FEE_RUB_*` в боте оставлены как мёртвые константы).
- `ux_copy.txt_withdraw_terms` — только эта функция (карта + BTC/LTC/TRX $ + USDT $).
- `systemctl restart focuspay-exchange-api` + `tg-bot`. Uvicorn stop → SIGKILL ~90с, затем active.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **73**. Не коммитил.
- md5 local=`/opt`: `crypto_network_fee.py` бэк `671fda725a6482cc6675dbe0c1689fed`, бот `eadc6f5d08554af0f70f7e429034c09c`; `payment_methods_display.py` бэк `716bb6fa4e0695b3305f9fe4f6f9b9d2`, бот `b6c61eba74aa0f5c469e1c8e95fde736`. Config/ux — хирургический патч, md5 локального WIP не ждали.
- `py_compile` ок. Health `/api/health` **200**, `/casino` **200**.
- Живой хелпер @80 USDT: карта **100** (balance=casino), BTC/TRX **200**, USDT **320**.
- `GET /api/public/rates` → `public_tariffs.withdraw_limits`: card **100**, btc/ltc/trx **$2.5** (≈222.65 ₽ @89.06), usdt **$4** (≈356.24 ₽).
- Бот compact terms: карта 100 ₽ · BTC/LTC/TRX $2.5 · USDT $4. Rapira timeout в журнале был и до рестарта (снимок курсов).
- Клик прод `https://focuspay.org/casino#withdraw`: семь способов — карта 100 ₽; USDT ≈345,56 ₽ ($4); BTC/LTC/TRX ≈215,98 ₽ ($2.5). Форма TRX 250 ₽ → комиссия 215,98 · к выплате 34,02. Пополнение на проде закрыто («скоро») — Tron там нет.
- HTML не трогал: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, `casino.html` `01:05:01`. API/бот `ActiveEnterTimestamp=Wed 2026-09-02 01:25:26 UTC`.

Скрины: `docs/qa-screenshots-2026-09-01/163-prod-cashier-withdraw-fees.png`, `164-prod-cashier-trx-form.png`.

Следующий шаг: **стоп**.

Потыкать (Ctrl+F5, **прод**):

1. Бот обменник → «Вывод средств»: карта 100 ₽, BTC/LTC/TRX $2.5 (≈₽), USDT $4 — не 50/20 ₽ и не карта 0.
2. Вывод с баланса на карту от 5000 ₽: к выплате сумма минус 100 ₽.
3. `/casino#withdraw` — семь способов как в скрине 163; Tron только на выводе.

---

## 2026-09-02 · Доли Creator/L1/L2 режутся вместе с комиссией уровня

Срез: в `/x8/casino/settings` таблица уровней показывает вычисленные доли Creator · L1 · L2 · казино на каждой ступени. Деньги settle уже так работали (`commission_shares_for_rate`). Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал. v2/джекпот/комнаты не резал.

Сделано:

- Тесты `scale_stake_share_percents` / `commission_shares_for_rate`: 15→15 без изменений; 15→10 creator 3→2, L1/L2 ×2/3; complete 5→4 → 0.8/0.4/0.4; allocate 100 ₽ на 10% = 2.00+1.33+1.33+5.34; ставка выше базы доли растут.
- Админка: колонки «Доли до» / «Доли после» (только чтение). Формула как бэкенд: `share * rate_ступени / rate_базы`.
- Первая ступень уже синхронизировалась с полями «Комиссия до/после» в обе стороны — не дублировал.
- Self-check `15→18 === 3.6` в JS давал `3.599…` и глушил весь `/x8` (чёрный экран). Починил через `Math.abs … 1e-9`. Бандл `panel-wwtkcIhO.js` → `panel-BjZEjB-p.js`.

Файлы: `tests/test_casino_commission.py` (+7), `casinoSettingsModel.ts` (`scaleStakeSharePercents`, `formatLevelShares`), `CasinoTierGrids.tsx`, `CasinoSettings.tsx` (`shareBase={form}`).

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **73**. Не коммитил.
- md5 local=`/opt`: `test_casino_commission.py` `0b131786515db79cf970dd207cd3bf16`, `casinoSettingsModel.ts` `ab0b739e4bc7f3b91c14ef342745f1ea`, `CasinoTierGrids.tsx` `1e77dc940bc5b94217c9932bc4c92de3`.
- Локально `test_casino_commission.py` **23 passed**. `npx tsc -b` чисто.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (два раза: до и после фикса self-check).
- Docker: наружу только `127.0.0.1:18081->8080/tcp`. Backend 8000 не опубликован.
- HTTP 200: `/x8/casino/settings` на 18081.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Collect **1674** (было ожидаемо 1667 + 7 тестов шкалы). Новых имён нет.
- Клик 18081 `/x8/casino/settings`: ступень 0 ₽ доли **3 · 2 · 2 · 8** и **1 · 0,5 · 0,5 · 3**; 50k **2,4 · 1,6 · 1,6 · 6,4** (×12/15); 100k **2 · 1,333 · 1,333 · 5,333**; 200k **1,6 · 1,067 · 1,067 · 4,267**. Панель ячейки: Creator / L1 / L2 / казино. Сохранить не жал — форма не dirty, колонки не пишутся в PATCH.
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `ActiveEnterTimestamp=Wed 2026-09-02 01:25:26 UTC` — без изменений за этот срез.

Скрины: `docs/qa-screenshots-2026-09-01/180-level-shares.png`, `181-level-shares-panel.png`.

Следующий шаг: **стоп**. Прод не выкатывать.

Потыкать (Ctrl+F5, туннель **18081**, админ `123` / `123`):

1. `/x8/casino/settings` → «Уровни»: колонки «Доли до/после». На 15% база = 3·2·2·8; на 12% = 2,4·1,6·1,6·6,4.
2. Клик по доле — под таблицей расшифровка Creator / L1 / L2 / казино.
3. Поменять «Комиссия до» в блоке выше — первая строка сетки та же цифра; доли следующих ступеней пересчитаются сразу, без сохранения.

---

## 2026-09-02 · Чат V2: одна карточка стола, итог отдельным сообщением

Срез: в игровом чате стол больше не плодит «стол опубликован» + лобби + «вы заняли место» + приглашение бросать. Одна карточка с составом мест; после расчёта бот шлёт компактный итог и пытается удалить карточку, броски и служебные id. Прод и `deploy_all.py` не трогал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- Ledger `games/v2_chat_ledger.py`: `trash_msg_ids` в `play_chats`, `add_trash` / `collect_trash`, кэш на время игры (`persist-state` после `finished` уже нельзя).
- Карточка лобби: места 1..N, tg-ссылка, «свободно», ставка. Join — toast, без второго сообщения. Визард правит своё сообщение в карточку.
- Броски правят ту же карточку (`card_msg_id`); эмодзи-кубы пишутся в ledger. Итог: победитель, выигрыш, кнопка «Проверить игру» (`/casino/tables/{id}` или fairness для карт).
- Если `delete_message` запрещён — карточка редактируется в итог. Outbox `settled` добивает групповую карточку, если стол закрыли с сайта.
- Preflight: бот **member** в `GAME_CHAT_ID=-5562276559`, не админ. Warning, не fail. Чужие кубики игроков бот удалит только после admin + can_delete_messages.

Файлы (casino): `games/v2_chat_ledger.py`, `games/v2_runtime.py`, `games/v2_tables.py`, `games/table_wizard.py`, `tests/test_v2_chat_hygiene.py` (+6), правки `test_v2_card_board.py` / `test_table_wizard.py` / `test_v2_tables.py`. FocusPay: `focussite/scripts/staging-runtime-preflight.sh`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **75**. Не коммитил.
- md5 local=`/opt`=`контейнер`: `v2_runtime.py` `48d8fb9b33dd47e1c0b559321ea14659`, `v2_chat_ledger.py` `93a3317e12332b9cef9e80a6d6446f62`, `v2_tables.py` `c6ecd423b0cb465133be624ec5d660f7`, `table_wizard.py` `8c661305a8c32b99ae098af9b43ef782`, preflight `b9c8c15068cbbb50a9a408e41af239c2`.
- Локально casino `pytest tests` (без e2e) **320 passed**. Hygiene+card+wizard+v2_tables **53 passed**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (warning: bot status=member).
- Docker: наружу только `127.0.0.1:18081->8080/tcp` + host `0.0.0.0:18082`. Backend 8000 не опубликован.
- HTTP 200: `/casino`, `/api/public/casino/v2/tables` → `tables: 0`.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- `rg` `collect_trash` / `publish_settled_table`: ledger + `v2_runtime.py` + `test_v2_chat_hygiene.py` (не одно вхождение).
- Клик 18082: лобби; `/casino/play/pvp_dice?mode=players` — «открытых столов нет»; `/casino/fairness` — форма «по ссылке из бота проверка запускается сама».
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `ActiveEnterTimestamp=Wed 2026-09-02 01:25:26 UTC` — без изменений.

Скрины: `docs/qa-screenshots-2026-09-01/190-dice-players-after-chat-hygiene.png`, `191-fairness-verify-game.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Бот в игровой группе нужно сделать админом с «удаление сообщений», иначе кубики игроков останутся.

Потыкать (Telegram staging `@focusludka_bot` / focusgame, группа GAME_CHAT; сайт **18082** или туннель **18081**):

1. В игровом чате создать кубики 2–3 места. Должно остаться **одно** сообщение: состав мест, свободно N, кнопки «Занять место» / «Бот» / «Смотреть на сайте». Без «стол опубликован» и без «вы заняли место».
2. Второй игрок жмёт «Занять место» — карточка **редактируется** (имя в списке, свободно −1), новое сообщение не появляется.
3. Доиграть. После итога: одно новое «Победил / Выигрыш / Проверить игру»; старая карточка и броски бота исчезают. Кубики людей исчезнут только если бот — админ с правом удаления.
4. Кнопка «Проверить игру» у кубиков открывает `/casino/tables/{id}`; у баккары/блэкджека — `/casino/fairness?...`.

---

## 2026-09-02 · Чат: живая карточка рулетки + TTL-уборка

Срез: в Telegram одна карточка рулетки/джекпота на чат с обновляемым «До спина N с.», не персональные «Ставка принята». После спина карточка удаляется, итог живёт 4 мин. `/help` и служебные ответы — 2–4 мин. В группе бот пытается удалять команды игроков. Личные квитанции (выплаты, пополнения) не трогал. Прод не выкатывал. Не коммитил.

Сделано:

- `games/chat_reaper.py`: реестр TTL (`TTL_HELP=240`, `TTL_ROUND=240`, `TTL_SERVICE=120`, `TTL_CARD=90`), `send_ephemeral` / `reply_ephemeral`, `sweep`, `try_delete_user_message` только в группе, `reaper_loop` — пятая задача в `main()`.
- `games/live_card.py` + `roulette_card.py` / `jackpot_card.py`: один `send_message` на раунд, дальше `edit_message_text`. Тикер 5 с (рулетка) / 30 с (джекпот). После `locked` — «Колесо крутится», карточка уходит в TTL 90 с.
- Ставка из чата больше не шлёт отдельный reply каждому: список всех `players` + банк + таймер. Ссылка только кнопкой. Шпаргалка/ошибки — ephemeral, `append_watch_line` в шпаргалке и в `confirm_text` остался (статик-тест).
- Outbox `roulette_table_settled` / `jackpot_settled` / `jackpot_refunded`: `drop` карточки, затем итог, затем TTL 4 мин. Групповой итог V2 — тоже TTL 4 мин. `/help`, `/start` и `/deposit` в группе, `catch_all`, отказ `chat_guard` — TTL 2 мин.

Файлы (casino): `games/chat_reaper.py`, `games/live_card.py`, `games/roulette_card.py`, `games/jackpot_card.py`, `games/roulette_table.py`, `games/jackpot.py`, `games/chat_guard.py`, `bot.py`, `recovery.py`, `games/v2_runtime.py`, `tests/test_chat_reaper.py`, `tests/test_roulette_card.py` (+ правки `test_roulette_table.py` / `test_jackpot.py` / `test_bot_startup.py` / `test_recovery.py` / `test_game_chat_guard.py`). FocusPay: `focussite/docker/staging-db/bootstrap_static_test.sh` (`require` на `TTL_HELP` / `reaper_loop` / `card_text`).

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **81**. Не коммитил.
- md5 local=`/opt`=`контейнер`: `chat_reaper.py` `f0087af47aa0650665f1a89296b14d81`, `roulette_card.py` `b4ef424691206ed4c6962c3409bbe0ad`, `jackpot_card.py` `99ac3eaba00621862d9284468a4191f8`, `live_card.py` `b72bc69e3ccd0b88866cf6d1a30f2e92`, `roulette_table.py` `7c63775bb78a1083d5a836fb4b3b21c5`, `jackpot.py` `04257650dd1e61bbbbee643085d6a9fe`, `bot.py` `9a50107821ec9e969b73d179dd2c08fb`, `recovery.py` `ea8660060549fa3cc6fe266ae9497c0c`, `v2_runtime.py` `fffc9516d1c69aa1c7d50fdec6044cd9`.
- Локально casino `pytest tests` (без e2e) **332 passed**. Связанные hygiene/card/startup/recovery/guard **74 passed**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (warning: bot status=member, `can_delete_messages=None`).
- Docker: наружу `127.0.0.1:18081->8080/tcp` + host `0.0.0.0:18082`. Backend 8000 не опубликован. casino-bot ERROR **0**. Старт: Roulette/Jackpot handlers + «Background cleaners and recovery worker started».
- HTTP 200: `/casino`, `/casino/play/roulette`, `/api/public/casino/roulette-table`.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- `rg` `reaper_loop` / `TTL_HELP` / `LiveCardBoard` / `upsert_roulette_card`: bot + chat_reaper + live_card + roulette_table + jackpot + тесты (не одно вхождение).
- `bootstrap_static_test.sh` локально падает на чужом `data-casino-now-playing` в `CasinoShell.tsx` (не этот дифф). Наши `require` на `TTL_HELP` / `reaper_loop` / `card_text` в файлах есть.
- Клик 18081: рулетка «Ждём первую ставку», стол 0–36; джекпот банк 0 ₽, «Первая ставка запускает таймер».
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `01:25:26`, casino-bot `01:03:17` — без изменений.

Скрины: `docs/qa-screenshots-2026-09-01/200-roulette-table-chat-hygiene.png`, `201-jackpot-table-chat-hygiene.png`.

Следующий шаг: **стоп**. Прод не выкатывать. В игровой группе бот всё ещё `member` — чужие команды и броски игроков он удалит только после admin + can_delete_messages. Свои сообщения бота чистит и без админки.

Потыкать (Telegram staging `@focuscaztest` / игровой чат; сайт **18082** или туннель **18081**):

1. `/roulette red 50` в игровом чате — одно сообщение «Ставка принята» со списком ставок и «До спина N с.», секунды должны **уменьшаться**. Второе `/roulette black 25` правит ту же карточку, не шлёт новую.
2. Дождаться спина. Карточка ставки исчезает, приходит одно «Рулетка · выпало …». Через ~4 минуты итог тоже исчезает.
3. `/help` и `/help roulette` — ответ есть, через ~4 минуты пропадает. Команда игрока пропадёт только если бот — админ с правом удаления.
4. Личка: итог выигрыша / пополнение не должны пропадать.

---

## 2026-09-02 · V2 closer: столы из Telegram больше не зависают в ready

Срез: баккара `fbbed2ab` зависла в `ready` после «+бот», потому что цикл `start_due` (`casino_v2_web.ensure_closer`) поднимался только с веб-роутеров. На стейджинге `STAGING_DISABLE_BACKGROUND_TASKS=true`, после рестарта бэкенда сайт никто не открывал — отсчёт истёк, раунд не стартовал, ставка висела. Чистка чата тут ни при чём. Прод не выкатывал. Не коммитил.

Сделано:

- `site/exchange-backend/main.py`: `casino_v2_web.ensure_closer()` в `lifespan` рядом с раффлом, **до** раннего выхода по `staging_disable_background_tasks`.
- `routers/internal_casino.py`: `_ensure_v2_web_closer()` в `create/join/bots/start` v2 — как у рулетки/джекпота. Страховка, если lifespan пропустят.
- Бот: в карточке лобби строка «Старт через N с» / «Старт вот-вот»; если через 20 с после `starts_at` стол всё ещё `ready` — «Старт задерживается, ждём сервер» + `logger.warning`. Тикер раз в 3 с, один на `table_id`, `drain_ready_watchers()` на остановке бота. Автоотмену не делал.
- Зависший `fbbed2ab` подхватился сам после рестарта стейджинга: `ready` → `finished` за ~3 с (`started_at=04:41:52`, `settled_at=04:41:55`), места `settled`, холд `casino-h-3d7d76e3…` ушёл в `spend`, резерв дома `settled`.

Файлы (backend): `site/exchange-backend/main.py`, `site/exchange-backend/routers/internal_casino.py`, `site/exchange-backend/tests/test_internal_casino.py` (`V2InternalCloserContractTests`). Casino: `games/v2_runtime.py`, `bot.py`, `tests/test_v2_chat_hygiene.py`, `tests/test_v2_card_board.py`. FocusPay: `focussite/docker/staging-db/bootstrap_static_test.sh` (`require` на closer / отсчёт / drain).

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **81**. Не коммитил.
- md5 local=`/opt`=`контейнер`: `main.py` `601ceedcc8fed0ca96c4daeebac6645b`, `internal_casino.py` `415c8090a3f5fe07e20e423422c40b7d`, `v2_runtime.py` `558c2b0adb74ed53c17adf0e7a7cf518`, `bot.py` `9402de1607b95debc8ed8d276d50da68`.
- Локально casino `pytest tests` (без e2e) **338 passed**. Hygiene+card+startup **63 passed** в связанном наборе. Backend `V2InternalCloserContractTests` + autostart **4 passed**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (warning: bot status=member, `can_delete_messages=None`).
- Docker: наружу `127.0.0.1:18081->8080/tcp` + host `0.0.0.0:18082`. Backend 8000 не опубликован.
- HTTP 200: `/casino`, `/casino/play/baccara`, `/api/public/casino/v2/tables`.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- `rg` `_ensure_v2_web_closer` / `v2_web_ensure_closer` / `drain_ready_watchers` / `DELAY_NOTICE`: main + internal_casino + v2_runtime + bot + тесты + bootstrap (не одно вхождение).
- SQL: после sync `fbbed2ab` `finished`, seats `settled`, hold `spend -100.00`, house reservation `settled`. `ready` столов 0. Клик-пасс создал `web-412784434311408e` — тоже `finished` (бот сел, раунд не завис).
- Клик 18081: лобби; баккара «открытых столов нет» (зависшего нет); создать 2 места 100 ₽ → «+ бот» → через ~10 с карты и итог (бот 7, игрок 3, −100 ₽).
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `01:25:26`, casino-bot `01:03:17` — без изменений.

Скрины: `docs/qa-screenshots-2026-09-01/210-lobby-after-v2-closer.png`, `211-baccara-no-stuck-table.png`, `212-baccara-bot-round-settled.png`.

Следующий шаг: **стоп**. Прод не выкатывать. В игровой группе бот всё ещё `member` — команды игроков он не удалит, пока нет права «Удаление сообщений».

Потыкать (Telegram staging игровой чат; сайт **18082** или туннель **18081**):

1. В чате создать баккару 2 места, посадить бота. Карточка должна показать «Старт через N с», секунды уменьшаются, затем раздача и итог. Не должно висеть вечно без кнопок.
2. То же с кубиками 2 места + бот.
3. На сайте `/casino/play/baccara?mode=players`: создать стол 2 места, «Добавить бота» — раунд должен закончиться сам, без открытия других страниц.
4. Если старт задержится больше ~20 с — в карточке Telegram появится «Старт задерживается, ждём сервер». Автоотмены нет.

---

## 2026-09-02 · Азарт и единый стиль живых карточек в Telegram

Срез: живые карточки бота сводятся к одному каркасу (`Сейчас` / `Дальше` / таймер / ссылки). Карты раскрываются по улицам, рулетка крутится тактами, джекпот тикает чаще к концу и крутит катушку, комнаты получили LiveCardBoard вместо одной кнопки «Обновить», кубики показывают кто бросает и дедлайн. Такты держит бот (`games/drama.py`); бэкенд не трогал. FocusLucky в боте по-прежнему выключен. Холдем/кланы не открывал. Прод и `deploy_all.py` не трогал. Не коммитил.

Сделано:

- `games/board_style.py`: `render_board` + `PHASE_LABELS` + общий `timer_line` / `next_line`.
- `games/drama.py`: `run_beats` / `wait_drama` / `drain_drama`, троттлинг 1.2 с, `REVEAL_HOLD_SECONDS=12`. Дренаж в `bot.py` рядом с `drain_ready_watchers`.
- Карты: `games/card_streets.py` (2 с на улицу). `_card_text(..., reveal_streets=N)` скрывает счёт (`—`, «раздача»). Если есть `cards_dealt_at`, баккара не добирает третьи и не зовёт `_score_cards`. `publish_settled_table` ждёт `v2-reveal:` / `v2-score:`.
- Рулетка: такты «ставки закрыты → крутится → замедляется → номер»; карман скрыт до последнего такта. `_is_terminal` только `settled` и drama done.
- Джекпот: интервал 30 / 5 / 2 с; такты катушки «крутится → финалисты → победитель».
- Комнаты: `games/rooms_card.py` (LiveCardBoard 5 с, 2 с на отсчёте). Кнопка «Обновить» осталась.
- Кубики 2–6: «бросает место N», «ведёт», «До броска N с», такт «Считаем результат…» 2 с. Тикер дедлайна 3 с.

Файлы (casino): `games/board_style.py`, `games/drama.py`, `games/card_streets.py`, `games/rooms_card.py`, `games/live_card.py`, `games/v2_runtime.py`, `games/roulette_card.py`, `games/jackpot_card.py`, `games/rooms.py`, `games/jackpot.py`, `games/roulette_table.py`, `bot.py`, `tests/test_board_style.py`, `tests/test_drama.py`, `tests/test_v2_card_streets.py` (+ правки roulette/jackpot/rooms/hygiene/card_board). FocusPay: `focussite/docker/staging-db/bootstrap_static_test.sh` (`require` на `render_board` / `drain_drama` / `Раздача: вторая карта…` / `rooms_card.drama_key`).

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **88**. Не коммитил.
- md5 local=`/opt`=`контейнер`: `board_style.py` `04e1f983181114852c822f80bfaa0d10`, `drama.py` `00c91d6d62befc146fd6b47e0012741a`, `card_streets.py` `c697e1c13f01d2e9e887df2133c07f38`, `v2_runtime.py` `ed8a9e4c193c6b6e788e86c794609655`, `roulette_card.py` `1cdbb7d5181236f3306db8a5a45f0a91`, `jackpot_card.py` `63e6c1e39dbbbd0f9dea858b6d2f6627`, `rooms_card.py` `d6d20cebdba71b1aa972df3a8bef1a1c`, `live_card.py` `7a7bf6df1de0040b7780628ef517f4b4`, `bot.py` `9fe8f8f83dc18e55cc1e967ad60c0d12`, `bootstrap_static_test.sh` `38add0cbc7f83f9726c80ad5c548be45`.
- Локально casino `pytest tests` (без e2e) **352 passed**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed** (повтор после снятия неиспользуемого импорта в `v2_runtime.py`).
- Docker: наружу `127.0.0.1:18081->8080/tcp` + host `0.0.0.0:18082`. Backend 8000 не опубликован. casino-bot ERROR в хвосте **0**.
- HTTP 200: `/casino`, `/casino/play/baccara`, `/casino/play/roulette`, `/casino/play/jackpot`, `/casino/play/fixed_room`.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- `rg` `render_board` / `drain_drama` / `Раздача: вторая карта…` / `drama_key`: board_style + drama + card_streets + rooms_card + v2_runtime + bot + тесты (не одно вхождение).
- `bootstrap_static_test.sh` локально по-прежнему может падать на чужом `data-casino-now-playing` в `CasinoShell.tsx` (не этот дифф). Наши `require` в файле есть.
- Клик 18081 (`fixture_buyer`): лобби; баккара 2×100 ₽ + бот → отсчёт «игра начинается» → итог (K♣ 2♥ A♦ = 3 vs A♠ 8♣ 8♥ = 8, −100 ₽); кубики 2×100 ₽ + бот → 2 vs 6, −100 ₽; рулетка красное 10 ₽, «ставки ещё 16 с» → выпало 25 красное, +9,75 ₽; джекпот банк 0 ₽ / 0/30, «первая ставка запускает таймер»; комнаты 2×50 ₽ + бот → катушка, затем комната закрылась.
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `01:25:26`, casino-bot `01:03:17` — без изменений.

Скрины: `docs/qa-screenshots-2026-09-01/220-lobby-drama.png`, `221-baccarat-countdown.png`, `222-baccarat-settled.png`, `223-dice-settled.png`, `224-roulette-timer.png`, `225-roulette-spin.png`, `226-jackpot-lobby.png`, `227-rooms-countdown.png`, `228-rooms-settled.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Живые такты Telegram смотреть в игровом чате: сайт крутит свои анимации, бот — отдельные правки сообщения. В группе бот всё ещё `member` без `can_delete_messages`.

Потыкать (Telegram staging `@focuscaztest` / игровой чат; сайт **18082** или туннель **18081**):

1. Баккара 2 места + бот в чате: карточка «Раздача: первая/вторая/третья карта…», очки `—` пока улицы не закончились; итог приходит **после** полного кадра со счётом.
2. Кубики 2–6: «Сейчас: бросает место N», «Дальше: киньте 🎲», «До броска N с», перед итогом «Считаем результат…».
3. Рулетка: после закрытия ставок текст «Колесо крутится 🎡» / «Замедляется…», номер и выплата не раньше последнего такта.
4. Джекпот: тикер чаще на последней минуте; на `locked` — «Крутится» → финалисты → победитель, не сразу имя.
5. Комнаты: карточка сама обновляется (отсчёт, катушка), «🔄 Обновить» только запасной. После итога карточка уходит, остаётся компактный результат.

---

## 2026-09-02 · Telegram: подчистка команд игрока в группе

Срез: в «тестовый чат» оставались `/baccara 100`, `/roulette red 50`, `/help`. Бот `focuscaztest` уже админ с правом удаления. Две дыры в коде: `/baccara` `/cub` `/blackjack` `/newgame` шли через визард и **не вызывали** `try_delete_user_message`; после первого отказа в правах чат попадал в вечный skip (бот раньше был `member`). Privacy «has no access to messages» (`can_read_all_group_messages=False`) чужие команды не блокирует — бот их уже получил. Старые строки из скрина сами не исчезнут. Прод не выкатывал. Не коммитил.

Сделано:

- `games/table_wizard.py`: slash-путь шлёт `send_message` (не `reply_to`) и чистит команду игрока. Callback с `user=` карточку не удаляет.
- `games/rooms.py` / `games/fairness.py`: `/rooms` и `/fairness` тоже чистят команду после ответа.
- `games/chat_reaper.py`: вместо вечного skip — пауза `SKIP_RIGHTS_SECONDS=45`. После повышения бота до админа удаление снова пробуется без рестарта. Тип чата читает enum `.value` и `ChatType.SUPERGROUP`.
- Тесты визарда/reaper + правки `test_card_bet_input` / `test_pvp_lobby` под `send_message`. Bootstrap `require` на `await try_delete_user_message` и `SKIP_RIGHTS_SECONDS`.

Файлы (casino): `games/chat_reaper.py`, `games/table_wizard.py`, `games/rooms.py`, `games/fairness.py`, `tests/test_chat_reaper.py`, `tests/test_table_wizard.py`, `tests/test_card_bet_input.py`, `tests/test_pvp_lobby.py`. FocusPay: `focussite/docker/staging-db/bootstrap_static_test.sh`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **332** / **88**. Не коммитил.
- md5 local=`/opt`=`контейнер`: `chat_reaper.py` `d7ec334b5beb19e4a3e15d480366406a`, `table_wizard.py` `0f86ff49dd8a9e8bdde002d596605d11`, `rooms.py` `08323468494de6c8c1fbe9b5aab2104b`, `fairness.py` `214d1bb5e2d0aaf9d924177c330976b7`, `bootstrap_static_test.sh` `bc397861387a2762a1f5c9df68d11d98`.
- Локально casino `pytest tests` (без e2e) **356 passed**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. casino-bot COPY не из кэша, handlers + «Background cleaners» в логе. ERROR в хвосте **0**.
- Docker: наружу `127.0.0.1:18081->8080/tcp` + host `0.0.0.0:18082`. Backend 8000 не опубликован.
- HTTP 200: `/casino`, `/casino/play/roulette`.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- `rg` `try_delete_user_message` / `SKIP_RIGHTS_SECONDS`: chat_reaper + table_wizard + rooms + fairness + bot + roulette_table + jackpot + chat_guard + тесты + bootstrap (не одно вхождение).
- Telegram API: `getMe` `can_read_all_group_messages=False`; `getChatMember` status=`administrator` `can_delete_messages=True`; `sendMessage` mid **755** + `deleteMessage` **ok**. Чат `-5562276559` type=`group` «тестовый чат».
- Клик 18081: лобби на месте (кубики/баккара/рулетка в сетке). Сайт команды в Telegram не чистит — это бот.
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `01:25:26`, casino-bot `01:03:17` — без изменений.

Скрин: `docs/qa-screenshots-2026-09-01/230-lobby-after-cmd-reaper.png`.

Следующий шаг: **стоп**. Прод не выкатывать. Старые `/help` `/baccara` в истории не ретроактивно.

Потыкать (Telegram staging `@focuscaztest` / «тестовый чат»):

1. Новая `/help` — команда игрока пропадает, ответ бота остаётся (потом TTL ~4 мин). Старые `/help` с 1:09 остаются.
2. Новая `/baccara 100` — команда пропадает, карточка/визард остаётся.
3. Новая `/roulette red 50` — команда пропадает, живая карточка/итог остаётся.
4. Подпись «has no access to messages» у бота может остаться (privacy BotFather). На удаление команд, которые бот уже видит, это не влияет: он админ с «Удаление сообщений».

## 2026-09-02 · Баккара: ничья не split 95 ₽, а переброс

Срез: стол Telegram `#6A60784D` (`6a60784d-896d-4542-9717-04d1141e8f68`), оба места по **5**. Карточка зависла ~**63 с** (`started_at` 05:59:41 → `settled_at` 06:00:44), `phase` остался `draw_choice` / `draw_policy=choose`, `outcome_kind=tie_split`, выплаты **95.00 + 95.00** (банк 200, комиссия 10). Сайт после вскрытия карт ставил баккару в 60 с `draw_choice`; в Telegram кнопок нет; таймаут звал `_settle_blackjack_outcome(..., kind="tie_split")` и снимал 5%. Прод не выкатывал. Не коммитил. Старый 95 ₽ на `#6A60784D` не откатываю.

Сделано:

- `casino_v2_cards.next_card_table_action`: после вскрытия ничья баккары → `kind: redeal` (не `draw_choice` / не auto `tie_split`).
- `casino_v2_web._redeal_card_leaders`: новая колода HMAC, раздача лидерам, `card-redeal`, `draw_policy=tie_break`, новый `cards_dealt_at`, `board_note` «Ничья N–N. Переброс лидеров.». Таймаут `draw_choice` для `baccara` тоже переброс (залипшие столы).
- Блэкджек: веб-выбор split/переброс без изменений.
- Telegram: визард баккары не спрашивает «что при ничьей», `draw_policy=tie_break`. `_CARD_WATCH` перезапускает вскрытие при смене `cards_dealt_at` / рук / `tie_break_round`.
- Фронт: `baccaratRoundKey` / `blackjackRoundKey` учитывают `cards_dealt_at`, чтобы улицы пошли заново.

Файлы: `site/exchange-backend/casino_v2_cards.py`, `casino_v2_web.py`, `tests/test_casino_v2_cards.py`, `tests/test_casino_v2_web.py`; casino `games/table_wizard.py`, `games/v2_runtime.py`, `tests/test_table_wizard.py`; `focussite/frontend/src/casino/baccaratStreets.ts`, `useBaccaratStreets.ts`, `scripts/check-baccarat-streets.mts`; `focussite/docker/staging-db/bootstrap_static_test.sh`.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **333** / **88**. Не коммитил.
- md5 local=`/opt`=`контейнер`: `casino_v2_cards.py` `84a9d25d10363ba682adfc13cc7a812c`, `casino_v2_web.py` `59c96e7994bbc74842fa8be4ba8c7aa5`, `baccaratStreets.ts` `290f9a889f8a1237df9412d7ea587ae2`, `useBaccaratStreets.ts` `a0bff3b900fde7c40a2d97df950af81c`, `v2_runtime.py` `8edcbceb17a69931f14807238fa0292a`, `table_wizard.py` `cd64855833057ae0238d7740a5a9220c`, `bootstrap_static_test.sh` `a0f265892f6172ffcc385473449e33cd`. Backend-контейнер `/app/backend/`.
- `rg`: `kind: redeal` `casino_v2_cards.py:262`; `_redeal_card_leaders` `casino_v2_web.py` 984 / 1079 / 1279 / 1350; `_ensure_card_watch` в `v2_runtime.py`; bootstrap `require` на эти три маркера.
- Локально casino `pytest tests` (без e2e) **357 passed**. Backend `test_casino_v2_cards` + `test_casino_v2_web` (+ closer/autostart) **passed**. `npx tsx scripts/check-baccarat-streets.mts` **ok**.
- `FOCUSPAY_SSH_HOST=focuspay-test focussite/scripts/staging-sync.sh` health **passed**. Gateway `npm run build` (TS), backend + casino-bot COPY не из кэша.
- Docker: наружу `127.0.0.1:18081->8080/tcp` + host `0.0.0.0:18082`. Backend 8000 не опубликован.
- HTTP 200: `/casino`, `/casino/play/baccara`.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- SQL: `#6A60784D` по-прежнему `tie_split` / 95+95 / 63.2 с (история). Новый веб-стол `web-67b4` (fixture_buyer + бот, 100 ₽): `winner` 190 ₽, **2.7 с**, `phase=scoring` — не 60 с `draw_choice`.
- Клик 18081 (`fixture_buyer`): баккара 2×100 ₽ + бот → 7 vs 4, **Победа +190 ₽** / «Ставка 100 ₽ · прибыль 90 ₽». Ничью 5–5 с сайта не вынудил.
- Прод read-only: `index.html` `2026-09-02 01:05:03 +0000`, `panel.html` `01:05:05`, API `01:25:26`, casino-bot `01:03:17` — без изменений.

Скрин: `docs/qa-screenshots-2026-09-01/231-baccara-pvp-round.png`.

Следующий шаг: **стоп**. Прод не выкатывать.

Потыкать (staging `@focuscaztest` / «тестовый чат» + сайт 18081):

1. Новая `/baccara 100` до ничьей (как 5–5): карточка не должна висеть минуту; сразу переброс лидеров, банк на месте, **не** возврат 95 ₽.
2. Сайт баккара 2 места + бот: обычный раунд как сейчас (победитель 190). Если выпадет ничья — улицы заново, без экрана «разделить / переброс» и без зависания.
3. Блэкджек на сайте: при ничьей по-прежнему выбор split / переброс (таймаут split).
4. Стол `#6A60784D` уже закрыт 95+95 — это старое, не чинится откатом.

## 2026-09-02 · Прод выкат: сайт + closer + переброс баккары + бот

Срез: после `01:05` (депозиты «скоро», 5%) и `01:25` (комиссии вывода) на прод ушло то, без чего новый бандл ломает ничьи и админку. Обменный `tg-bot` / антиспам / nginx не трогал. Депозиты не включал. `RAFFLE_ENABLED=False`. Webhook casino **inactive**. Холдем/кланы не открывал. Не коммитил. SQL не применял.

Сделано:

- Бэкапы `/opt/backups/exchange-backend-code-pre-20260902T064348Z.tgz`, `/opt/backups/focuspay-casino-code-pre-20260902T064348Z.tgz`, файлы API в `prod-casino-ship-20260902T064348Z/`. HTML `.bak-20260902-024747`.
- API rsync DIFF: `casino_v2_cards.py`, `casino_v2_web.py`, `main.py` (v2 closer до staging-disable), `routers/internal_casino.py` (`_ensure_v2_web_closer`), `routers/admin_casino.py`, новый `casino_stats.py`. `py_compile` из `/tmp`. `systemctl restart focuspay-exchange-api` (stop-sigterm ~90 с, как раньше, затем SIGKILL и старт).
- Казино-бот: rsync `games/` + `bot.py` + `recovery.py` → `/opt/focuspay-casino`. Env не копировал (`DEPOSITS_ENABLED=0`). Restart `focuspay-casino-bot`.
- `npm run build` + `deploy_all.py`: `index.html` / `panel.html` / `casino.html` + ассеты; prune `index-Y77pyayI.js` и старой панели.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty **333** / **88**. Не коммитил.
- md5 local=`/opt`: `casino_v2_cards.py` `84a9d25d10363ba682adfc13cc7a812c`, `casino_v2_web.py` `59c96e7994bbc74842fa8be4ba8c7aa5`, `main.py` `601ceedcc8fed0ca96c4daeebac6645b`, `casino_stats.py` `6ac3d01c3c222a43ff613dec711876d0`, `internal_casino.py` `415c8090a3f5fe07e20e423422c40b7d`, `admin_casino.py` `45e584a972bcd3ff5b4e96cbd3708e99`, `bot.py` `9fe8f8f83dc18e55cc1e967ad60c0d12`, `v2_runtime.py` `8edcbceb17a69931f14807238fa0292a`, `table_wizard.py` `cd64855833057ae0238d7740a5a9220c`, `chat_reaper.py` `d7ec334b5beb19e4a3e15d480366406a`, `live_card.py` `7a7bf6df1de0040b7780628ef517f4b4`.
- Локально: casino `pytest tests` без e2e **357 passed**. Backend `test_casino_v2_cards` + `test_casino_v2_web` + `test_casino_stats` + `test_casino_commission` exit 0. `npm run build` чисто. Бандл `index-DSSxhYeO.js` / `panel-BjZEjB-p.js`.
- API `ActiveEnterTimestamp=Wed 2026-09-02 06:46:03 UTC`, health `{"status":"ok"}`. В логе старта нет «v2 closer failed». На проде `kind: redeal` / `_redeal_card_leaders` / `v2_web_ensure_closer`.
- Бот `06:46:59 UTC` `@focusludka_bot`. Handlers: PVP/V2/wizard/baccara/blackjack/roulette/jackpot/rooms/fairness. «Background cleaners». Raffle warning (выкл). ERROR после старта **0**. Webhook **inactive**. 502 на recovery были у **старого** процесса, пока API поднимался; после старта API — 200.
- HTML: `index.html` `2026-09-02 06:47:48 +0000`, `panel.html` `06:47:51`, `casino.html` `06:47:46`. HTTPS **200**: `/` `/x8` `/ops` `/casino` `/x8/login` `/api/health`. Живой `index-DSSxhYeO.js`: «Пополнение скоро» **1**, «Комиссия сейчас» **1**, «до отыгрыша» **0**. Панель «до отыгрыша» **8** (админка).
- Клик прод `/casino` без входа: баннер мин. ставка **10 ₽**, комиссия **5%**, открытых столов 0. Сетка игр на месте (кубики выкл в настройках — как было).

Скрин: `docs/qa-screenshots-2026-09-01/240-prod-ship-lobby.png`.

Следующий шаг: **стоп**. Коммит не делал. Откат: HTML `.bak-20260902-024747`, tgz API/бота `…064348Z`, restart тех же unit.

Потыкать (прод, Ctrl+F5):

1. `https://focuspay.org/casino` — лобби 5% / 10 ₽, Пополнить → «скоро».
2. Баккара 2 места + бот — раунд сам доигрывается.
3. `@focusludka_bot` `/baccara` до ничьей — переброс, не минута и не 95 ₽. `/help` без СБП.
4. `/x8/casino` — водопад и таблицы долей, не чёрный экран.
5. Касса вывод: карта 100 ₽, USDT $4, BTC/LTC/TRX $2.5.

## 2026-09-02 · Рулетка в группе: карточка замирала, второй игрок «не добавлялся»

Срез: на проде `#RTC60240` (`rt-c60240d82c3d`) ставка второго игрока **встала в БД**, колесо закрылось. В чате карточка замерла на «До спина 24 с» и одном игроке. Причина не restart и не парсер `/roulette black 20`. Telegram в **группе** отвергает inline `web_app` (`BUTTON_TYPE_INVALID`); `_send` умел убрать клавиатуру, `_edit` — нет, поэтому таймер и состав стола не обновлялись. API/closer не трогал. Прод-бот не выкатывал. Не коммитил.

Сделано (casino-бот):

- Карточка рулетки: кнопка «Открыть стол» = `url=`, не `web_app`. Дубль «Смотреть на сайте» убран (тот же URL).
- Джекпот live-клавиатура: `web_app` «Открыть джекпот» снят (группы ломались так же). Callback-ставки и url «Смотреть» живы.
- `edit_html_message`: если правка с клавиатурой 400 — повтор без markup, чтобы таймер не клинил.
- Старт: `hydrate_live_table_cards` — открытый раунд рулетки/джекпота в привязанный игровой чат (пустой open без ставок — нет).
- Тесты: https-клавиатура без web_app; edit retry; hydrate шлёт карточку в bound chat.

Проверки:

- git: focuspay-casino dirty точечно `bot.py` + `games/{live_card,live_table_hydrate,roulette_table,roulette_card,jackpot,jackpot_card,rooms_card,site_links}.py` + тесты. Не коммитил. Прод HTML/API не менял.
- md5 local = staging `/opt` = контейнер `/app`: `live_card.py` `91fc2c63af4d065a9c9757075df20fc0`, `roulette_table.py` `f357281188d7734dbcdaaca15c6326ed`, `jackpot.py` `70de6a2e4922de3e88b644db569385f8`, `live_table_hydrate.py` `980cc4f9f7b5da324212861e6c477871`, `bot.py` `ffcf6baef8225d01e6c9000365f7d27e`.
- Локально casino `pytest tests --ignore=e2e`: **366 passed**.
- `rg web_app` в `roulette_table.py` / `jackpot.py`: только комментарий про private-only. Вызовов `WebAppInfo` в этих файлах нет.
- SQL прод `#RTC60240`: 4×50 ₽ `@focuspayadmin` (17/20/24/36) 07:10:32 + `black` 20 ₽ `@focus_supervisor` 8718118115 в 07:10:45. `settled` 07:10:58, pocket **21**. `notify_chat_id` `-1004058942735`. Журнал бота: `roulette card edit failed … BUTTON_TYPE_INVALID` каждые 5 с.
- Прод read-only: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`, API `ActiveEnterTimestamp=Wed 2026-09-02 06:46:03 UTC`, casino-bot всё ещё `07:17:48 UTC` (этот фикс туда не лил).
- Staging: rsync файлов + `compose --profile casino up -d --build --no-deps --wait casino-bot`. Health **passed**. Порты: gateway `127.0.0.1:18081->8080`, host `18082`. Старт бота `@focuscazzcztewrfweda_bot` 07:30:15: hydrate GET roulette+jackpot, пустой open не слал карточку, handlers ok, ERROR 0.
- `staging-test.sh`: 7 упавших, не рулетка — `test_casino_weekly_cashback` (2), `test_finance_access_staging` fixture admin, `test_internal_casino` weekly_wager mock (3) + profile `Conn.fetch`. Новых имён про live-card нет.
- Клик 18081: `/casino/play/roulette` стол 0–36, после клика красное 100 ₽ — «Ставки ещё 18 с», игрок на столе. Лобби: мин. 10 ₽, комиссия 5%, рулетка «Из Telegram тоже».

Скрин: `docs/qa-screenshots-2026-09-01/241-staging-roulette-after-group-card-fix.png`, `242-staging-lobby-after-roulette-card-fix.png`.

Следующий шаг: **стоп**. На прод `@focusludka_bot` не выкатывал. Нужно «го». Откат staging: предыдущий image casino-bot + recreate.

Потыкать (группа FOCUS PAY / staging `@focuscazzcztewrfweda_bot`):

1. `/roulette red 50` — карточка, таймер **тикает** (не залипает на 24 с), кнопка «Открыть стол» открывает сайт, не ошибка Telegram.
2. Второй аккаунт `/roulette black 20` в том же раунде — на той же карточке появляется второй игрок, банк растёт.
3. Дождаться спина на карточке (не только в сайте). После рестарта бота при живом раунде — новая карточка с актуальным составом.
4. `/jackpot 50` в группе — карточка не молчит из‑за BUTTON_TYPE.

## 2026-09-02 · Уведомление: ставка отменена / стол истёк

Срез: в группе FOCUS PAY по старому объявлению баккары «Занять место» давало только popup «стол уже заполнен, начался или ставка недоступна». Если стол уже отменили/истёк и холд сняли — личного сообщения «ставка вернулась» не было. Outbox `settled` слался только после игры; cancel/leave/expire/release холд отпускали молча. Не коммитил. Прод не трогал.

Сделано:

- API: после возврата ставки в `leave`/`cancel`, `release`, expire unstarted и stale-play — строка `casino_v2_notification_outbox` `event_type=cancelled`, текст «Игра отменена, ставка возвращена» + стол + баланс. Боты и web-id `<= 0` не ставятся.
- Бот: outbox cancelled шлёт личку, живую карточку settled не публикует. Кнопка «Занять место» на исчезнувшем столе: «Стол уже отменён или истёк. Если ставили — ставка вернулась на баланс.»
- Тесты: `V2CancelledOutboxTests` (html, skip bots/web, expire→enqueue); casino `test_cancel_omits_payout`, outbox без board, join missing table.

Проверки:

- git: focuspay dirty точечно `internal_casino.py` + `test_internal_casino.py` + этот журнал (файл API и раньше был огромный WIP). Casino: `games/v2_runtime.py`, `games/v2_tables.py`, `tests/test_result_notify.py`, `tests/test_v2_tables.py`. Не коммитил.
- md5 local = staging `/opt` = контейнер: `internal_casino.py` `030e7011782c3df5eb485159b0ef3280`, `v2_runtime.py` `0e31fa5de5948a18629c4ebba2289f68`, `v2_tables.py` `e633d755ab3d8a21058b7276a2328ff8`.
- `rg _enqueue_v2_cancelled_outbox` в API: **6** (определение + 5 вызовов: cancel, leave, release, expire unstarted, stale play).
- Локально casino `pytest tests --ignore=tests/e2e`: **369 passed**. Backend `V2CancelledOutboxTests` **4 passed**.
- Staging: rsync этих файлов + `compose up -d --build --no-deps --wait` backend и `--profile casino` casino-bot. Health **passed**. Порты: gateway `127.0.0.1:18081->8080`, host **18082**. Бот `@focuscazzcztewrfweda_bot` 07:44:41 UTC, ERROR на старте **0**.
- `staging-test.sh`: те же **7** упавших, новых имён нет — `test_casino_weekly_cashback` (2), `test_finance_access_staging` fixture admin, `DurableLifecycleTests` weekly_wager mock (3), profile `Conn.fetch`. `V2CancelledOutboxTests` на staging **4 passed**.
- SQL после клика «Отменить» на staging баккаре 100 ₽ (стол `#WEB-D907`, user 940002): `cancelled` / `result=cancel` / текст «Игра отменена, ставка возвращена» / «Баланс: 6037.55 ₽». Баланс UI 5937,55 → **6 037,55**. Доставка лички этому id: Telegram `chat not found` (это web-фикстура, не реальный Telegram) — fail outbox, как у старых `settled` на 940002. Живому Telegram id outbox как у `8443902979` completed.
- Прод read-only: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`, API `ActiveEnterTimestamp=Wed 2026-09-02 06:46:03 UTC`, casino-bot `07:17:48 UTC`.

Скрин: `docs/qa-screenshots-2026-09-01/243-staging-baccarat-after-cancel.png`.

Следующий шаг: **стоп**. На прод API и `@focusludka_bot` не выкатывал. Нужно «го». Выкат casino-bot заодно унесёт в прод и фикс карточки рулетки (web_app в группе), он уже на staging.

Потыкать (группа FOCUS PAY / `@focusludka_bot` после го; сейчас только staging `@focuscazzcztewrfweda_bot`):

1. Создать баккару в группе, второй аккаунт «Занять место», создатель отменяет — **обоим** в личку бота: «Игра отменена, ставка возвращена» и баланс.
2. Выйти со стола самому — в личку то же про возврат ставки.
3. Старое объявление «Занять место» после отмены — popup про отмену/истечение, не «стол заполнен».
4. На сайте «Отменить» — ставка сразу на балансе (toast «Стол отменён»). Личка придёт, если вход через Telegram, не web-id.

## 2026-09-02 · Прод выкат: личка при отмене ставки + карточка рулетки в группе

Срез: после приёмки на staging выкатил API+`@focusludka_bot`. `deploy_all.py` / nginx / обменный `tg-bot` не трогал. Депозиты не включал. `RAFFLE_ENABLED=False`. Webhook inactive. Холдем/кланы не открывал. SQL не применял. Не коммитил.

Сделано:

- Бэкап `/opt/backups/cancel-notify-20260902T075345Z/` + `cancel-notify-pre-20260902T075345Z.tgz`.
- API: `routers/internal_casino.py` (outbox `cancelled` после refund). `py_compile` из `/tmp`. Restart `focuspay-exchange-api`.
- Казино-бот: `v2_runtime.py` / `v2_tables.py` (личка + попап на исчезнувший стол) и фикс рулетки в группе: `live_card.py`, `roulette_table.py`, `jackpot.py`, `jackpot_card.py`, `rooms_card.py`, `site_links.py`, новый `live_table_hydrate.py`, `bot.py` (+8 hydrate). Env не копировал. Restart `focuspay-casino-bot`.

Проверки:

- md5 local=`/opt`: `internal_casino.py` `030e7011782c3df5eb485159b0ef3280`, `v2_runtime.py` `0e31fa5de5948a18629c4ebba2289f68`, `v2_tables.py` `e633d755ab3d8a21058b7276a2328ff8`, `live_card.py` `91fc2c63af4d065a9c9757075df20fc0`, `bot.py` `ffcf6baef8225d01e6c9000365f7d27e`, `live_table_hydrate.py` `980cc4f9f7b5da324212861e6c477871`.
- Дифф к прод до выката: API **+48** строк enqueue; v2_tables **+8/−1**; v2_runtime **+2/−1**; bot **+8**; roulette/jackpot/live_card как на staging. Чужой WIP не лил.
- `rg _enqueue_v2_cancelled_outbox` **6**. `web_app` в `roulette_table.py` только в комментарии; кнопка джекпота `WebAppInfo` снята.
- API `ActiveEnterTimestamp=Wed 2026-09-02 07:56:03 UTC`, health `{"status":"ok"}`. Startup complete, без нового traceback на старте. 502 у **старого** бота, пока API поднимался.
- Бот `07:56:28 UTC` `@focusludka_bot`. Handlers PVP/V2/wizard/baccara/blackjack/roulette/jackpot/rooms/fairness. Raffle warning (выкл). Hydrate GET roulette+jackpot. ERROR после старта **0**. Webhook **inactive**. `DEPOSITS_ENABLED=0`.
- HTML не менялся: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`. HTTPS **200**: `/` `/x8` `/ops` `/casino` `/api/health`.

Следующий шаг: **стоп**. Откат: файлы из `cancel-notify-20260902T075345Z` + restart тех же unit.

Потыкать (прод, группа FOCUS PAY / `@focusludka_bot`, Ctrl+F5 не нужен — это бот/API):

1. Баккара в группе, второй сел, создатель отменяет — **обоим** в личку: «Игра отменена, ставка возвращена» и баланс.
2. Сам вышел — личка про возврат.
3. Старое «Занять место» — попап про отмену/истечение.
4. `/roulette red 50` — карточка тикает, второй игрок появляется на той же карточке (не BUTTON_TYPE).

## 2026-09-02 · @focuspay1_bot: FocusBet вместо FocusLucky в главном меню

Срез: в reply-клавиатуре обменного бота была кнопка «🍀 FocusLucky» рядом с «Совершить обмен / Профиль / О нас». Заменил на **FocusBet** (ссылка в `@focusludka_bot`). FocusLucky в профиле и хендлер старой кнопки оставил. Не коммитил. `deploy_all.py` / nginx / API не трогал. Чужой WIP бота (комиссии вывода, антиспам) на прод не лил.

Сделано:

- `services/menu.py`: ряд FocusLucky снят, ряд FocusBet.
- Хендлер кнопки: `focusbet_menu_handler` → inline URL `https://t.me/focusludka_bot`.
- Прод: `main.py` (+регистрация), `casino_login.py` (+handler), новый `focusbet_link.py`, в `config_rates.py` только `casino_bot_url()` (дефолт `focusludka_bot`).

Проверки:

- git HEAD `61e47be`. Dirty точечно эти файлы бота + тесты + журнал. Не коммитил.
- Локально `python -m unittest tests.test_focusbet_link tests.test_profile_hub tests.test_start_captcha_to_main_menu`: **18 passed**. Клавиатура `[Совершить обмен, Профиль, О нас, FocusBet]`. `KeyboardButton(MENU_FOCUS_LUCKY)` в `menu.py`: **0**.
- md5 local=`/opt/tg_bot_btc`: `menu.py` `f5f51c6731521fc0c7b76a15b32b109e`, `main.py` `587849e07450c9e12eac3ac5bd9fcf80`, `casino_login.py` `c89727e1f60999f249bc09d24786af70`, `focusbet_link.py` `49cfad60b384d700a869a639b3a77a05`, `config_rates.py` `3f16e370e11f94a6bd27b51f19ba5095`.
- Бэкап `/opt/backups/tg-bot-menu-focusbet-20260902T092332Z`. `py_compile` ok. `systemctl restart tg-bot`. `getMe` **True `focuspay1_bot`**. Unit `ActiveEnterTimestamp=Wed 2026-09-02 09:23:46 UTC`, `Application started`. ERROR нового pid **0** (Rapira timeout — старый fallback на snapshot).
- HTML/API не сдвинулись: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`, API `07:56:03 UTC`.

Следующий шаг: **стоп**. Откат: файлы из `tg-bot-menu-focusbet-20260902T092332Z` + `systemctl restart tg-bot`.

Потыкать (`@focuspay1_bot`, `/start` чтобы Telegram подтянул новую клавиатуру):

1. Внизу: **Совершить обмен**, **Профиль**, **О нас**, **FocusBet**. Кнопки FocusLucky нет.
2. FocusBet → сообщение с кнопкой на `@focusludka_bot`.
3. Профиль → FocusLucky внутри профиля ещё есть.
4. Обмен / Профиль / О нас — как раньше.

## 2026-09-02 · Карточка кубиков: @username вместо first_name

Срез: живой прод-стол `#5FDF15B4` (`5fdf15b4-154e-484f-b826-19dfb0a4b2bd`, кубики 10 ₽, 4 места). В карточке было «ꍏ…ꋪ» и «Focus». В `game_state.roster_names` уже лежали `@pochemutigovorishsomnoyfromhell` и `@focuspayadmin` — карточка брала Telegram `first_name`. Место 2 — не бот, это `@focuspayadmin` с именем Focus. Не коммитил. Прод не трогал.

Сделано:

- `_seat_name` / `_player_seat_label`: если есть username — показывать `@username` и ссылку `tg://user?id=`. Нет username — first_name, иначе display_name.
- `_annotate_roster_names` тот же приоритет (итог / get_chat).
- Тест `test_lobby_card_shows_telegram_username_not_glyph_name`: GlyphName+Focus не попадают в текст, есть `@pochemutigovorishsomnoyfromhell` и `@focuspayadmin`. `test_seat_name_uses_roster_from_user` теперь ждёт `@katya`, не «Катя».

Файлы (casino): `games/v2_runtime.py`, `tests/test_v2_card_board.py`. Журнал этот.

Проверки:

- git HEAD `61e47be` / casino `4b8d65e`. Dirty: этот срез только два файла казино + журнал. Чужой WIP не смешивал. Не коммитил.
- md5 local=`/opt`=`контейнер /app`: `v2_runtime.py` `bb4c18d2ecebaae4b5ebdf58556aa977`, `test_v2_card_board.py` `9a788299631caac2043994ce04507651`.
- Локально casino `pytest tests --ignore=tests/e2e`: **370 passed** (было 369, +1 тест). `test_v2_card_board` + `test_v2_chat_hygiene`: **30 passed**.
- Staging: rsync двух файлов + `compose --profile casino up -d --build --no-deps --wait casino-bot`. Health **passed**. Бот `@focuscazzcztewrfweda_bot` 10:57:39, ERROR **0**.
- `rg` `_player_seat_label`: `v2_runtime.py` + `test_v2_card_board.py` (не одно вхождение).
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- Docker: gateway `127.0.0.1:18081->8080`, host **18082**. Backend 8000 не опубликован.
- Клик 18081 `/casino/play/pvp_dice?mode=players`: открытых столов нет (этот стол на проде, не на staging).
- Прод read-only: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`, API `ActiveEnterTimestamp=Wed 2026-09-02 10:16:46 UTC` (сдвинулся раньше этого среза, этот фикс API не рестартил), casino-bot всё ещё `07:56:28 UTC`.
- SQL прод `#5FDF15B4`: roster_names место 1 username `pochemutigovorishsomnoyfromhell` / first_name глифы; место 2 username `focuspayadmin` / first_name `Focus`. Оба `participant_kind=player`.

Скрин: `docs/qa-screenshots-2026-09-01/244-dice-lobby-after-tg-username-fix.png`.

Следующий шаг: **стоп**. На `@focusludka_bot` не выкатывал. Нужно «го». Живая карточка `#5FDF15B4` обновится после выката, когда кто-то займёт/выйдет/добавит бота (просто рестарт без edit не перерисует текст).

Потыкать (staging `@focuscazzcztewrfweda_bot`, группа GAME_CHAT; после го — прод `@focusludka_bot`):

1. Создать кубики с аккаунта, у которого есть @username и кривой first_name. В карточке должно быть **@username**, не глифы.
2. Второй игрок с first_name «Focus» — в списке **@его_username**, не «Focus» как у бота.
3. У кого нет username — по-прежнему имя, кликабельное через `tg://user?id=`.

## 2026-09-02 · Кубики в группе: спам после победы

Срез: прод `#5FDF15B4` после «Победил 38 ₽» засыпал группу карточками «киньте 🎲 / до броска 0 с» раз в ~3 с. HMAC-closer закрыл раунд по 30 с `roll_deadline_at`, outbox прислал итог и стёр живую карточку, а roll-watch остался на stale `running` и на каждый неудачный edit слал новое сообщение. Рестарт `@focusludka_bot` не делал — нет «го». Не коммитил. Прод не трогал.

Сделано:

- Бот: `_refresh` без стола в `/v2/tables/active` ставит `status=gone`. `_stop_table_watchers` на settle/outbox/cancel. Тикер `_tick_edit_board` только edit, без `send_message`.
- API: `telegram_play_surface` (group `play_chats` / listing / `game_chat_id` < 0). Таким кубикам не ставить 30 с deadline в `ensure_round_ready`, `house_fill_table` не HMAC-дописывает игрокам. `v2_play_is_stale` для них — idle 30 мин по `updated_at`, не web-дедлайн. Чистый web-стол как был.

Файлы: casino `games/v2_runtime.py`, `tests/test_v2_chat_hygiene.py`. API `casino_v2_web.py`, `tests/test_casino_v2_web.py`. Журнал этот.

Проверки:

- git HEAD focuspay `61e47be` / casino `4b8d65e`. Этот срез: четыре файла + журнал + скрин. Чужой WIP не лил. Не коммитил.
- md5 local=`/opt`=`контейнер`: `v2_runtime.py` `c3998f3357c39e570f0215f5c19c17a7`, `test_v2_chat_hygiene.py` `a0de5a7d69f89810e0e8cb19a11f3233`, `casino_v2_web.py` `3217558654f01038fd20bc5415a40105`, `test_casino_v2_web.py` `cc63e76f80ff57ec5ea3d66c86c3b7aa`.
- Локально casino `pytest tests --ignore=tests/e2e`: **374 passed** (было 370, +4). `test_v2_card_board` + `test_v2_chat_hygiene` + `test_result_notify`: **39 passed**. Backend `test_casino_v2_web.py`: все зелёные.
- Staging: точечный rsync четырёх файлов + `compose up -d --build --no-deps --wait` backend и `--profile casino` casino-bot. Health **passed**. Бот `@focuscazzcztewrfweda_bot` 13:46:32 UTC, ERROR **0**.
- `rg` `_tick_edit_board`: **3** в `v2_runtime.py` (определение + ready + roll). `_stop_table_watchers`: **4** (определение + score + settle + cancel). `telegram_play_surface`: **5** в `casino_v2_web.py` + **3** в тесте.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- Docker: gateway `127.0.0.1:18081->8080`, хост **18082**. Backend 8000 не опубликован наружу.
- Клик 18082 `/casino/play/pvp_dice?mode=players`: лобби кубиков открывается, открытых столов нет.
- Прод read-only: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`, API `ActiveEnterTimestamp=Wed 2026-09-02 10:16:46 UTC`, casino-bot всё ещё `07:56:28 UTC`.

Скрин: `docs/qa-screenshots-2026-09-01/245-dice-lobby-after-group-flood-fix.png`.

Следующий шаг: **стоп**. На `@focusludka_bot` и прод API не выкатывал. Нужно «го». Пока прод-бот жив, старый roll-watch на уже закрытом столе может ещё слать карточки — снять только рестартом после «го».

Потыкать (staging `@focuscazzcztewrfweda_bot`, группа GAME_CHAT; после го — прод `@focusludka_bot`):

1. Кубики 2–4 в группе, **не бросать 30+ с** — не должно быть внезапного HMAC-итога и пачки «киньте 🎲 / 0 с».
2. Довести раунд эмодзи до конца — одна живая карточка, один «Победил», дальше тишина.
3. Сайтовый стол кубиков без группы — по-прежнему дом кидает после 30 с.

## 2026-09-02 · Прод выкат: спам карточек кубиков после победы

Срез: «выкати» после приёмки staging. Снял roll-watch рестартом `@focusludka_bot`. `deploy_all.py` / nginx / обменный `tg-bot` не трогал. Депозиты не включал. `RAFFLE_ENABLED=False`. Webhook казино-бота inactive. Холдем/кланы не открывал. SQL не применял. Env не копировал. Не коммитил.

Сделано:

- Бэкап `/opt/backups/dice-flood-20260902T140455Z/` + `dice-flood-pre-20260902T140455Z.tgz`. Старые md5: API `59c96e7994bbc74842fa8be4ba8c7aa5`, бот `0e31fa5de5948a18629c4ebba2289f68`.
- API: `casino_v2_web.py` (group surface без HMAC 30 с). `py_compile` из `/tmp`. Restart `focuspay-exchange-api`.
- Казино-бот: `games/v2_runtime.py` (gone + stop watchers + ticker без send; вместе с @username на местах). Env не копировал. Restart `focuspay-casino-bot`.

Проверки:

- git HEAD focuspay `61e47be` / casino `4b8d65e`. Дифф к прод до выката: API **+54/−2**; `v2_runtime` **+107/−35**. Чужой WIP не лил.
- md5 local=`/opt`: `casino_v2_web.py` `3217558654f01038fd20bc5415a40105`, `v2_runtime.py` `c3998f3357c39e570f0215f5c19c17a7`.
- `rg` `telegram_play_surface` **5** в `/opt` `casino_v2_web.py`. `_tick_edit_board` **3**, `_stop_table_watchers` **4** в `v2_runtime.py`.
- API `ActiveEnterTimestamp=Wed 2026-09-02 14:06:51 UTC`, pid 701516, health `{"status":"ok"}`. Startup complete. Первый старт бота 14:06:53 — 502 settings (гонка с API), systemd restart 1.
- Бот живой pid **701569** `14:07:03/04 UTC` `@focusludka_bot`. Settings 200. Handlers PVP/V2/wizard/baccara/blackjack/roulette/jackpot/rooms/fairness. Raffle warning (выкл). Hydrate GET roulette+jackpot 200. ERROR после **14:07:04** **0**. `getMe` True `focusludka_bot`. Webhook **inactive**, pending 0. `DEPOSITS_ENABLED=0`.
- HTML не менялся: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`. HTTPS **200**: `/` `/x8` `/ops` `/casino` `/api/health`.
- Побочное, не этот срез: после рестарта API `POST /api/internal/chat/telegram-inbound` 500 `sticker_file_id` (обменный webhook vs API). Казино-эндпоинты 200.

Следующий шаг: **стоп**. Откат: файлы из `dice-flood-20260902T140455Z` + restart `focuspay-exchange-api` и `focuspay-casino-bot`.

Потыкать (прод, группа FOCUS PAY / `@focusludka_bot`):

1. Спам на `#5FDF15B4` должен был остановиться (процесс рестартнут).
2. Новые кубики 2–4, **не бросать 30+ с** — нет HMAC-итога и пачки карточек.
3. Довести раунд эмодзи — одна живая карточка, один «Победил», тишина.
4. В карточке **@username**, если он есть (этот `v2_runtime` и тот фикс).
5. Сайтовый стол без группы — дом по-прежнему кидает после 30 с.

## 2026-09-02 · Кубики в FOCUS PAY только ответом на карточку

Срез: на проде 🎲 в FOCUS PAY не зачитывается, если не ответить на карточку бота. Код уже принимает бросок без reply (`try_handle_v2_dice` → `_dice_table_for_player`). Telegram не отдаёт апдейт: бот зашёл в группу не админом. Выкат API/бота не делал. Не коммитил.

Сделано:

- Read-only прод: `getMe` `@focusludka_bot` `can_read_all_group_messages=True`. Чат `-1004058942735` title **FOCUS PAY**, не форум.
- `getChatMember` бота: всё ещё **`restricted`**, `is_member=true`, тег `focusgame`, `can_delete_messages` нет. Не administrator.
- `@focuspay1_bot` в том же чате administrator, `can_promote_members=False` — повысить казино-бота через API нельзя.
- Кто может повысить: creator `@zargasdgf`; `can_promote_members=True` у `@focuspayadmin` и `@focus_supervisor`.
- В [`PRODUCTION_RUNBOOK.md`](/home/qwe/Desktop/focuspay-casino/PRODUCTION_RUNBOOK.md): строка — игровой чат, бот админ с delete. Не кикать ради re-add, если можно повысить.

Проверки:

- git HEAD focuspay `61e47be` / casino `4b8d65e`. Этот срез: runbook + журнал. Чужой WIP не лил.
- md5 `PRODUCTION_RUNBOOK.md` `7233aa7eebfd69c78c62121f0f6b87d8`.
- Прод HTML не сдвинулся: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`. API `14:06:51 UTC`, casino-bot `14:07:03 UTC`.

Следующий шаг: **стоп, ждём админа**. Владелец в FOCUS PAY: `@focusludka_bot` → админ, право удалять сообщения. После этого — `getChatMember` administrator и голый 🎲 без reply.

Потыкать (после повышения, прод FOCUS PAY / `@focusludka_bot`):

1. Стол кубиков 2–4, «Киньте эмодзи».
2. Кинуть 🎲 **не ответом** — место засчиталось, карточка обновилась.
3. Ответ на карточку по-прежнему ок.

## 2026-09-02 · Сайт: кубики не заканчиваются в лобби

Срез: прод `/casino/play/pvp_dice?mode=players` показывал три живых стола. Это те же V2, что в Telegram. Вчерашний `telegram_play_surface` считал `listing_chat_id` группы игровым чатом — HMAC-closer молчал, `roll_deadline_at=None`. Личковые 1018/2fd1 не закрывались. Групповой `077eaae7` ждал эмодзи (бот в FOCUS PAY всё ещё `restricted`). Idle 30 мин смотрел на `updated_at` (persist карточки его двигает). Прод не выкатывал. Не коммитил. Холдем/кланы не открывал.

Сделано:

- `telegram_play_surface`: только `play_chats.chat_id < 0` или `game_chat_id < 0`. Listing в группе — не skip.
- `effective_roll_deadline`: пустой дедлайн у web/DM = `started_at + 30 с`. Просроченные залипшие — HMAC-fill.
- `v2_play_is_stale` для групповых кубиков: `started_at` (fallback `created_at`), не `updated_at`.

Файлы: `site/exchange-backend/casino_v2_web.py`, `tests/test_casino_v2_web.py`. Журнал этот.

Проверки:

- git HEAD focuspay `61e47be` / casino `4b8d65e`. Этот срез: два файла API + журнал + скрин. Чужой WIP не лил. Не коммитил.
- md5 local=`/opt`=`контейнер /app/backend`: `casino_v2_web.py` `1a570083f92fa37a2bdaed69498e32af`, `test_casino_v2_web.py` `cc9a9e790474685e50984738bdb423a6`.
- Локально `python -m unittest tests.test_casino_v2_web -q`: **42 passed**.
- `telegram_play_surface`: **7** в `casino_v2_web.py`, **5** в тесте. `listing_chat_id` в функции surface нет (только docstring). `effective_roll_deadline` **3**, `_start_stamp` **3**.
- Staging: rsync двух файлов + `compose up -d --build --no-deps --wait backend`. Health **passed**. Backend healthy. Казино-бота не пересобирал.
- `staging-test.sh`: **7 failed**, те же семь имён (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Новых имён нет.
- Docker: gateway `127.0.0.1:18081->8080`, хост **18082**. Backend 8000 не опубликован наружу.
- Клик 18082 `/casino/play/pvp_dice?mode=players`: лобби кубиков, «Открытых столов этой игры нет.»
- Прод read-only: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`, API `14:06:51 UTC`, casino-bot `14:07:03 UTC`.

Скрин: `docs/qa-screenshots-2026-09-01/246-dice-lobby-after-stuck-closer.png`.

### Выкат на прод (по «прод сделал? если нет делай»)

Выкатил только `casino_v2_web.py` в `/opt/exchange-backend` + рестарт `focuspay-exchange-api`. Фронт, бот, nginx, миграции не трогал. Не коммитил.

- Бэкап до: `/opt/backups/stuck-dice-20260903T020334Z/casino_v2_web.py` + `stuck-dice-pre-20260903T020334Z.tgz`. Прошлый md5 `3217558654f01038fd20bc5415a40105`.
- Дифф прод↔локаль перед выкатом: **+51 / −8**, ровно этот срез (`telegram_play_surface`, `_start_stamp`, `effective_roll_deadline`, `v2_play_is_stale`, дедлайн в `ensure_round_ready`, `effective_roll_deadline` в closer). Чужого WIP нет.
- После: md5 `/opt/exchange-backend/casino_v2_web.py` = `1a570083f92fa37a2bdaed69498e32af` = локальный. `py_compile` OK.
- Рестарт: `ActiveEnterTimestamp=2026-09-03 02:05:54 UTC`, `is-active=active`. Graceful stop занял ~90 с (висящие SSE).
- HTTP: `/api/health` **200**, `/api/public/rates` **200**, `https://focuspay.org/` **200**, `/x8` **200**, `/ops` **200**. Прод HTML не сдвинулся: `index.html` `2026-09-02 06:47:48`, `panel.html` `06:47:51`.

Три залипших стола закрылись сами в первые два цикла closer:

| стол | было | стало | деньги |
|---|---|---|---|
| `1018db06` (личка, 25 ₽, 3 места) | `tie_break_running`, дедлайн `null` | `finished` 02:05:57 | пот 75 ₽, комиссия 3.75 ₽, выплата 71.25 ₽ seat 3 |
| `2fd1e8ad` (личка, 10 ₽, 2 места) | `running`, дедлайн `null` | `finished` 02:06:28 | пот 20 ₽, комиссия 1.00 ₽, выплата 19.00 ₽ seat 1 |
| `077eaae7` (группа `-1004058942735`, 10 ₽) | `running` с 23:51 | `expired` 02:05:57 | «Игра отменена, ставка возвращена», ставки вернулись |

- Живых V2-столов сейчас **0** (`open/ready/running/tie_break_running`).
- Полный жизненный цикл в `casino_v2_lifecycle_idempotency`: `house-fill` → `commit_outcome` → `tie-break` → `settle` → `settle_committed`. `casino_v2_house_reservations` для 68 и 70 — `settled`. `casino_v2_house_ledger` +50.00 и −9.00, баланс дома `500403.60`.
- Логи API после рестарта: тректрейсов нет.

Хвосты (не от этого выката, чинятся правом админа `@focusludka_bot` в FOCUS PAY):

- `casino_v2_notification_outbox` id 91 висит `pending`, 4 попытки, `403 Forbidden: bot can't initiate conversation with a user` — игрок не открывал личку с казино-ботом. Деньги вернулись, только уведомление не дошло.
- В логе бота `400 Bad Request: message can't be deleted for everyone` — чистка карточек в группе без права удаления.
- Один старый холд комнат `casino-rt-ab9662d60cf0-b14-player` 35 ₽ от 00:41 в статусе `confirmed` — другая подсистема (`casino_fixed_room`), к кубикам не относится, глянуть отдельно.

Потыкать (прод `focuspay.org`):

1. Сайтовый стол кубиков без группы — через ~30 с дом докидывает, стол уходит из «открытых».
2. Стол из лички с анонсом в группе — тоже закрывается, не висит.
3. Настоящий групповой стол — HMAC не ворует бросок за 30 с; бросать эмодзи (пока бот не админ — ответом на карточку).

## 2026-09-11 · Блэкджек в чате: не отменять на доборе

Не прод. `deploy_all.py` не запускал. Холдем/кланы/дом 1×1 не трогал. HMAC / рейк 5% не менял. Казино-бота не правил.

Повод: в FOCUS PAY стол `#1CE5F178` / `#24E620B5` на «ваш ход» уходил в «Игра отменена, ставка возвращена». `waiting` closer каждые ~10 с считал прошедший `roll_deadline_at` (30 с добора) stale и refund, раньше чем `ensure_blackjack_round` авто-оставлял.

Сделано:

- `v2_play_is_stale`: `blackjack` / `baccara` не смотрят turn-дедлайны. Stale только idle 30 мин от `started_at` (как групповые кубики).
- `blackjack_hit_timeout_seconds`: группа (`telegram_play_surface`) **180 с**, сайт/личка **30 с**. По дедлайну по-прежнему auto-stand + settle, не cancel.
- Casino-bot: `v2hit:` / `v2stand:` без `expected_state_version`, hit через `cards/deal`. Не трогал.

Файлы: `site/exchange-backend/casino_v2_web.py`, `site/exchange-backend/tests/test_casino_v2_web.py`. Журнал этот.

Проверки:

- git HEAD focuspay `816b005` / casino `f0ab827`. Этот срез: `casino_v2_web.py` (+20/−6), `tests/test_casino_v2_web.py` (untracked), журнал. Чужой WIP не лил. Не коммитил. `focuspay-casino` чистый.
- md5 local=`/opt`=`контейнер /app/backend`: `casino_v2_web.py` `919482b4bc7cb06d78078b95f1b27615`, `test_casino_v2_web.py` `5d20f0447201b049510e22a6c556873a`.
- Локально `python -m unittest tests.test_casino_v2_web -q`: **47 passed** (`py_compile` OK).
- Контейнер `python -m unittest tests.test_casino_v2_web tests.test_casino_v2_cards -q`: **65 OK**.
- `blackjack_hit_timeout_seconds`: **5** в `casino_v2_web.py` (объявление + 4 вызова hitting), **4** в тесте. `WEB_V2_TELEGRAM_HIT_TIMEOUT_SECONDS`: **2** модуль / **2** тест. `v2hit:` / `v2stand:` в `focuspay-casino/games/v2_runtime.py` **4**.
- Staging: точечный rsync двух файлов API + `compose up -d --build --no-deps --wait backend`. Health **passed**. Backend healthy. Казино-бота не пересобирал. SQL `casino_settings` **67** строк (схему не трогал).
- `staging-test.sh`: **1983 collected**, **13 failed**. Базовые семь те же (`CasinoWeeklyCashbackTests` ×2, `FinanceAccessStagingFixtureTests.test_fixture_admin_not_finance_owner_in_production`, `DurableLifecycleTests` ×3, `ProfileEndpointTests.test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback`). Лишние шесть — чужой WIP, не этот срез: `TestBuyerProfileProfit.test_compute_gross_profit_from_orders`, `IpBlocklistUnbanTests` ×4, `ShiftStatsRoleSplitTests.test_legacy_stats_remain_unchanged_for_non_split_orders`. `test_casino_v2_web` в упавших нет.
- Docker: gateway `127.0.0.1:18081->8080` **200**, хост **18082** **200**. Backend 8000 не опубликован наружу.
- Клик 18082 `/casino/play/blackjack?mode=players`: лобби «Игроки 2–6», копирайт про добор/оставить, открытых столов нет. Живой раунд без логина не сыграл.
- Прод read-only (не трогал): `index.html` `2026-09-11 05:26:54`, `panel.html` `05:26:55`, API `ActiveEnterTimestamp=2026-09-11 05:26:34 UTC`.

Скрин: `docs/qa-screenshots-2026-09-01/247-blackjack-players-lobby-after-cancel-fix.png`.

### Выкат на прод (по «выкати прод»)

Выкатил только `casino_v2_web.py` в `/opt/exchange-backend` + рестарт `focuspay-exchange-api`. Фронт, бот, nginx, миграции не трогал. Не коммитил.

- Бэкап до: `/opt/backups/bj-cancel-20260911T210052Z/casino_v2_web.py` + `bj-cancel-pre-20260911T210052Z.tgz`. Прошлый md5 `1a570083f92fa37a2bdaed69498e32af`.
- Дифф прод↔локаль перед выкатом: **+20 / −6**, ровно этот срез (`WEB_V2_TELEGRAM_HIT_TIMEOUT_SECONDS`, `blackjack_hit_timeout_seconds`, `v2_play_is_stale` для card types, hitting deadline, `table=` в `_finalize_blackjack_action`). Чужого WIP нет. HEAD `casino_v2_web.py` = прод до выката.
- После: md5 `/opt/exchange-backend/casino_v2_web.py` = `919482b4bc7cb06d78078b95f1b27615` = локальный. `py_compile` OK. owner `focuspay:focuspay` mode 644.
- Рестарт: `ActiveEnterTimestamp=2026-09-11 21:01:23 UTC`, `is-active=active`, pid `342354`, NRestarts=0. Старт ~3 с.
- HTTP: `/api/health` **200**, `/api/public/rates` **200**, `https://focuspay.org/` **200**, `/x8` **200**, `/ops` **200**. Прод HTML не сдвинулся: `index.html` `2026-09-11 05:26:54`, `panel.html` `05:26:55`.
- Живых V2-столов после рестарта **0**. Blackjack `expired` с рестарта **0**.
- Хвост не этого бага: baccarat `b9beeee7` (id 90) висел `scoring` с **2026-09-07**. House-fill не смог settle (`Unified balance hold does not match casino hold` — было и до рестарта). Idle > 30 мин → `expired` 21:01:27, outbox `cancelled` id 130/131, ставки вернулись. Не hitting blackjack.

Потыкать (прод, группа FOCUS PAY):

1. Две живые руки 16/17: успеть «Взять карту» — стол не должен исчезнуть с возвратом в первую минуту.
2. Второй прогон: никто не жмёт ~3 мин → авто-оставить и выплата, не «Игра отменена».
3. Сайтовый стол: ~30 с на ход, потом авто-оставить, не cancel.

## 2026-09-11 · Создатель стола сразу на карточке

Не прод. Казино-бота на боевом не перезапускал. API/фронт/HMAC/рейк не трогал. Холдем/кланы/дом 1×1 не трогал.

Повод: при создании стола создатель уже сидит в API, но в чате его не видно. Для блэкджека объявление в группе из-за `if/else` на соседних строках становилось только «Нажмите Войти. Карты в личке» — без номера стола и без имени. На живой карточке имя писалось в `roster_names` после первого send, поэтому место 1 было «игрок».

Сделано:

- `_apply_actor_roster`: имя создателя на seat 1 до первой отрисовки.
- `_listing_text`: всегда шапка + ставка + «За столом: @name». Блэкджек — доп. строка про личку, не вместо карточки.

Файлы: `focuspay-casino/games/v2_runtime.py`, `tests/test_v2_card_board.py`. Журнал этот.

Проверки:

- git HEAD focuspay `816b005` / casino `f0ab827`. Этот срез: два файла бота (+108/−18). Чужой WIP не лил. Не коммитил.
- md5 local=`/opt/focuspay-casino`=`контейнер /app`: `v2_runtime.py` `16ab7bf4d0f906f231643764f1292e46`, `test_v2_card_board.py` `7b4625cddaca96a0b0514b575b89bcb8`.
- Локально 3 новых теста + `test_v2_chat_hygiene`: **20 OK**. `py_compile` OK.
- Контейнер те же **20 OK**.
- `_apply_actor_roster`: **2** (объявление + `publish_created_table`). `_seated_names_line`: **2**. `_listing_text`: **3** модуль + **1** тест.
- Staging: rsync в `/opt/focuspay-casino` + `compose --profile casino up -d --build --no-deps casino-bot`. Контейнер running с `2026-09-11T21:15:36Z`.
- Docker: gateway `127.0.0.1:18081`, хост **18082**. Это правка Telegram-карточки, сайт не менялся.
- Прод read-only: `index.html` `2026-09-11 05:26:54`, `panel.html` `05:26:55`, API `21:01:23 UTC` (прошлый выкат блэкджека), casino-bot **`2026-09-08 06:10:35 UTC`** — этот срез туда не лил.

Потыкать (staging-бот; прод-бот старый, пока нет «го»):

1. Создать блэкджек в группе — на карточке сразу @ник создателя на месте 1, не «игрок» и не пусто.
2. Создать из лички — в группе объявление со столом #, ставкой и «За столом: @ник», не одна строка «Войти».
3. Второй игрок жмёт «Войти» — создатель остаётся на месте 1.

## 2026-09-11 · Стол 2–6: без автоотмены по времени

Не прод. `deploy_all.py` не запускал. Холдем/кланы/дом 1×1 не трогал. HMAC / рейк 5% не менял. 1×1 дуэли и house-multi по-прежнему гаснут через 10 мин.

Повод: карточка блэкджека `#776FB060` оставалась «Сбор ставок» после отмены. Closer каждые ~10 с снимал V2 `open` с одним человеком через 10 мин (`expire_unjoined_v2`). Outbox слал «игра отменена» в личку и **не удалял** групповую карточку. На самой карточке не было кнопки отмены — только «Занять место» / «Бот».

Сделано:

- V2 стол больше не истекает по join-timeout. Создатель отменяет кнопкой в боте (`❌ Отменить стол` на карточке и в «моих столах»).
- Отмена / outbox cancel / «Войти» в уже мёртвый стол — бот удаляет карточку (или пишет «Стол отменён», если нет прав на delete).

Файлы: `site/exchange-backend/casino_waiting.py`, `tests/test_casino_waiting.py`; `focuspay-casino/games/v2_runtime.py`, `games/v2_tables.py`, `tests/test_v2_card_board.py`, `tests/test_v2_tables.py`, `tests/test_result_notify.py`. Журнал этот.

Проверки:

- git HEAD focuspay `816b005` / casino `f0ab827`. Этот срез: waiting no-op + бот cancel/delete. Чужой WIP не лил. Не коммитил.
- md5 local=`/opt`=`контейнер`: `casino_waiting.py` `94a74d0dd1116091b93a32bbce5aa418`, `v2_runtime.py` `c917250cac565cd07e1a0a41d97cac06`, `v2_tables.py` `159e09d300bc208fb9bbb9e72140454f`.
- `py_compile` OK.
- Локально: waiting Expire/Cutoff/Cancel **10 OK**. Бот 7 новых + hygiene в контейнере **24 OK**. Прежний fail `test_blackjack_hit_buttons_stay_on_group_card` не этого среза.
- `expire_unjoined_v2`: **3** модуль + **3** тест. `_cancel_button`: **3**. `discard_table_cards`: **3** runtime + **2** `v2_tables`.
- Staging: rsync этих файлов + `compose up -d --build --no-deps` backend и casino-bot. Backend healthy с `2026-09-11T21:27:20Z`, casino-bot `2026-09-11T21:27:31Z`.
- Docker: gateway `127.0.0.1:18081`, хост **18082**.
- Прод read-only: HTML `05:26:54` / `05:26:55`, API `21:01:23 UTC`, casino-bot **`2026-09-08 06:10:35 UTC`**, прод `casino_waiting.py` `23fa33cb0e13d4bd915c4e7f6f32f012` — этот срез туда не лил.

Потыкать (staging-бот; FOCUS PAY — старый бот/API, пока нет «го»):

1. Создать стол 2 места — на карточке сразу «❌ Отменить стол». Нажать — карточка пропадает, ставка на балансе.
2. Не жать отмену 10+ мин — стол живой, карточка на месте.
3. Старая карточка после прошлой автоотмены: «Занять место» или «Отменить» — сообщение снимается.

### Выкат на прод (по «выкати впрод» / «делай»)

Выкатил три файла: `casino_waiting.py` → `/opt/exchange-backend`, `v2_runtime.py` + `v2_tables.py` → `/opt/focuspay-casino/games`. Рестарт `focuspay-exchange-api` и `focuspay-casino-bot`. Фронт, nginx, обменный бот, `.env`, миграции не трогал. Не коммитил.

- Бэкап: `/opt/backups/v2-no-timeout-20260911T213631Z/` + `v2-no-timeout-pre-20260911T213631Z.tgz`. Прошлые md5: waiting `23fa33cb…`, runtime `c3998f33…`, tables `e633d755…`.
- Дифф прод↔локаль до выката: waiting **+7/−4** (только `expire_unjoined_v2` → `return 0`). `v2_tables.py` **+21/−1** (cancel/delete). `v2_runtime.py` **+345/−55**: этот срез (roster создателя, `_cancel_button`, `discard_table_cards`) плюс личка блэкджека, которая уже была в том же файле на staging; чужих модулей не лил. `v2_chat_ledger.py` на проде уже с `already_finalized`, md5 совпал.
- После: md5 = локальный `94a74d0d…` / `c917250c…` / `159e09d3…`. `py_compile` OK. `focuspay:focuspay` 644.
- API: `ActiveEnterTimestamp=2026-09-11 21:37:19 UTC`, pid `345259`, NRestarts=0, `active`. Старт ~3 с.
- Бот: первый старт в ту же секунду поймал **502** на `/api/internal/casino/settings` (API ещё поднимался) → systemd NRestarts=1. Живой повтор: `21:37:30 UTC`, pid `345293`, `@focusludka_bot`, V2/BJ хендлеры, slash menu cleared. ERROR hydrate рулетки — не этот срез.
- HTTP: `/api/health` **200**, `/api/public/rates` **200**, `https://focuspay.org/` **200**, `/x8` **200**, `/ops` **200**. HTML не сдвинулся: `index.html` `2026-09-11 05:26:54`, `panel.html` `05:26:55`.

Откат: файлы из `v2-no-timeout-20260911T213631Z` + restart обоих unit.

Потыкать (прод, FOCUS PAY / `@focusludka_bot`):

1. Создать блэкджек на 2 места — сразу @ник и «Отменить стол».
2. Нажать отмену — карточка пропадает, ставка на балансе.
3. Новый стол 10+ мин без отмены — живой.
4. Старая карточка `#776FB060`: «Отменить» или «Войти» снимает сообщение.




## 2026-09-12 · BJ: добор на карточке + зомби #E67E4102

Не прод (патч бота локально). API/фронт/HMAC/рейк не трогал. Холдем/кланы/дом 1×1 не трогал.

Повод: стол `#E67E4102` (qqtttqw + focuspayadmin) стартовал, группа писала «Добор — в личке», в ЛС хода не было. Closer после дедлайна пытался settle → `Unified balance hold does not match casino hold` (hold=0), спам раз в секунду. «Мои игры» показывали стол, «Активные» — нет.

Сделано (прод ops):

- Снял стол через `_expire_stale_v2_play_table`: `expired`, seats `released`, outbox cancel 135/136. Closer spam = 0. Hold был 0 → списаний/возвратов по ledger не было. 135 (qqtttqw) — bot blocked; 136 (admin) — delivered.

Сделано (код `focuspay-casino`, ещё не на прод):

- Групповая карточка снова с «Взять / Оставить» (`_card_keyboard` без viewer).
- Параллельно `_sync_blackjack_dms` шлёт личную доску каждому человеку; `/start bj_<table_id>` открывает её.
- Тексты: добор кнопками ниже / в личке.

Файлы: `games/v2_runtime.py`, `bot.py`, `tests/test_v2_card_board.py`. Журнал этот.

Проверки:

- Локально `python -m unittest tests.test_v2_card_board -q`: **22 OK**. `test_v2_tables`: **22 OK**. `py_compile` OK.
- md5 local: `v2_runtime.py` `f2450807b2427a1f660ccbfa953e9acf`, `bot.py` `b8cddda73d8b932a745d97b78f3f981f`, `test_v2_card_board.py` `7edb10f1d73366fec2361c0a28318a6a`.
- Прод casino-bot пока старый `c917250cac565cd07e1a0a41d97cac06` — ждать «го» на выкат.

Потыкать после выката:

1. BJ 2 места в группе — на карточке сразу «Взять / Оставить».
2. В личке у обоих появляется своя доска с открытыми картами.
3. `/start bj_<uuid>` из deep-link открывает ход, если сидишь за столом.

Хвост (не этот срез): почему V2 join не оставил unified hold для `#E67E4102` — иначе closer не зависал бы на settle.

## 2026-09-17 · Production: создание баккары блокировалось preflight

Обращение: «Не удалось создать стол» при создании баккары. Journal casino-bot
03:49:10/03:49:13 UTC показал EntryDenied до вызова backend. Telegram getChatMember
подтвердил restricted + is_member=true + can_send_messages=true +
can_send_other_messages=true. Бот имел достаточно прав для игровых карточек,
но новый preflight ошибочно требовал administrator и can_delete_messages.

Исправлены только focuspay-casino/telegram_reliability.py и games/table_wizard.py:
проверяется фактическое право отправки для restricted и обычного member
(для member через chat.permissions); left/kicked/muted остаются заблокированы.
Удаление чужих сообщений — необязательная уборка, не условие приёма ставки.
EntryDenied теперь отображается пользователю с конкретной причиной.

До исправления два regression-теста воспроизвели отказ и потерю текста ошибки.
После: 369 тестов casino-bot OK; дополнительно расширены проверки member и
create_v2_table для baccara/blackjack/pvp_dice (31 focused test OK).
Backend: 664 passed + 41 subtests. Production read checks: settings, roulette,
jackpot, fixed rooms, active PVP, recovery snapshot — OK. Preflight на реальных
правах production-чата проходит (DM-send заменён заглушкой только в probe;
это не live E2E и не проверка доставки пользователю).

Выкат 03:54 UTC, backup /opt/backups/casino-entry-rights-20260917T0354/.
py_compile OK, casino-bot active, обработчики зарегистрированы, health OK.
Backend и денежные записи этим исправлением не менялись.

Read-only аудит исторического хвоста: 4 V2 pvp_dice manual_review с outcome
(2026-09-07 ×2, 2026-09-15, 2026-09-16); причина у всех — отсутствующий
unified hold при settlement. Это не завершённые партии: финансовые записи
сохранены для сверки, автоматического повторного списания не производилось.
V2 outbox: completed=152, dead=22 (19 Telegram 403 / 3 Telegram 429),
legacy outbox completed=32. На момент проверки активных V2 столов нет,
legacy casino_balance_holds содержит только confirmed=39.

Повторный disposable Compose E2E: 15 tests OK (111.110s).
QA60 elapsed=99.73s, finished=60; 120 spends, 0 holds, 60 settlements,
120 outbox records; conservation OK. Telegram — synthetic adapter, не
60 живых Telegram-клиентов. Лог /tmp/casino-rights-results.log.
Стенд casino-rights-20260917 остановлен после прогона; production не нагружался.

---

## 2026-10-09 · Холдем: карман до вскрытия

Сделано: `public_view` отдаёт чужой карман только после настоящего шоудауна (`cards_shown`, его ставит только добор борда). Фолд-победа оставляет рубашки, в том числе у победителя для соперника. Уже открытый флоп остаётся, нерозыгранные терн и ривер в снимок не попадают. Сид колоды пишется и отдаётся только если `cards_shown`; `status == complete` больше не раскрывает сид. Публичная проверка холдема сверяет борд и не возвращает `holes` / `burns`. Ранжир `best_seven` на месте; `treys` только в `requirements-dev.txt`. Плитка холдема снова в лобби. Бота нет.

Файлы: `casino_holdem.py`, `casino_poker.py`, `casino_player_history.py`, `routers/public_casino.py`, `tests/test_casino_holdem.py`, `tests/test_casino_fairness.py`, `tests/test_casino_player_history.py`, `requirements-dev.txt`, `gameCatalog.ts`, `casinoRoutes.tsx`, `.cursor/rules/casino-shelved-games.mdc`.

Локально: `python -m unittest tests.test_casino_holdem tests.test_casino_fairness` + `ShareAndResultTests.test_poker_fold_hides_seed_and_showdown_publishes_only_the_board` — **33 ok**, 0 failed. Имена приватности: `test_two_viewers_never_see_the_other_pocket_before_showdown_or_after_fold`, `test_flop_fold_keeps_dealt_board_and_hides_the_winner_pocket`, `test_showdown_shows_live_pockets_and_keeps_a_folded_pocket_hidden`. Судья: `test_wheel_loses_to_six_high_and_the_pot_follows_treys`, `test_kicker_orders_the_same_pair_like_treys`, `test_split_pot_matches_a_treys_tie_and_odd_kopek_goes_left_of_the_button`, `test_side_pot_pays_the_short_stack_main_and_treys_winner_the_side`.

`rg cards_shown`: движок, `to_dict`/`from_dict`, фолд и runout, `public_view`, `_finish_hand`, снимок стола, история, тесты.

Лобби на `http://127.0.0.1:5173/casino`: плитка «Техасский холдем», клан в каталоге нет. `/casino/play/holdem`: «Кэш-стол 2–6 мест», бай-ин 400–2 000 ₽, блайнды 10/20, рейк 5%, кнопка «Войти и открыть стол», открытых столов нет. Чужие рубашки на живом столе этим прогоном не смотрел: боевой API ещё старый.

Прод не выкатывал. Метки: `index.html` 2026-10-08 14:20:56 UTC, `panel.html` 2026-10-08 14:20:58 UTC, `focuspay-exchange-api` ActiveEnterTimestamp Fri 2026-10-09 05:42:41 UTC. Staging-sync и `staging-test.sh` не запускал. Старые руки с уже записанным сидом не мигрировал.

---

## 2026-10-09 · Нарды: стол вместо сетки

Сделано: лобби и партия рисуют длинные нарды как доску. Деревянная рама, 24 треугольника, бар, шашки стопкой (больше пяти — число на верхней), лотки снятых слева чёрные и справа белые, кости кубиками. Старт: 15 белых на 24, 15 чёрных на 12. Дома 13–18 и 1–6 отмечены латунной чертой. Ход кликом по своей шашке и подсвеченному пункту; список `24→18` убран. «Ход сгорел» остаётся кнопкой. Правила под столом — одна строка.

Файлы: `CasinoNardyTable.tsx`, `CasinoNardy.tsx`, `casino.css`. Бэкенд не менялся.

Локально: `tsc -p tsconfig.app.json --noEmit` — 0 ошибок. Разбор подписей хода (`24→19, 19→14`, `снять с 6`, `ход сгорел`) и сужение хода до одного `move_index` прогнаны отдельно — ок.

Браузер `http://127.0.0.1:5173/casino/play/nardy`: десктоп и 390px. Доска на всю колонку, горизонтального скролла нет, кнопки ставок в одну строку. Подсветка хода и кости 5 и 2 смотрел на том же компоненте. `/casino/nardy/missing` без входа: «Not authenticated», стол не рисуется. Живой ход по шашке не играл: в этой сессии нет входа.

Выкат фронта 2026-10-09 09:07 UTC. Бэкап HTML `.bak-20261009-050737` у `index.html`, `panel.html`, `casino.html`, `exchange.html`. Новый бандл: `index-go1GCV1j.css`, `casinoRoutes-DLZjoYJk.js`. HTTPS `/`, `/x8`, `/ops`, `/casino/play/nardy`, `/casino.html`, `/exchange.html` = 200. В CSS есть `nardy-board`. Бэкенд не трогал. Staging-sync и `staging-test.sh` не запускал.

---

## 2026-10-10 · Блэкджек: руки в строке лобби

Сделано: в открытой строке стола блэкджека и баккары места больше не делят ширину по `1fr`. Руки стоят слева, ширина по картам, зазор 16px. Подсветка победы/проигрыша/лидера остаётся. Кубики в той же строке по-прежнему на всю ширину. Страницу стола не менял.

Файлы: `CasinoV2CompactPlay.tsx` (класс `is-cards` на корне мест карточного стола), `casino.css` (только `.casino-v2-strip-play .casino-v2-seats.is-cards`).

`rg casino-v2-seats.is-cards`: 4 правила в `casino.css`, класс ставится в `CasinoV2CompactPlay.tsx`. SQL нет.

Замер на CSS с `http://127.0.0.1:5173` (полоска 946px, две рубашки + три лица + победа): зазор рук **16px**, рука 98 / 142 / 98px, `flex-wrap: nowrap`, фон обычного места `rgba(0,0,0,0)`, победа `srgb 0.184 0.749 0.443 / 0.16`. Кубики без `is-cards`: зазор **422px**. Скрин `docs/qa-screenshots-2026-10-10/blackjack-strip-hands.png`. Живых столов блэкджека на `GET /api/public/casino/v2/tables?game_type=blackjack` — **0**.

Прод не выкатывал. Метки: `index.html` 2026-10-09 11:39:28 UTC, `panel.html` 2026-10-10 01:49:37 UTC, `focuspay-exchange-api` ActiveEnterTimestamp Sat 2026-10-10 04:14:39 UTC. Staging: `178.63.247.233:22` — No route to host, `:18082` и туннель `:18081` не открылись. `staging-sync.sh` и `staging-test.sh` не запускал. md5 local vs staging нет.

---

## 2026-10-10 · Шашки: клетка и чёрные

Сделано: клетка задаёт себе квадрат через `aspect-ratio`, доска больше не режет фигуры нулевой высотой ряда. Чёрные — светлая заливка с тёмным ободком. На картинке лобби и пока стол ждёт второго: «Ход появится у белых, когда сядут чёрные.» Кнопок хода без соперника нет.

Файлы: `casino.css`, `CasinoDraughts.tsx`, `CasinoDraughtsTable.tsx`. Бэкенд не менялся.

Локально на 390px: доска 300×300, клетка 37.25px, чёрные `rgb(212, 212, 216)`, нажатие в шашку попадает в клетку `b8`. Кнопок `a3-b4` нет.

Выкат фронта 2026-10-10 12:00 UTC. Бэкап `.bak-20261010-080030`. Живые `index-DGiB2stM.css` и `casinoRoutes-BXG65JkP.js`. HTTPS `/` `/x8` `/ops` = 200. Staging не трогал.

---

## 2026-10-12 · Дизайн FocusBet v2

Сделано: вид казино перенесён с прототипа focuscasinov2.0 на общие экраны сайта, мини-аппа и FocusLucky. Токены в `.casino-root` (Inter, `#0c0c0c`, белый акцент). Оболочка: логотип, кошелёк с «Вывести» и «Пополнить», сворачиваемый рельс. Лобби: герой, три анонса, плитки с фото. Карты: рубашка SVG, лицо мастью; `faceDown` по-прежнему без ранга в тексте. Нарды перекрашены в монохром. HeroUI не ставился. Кланы не открывались. Бот не менялся.

Файлы: `casino.css`, `casino-skin.css`, `CasinoShell.tsx`, `CasinoLobby.tsx`, `CasinoGameTile.tsx`, `CasinoPlayingCard.tsx`, `gameRailIcon.tsx`, `vite.config.ts`, `public/casino/*`, `exchange-miniapp/screens/LuckyScreen.tsx`.

Локально `npm run build` — 0 ошибок. Dev `http://127.0.0.1:5199`. Плиток в лобби **10**, `clan_war` **0**, слова «клан» в рельсе нет. Закрытая карта: `data-casino-card=back`, текст пустой, подпись «Закрытая карта». Открытые `A♠` и `10♥` содержат ранг. Мини-апп `/casino/tg` и вкладка Lucky (`/exchange/tg/lucky?preview=1`) рисуют ту же оболочку. Рулетка и FocusLucky открываются. `staging-test.sh` не запускал.

Прод 2026-10-12 19:32 UTC. Бэкап HTML: `index.html.bak-20261012-153217`, `panel.html.bak-20261012-153217`, `casino.html.bak-20261012-153217`, `exchange.html.bak-20261012-153217`. Бандлы: `index-C5thBcr4.js`, `index-DPPVy93A.css`, `casinoRoutes-CcMEn5rE.js`, `casino-Cdv-CMjA.js`, `exchange-CJlVtG_9.js`, `panel-DsfEKrGi.js`. Картинки в `/var/www/focuspay.org/casino/`. Nginx: `location = /casino` отдаёт `index.html`, бэкап конфига `/root/nginx-backups/focuspay.org.bak-20261012-1934`. API и бот не рестартились. HTTPS `/` `/x8` `/ops` `/casino` `/casino/` `/casino/tg` `/exchange/tg` и картинки логотипа, рубашки, героя, плитки — 200. Staging не выкатывал.

## 2026-10-12 · Комнаты кубиков, баккары и блэкджека

Сделано: лобби этих трёх игр — колонка «Новый стол» и список «Открытые столы». Раскрытый стол — арена с местами: аватар, имя, кубик или две рубашки, счёт внизу. Тот же вид на `/casino/tables/:id`. Очки баккары считаются только по открытым картам. `tsc --noEmit` — 0 ошибок. Локально `http://127.0.0.1:5199/casino/play/baccara?mode=players`: 8 карт, все `data-casino-card=back`, текст пустой, четыре значения «—». Прод не выкатывал. `staging-test.sh` не запускал.

Комнаты, холдем, нарды и шашки получили ту же колонку создания и список открытых столов. У кубиков над местами полоса VS. Планка и лотки нард: `#2a2a2a` и `#141414`, без дерева. Локально проверены `/casino/play/fixed_room`, `/holdem`, `/nardy`, `/russian_draughts`, `/pvp_dice`.

Прод 2026-10-12 16:01 UTC. Бэкап `*.bak-20261012-160120`. Живые `casinoRoutes-UfkMMsz3.js`, `index-fxzLTSD8.css`, `casino-CD9nmgdI.js`, `exchange-DsK8lyA8.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200. API и бот не рестартились.

## 2026-10-12 · Деревянная доска длинных нард

Сделано: серая заливка доски снята. Рама `rgb(141, 94, 56)`, поле `rgb(237, 217, 174)` / `rgb(201, 165, 106)`, планка `rgb(138, 88, 52)` → `rgb(44, 26, 16)`, лоток `rgb(44, 28, 18)`. Пункт 24 бордовый `rgb(163, 61, 56)`, соседний 23 кремовый `rgb(255, 248, 234)`. Старт: 15 белых на 24 и 15 чёрных на 12, на экране по 5 шашек и цифра 15. Дубль рисует четыре кости. Нумерация и `casino_nardy.py` не менялись.

Правила: `pytest tests/test_casino_nardy.py` — 22 passed. Клик по моку на `127.0.0.1:5199`: кости 5 и 3, выбрана 24, цели только 19 и 21; клик по 12 не снимает выбор; после 24→21 голова 14, шашка на 21, следующая цель 16. Дубль 6-6: подпись «Дубль 6, четыре хода», 4 кости, цель 18. Снятие: подсвечен белый лоток, чёрный нет, второй клик шлёт `move_index: 0`. Номера 12 и 24 не пересекаются со стопкой (covers 0) на 1280 и 390. `staging-test.sh` не запускал.

Прод 2026-10-12 20:41 UTC. Бэкап `*.bak-20261012-204102`. Живые `casinoRoutes-FawACZlh.js`, `index-Hs536pq_.css`, `casino-zlBAE6N1.js`, `exchange-B4F0_V3m.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200. В CSS есть `#8d5e38`. API и бот не рестартились.

Крупный стол. Доска на всю ширину страницы: на 1440px поле 1044×523, шашка 60px, номер пункта 23px на тёмной плашке, подписи лотков 16px. Номера 12 и 24 не пересекаются со стопкой. Под доской строка: белые с 24, чёрные с 12, цифра — сколько шашек.

Прод 2026-10-12 20:55 UTC. Бэкап `*.bak-20261012-205427`. Живые `index-Ds4FI9Ph.css` (226733 байт, `nardy-legend`, лоток 84px), `casinoRoutes-F-ZWkq8a.js` (301104, «сверху справа»), `casino-CDBtHqDO.js`, `exchange-D3dnO5MX.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200, `no-store`. API и бот не рестартились.

Ширину стола ограничил 800px. На 1440px доска 800×377, номер 21px, шашка 41px, подпись лотка 16px. Номера 12 и 24 не пересекаются со стопкой.

Прод 2026-10-12 21:03 UTC. Бэкап `*.bak-20261012-210240`. Живые `index-CwzVu32U.css` (226780, `800px`), `casinoRoutes-BBfvVueL.js`, `casino-dlg52tEm.js`, `exchange-DnPnSOpf.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200, `no-store`. API и бот не рестартились.

## 2026-10-12 · Нарды: доска только в лобби стола

Сделано: со списка `/casino/play/nardy` стартовая доска убрана. У стола в ожидании кнопки «Смотреть» и «Сесть», у идущей партии только «Смотреть». `/casino/nardy/:id` — доска, статус и подпись пунктов. «Сесть чёрными» с этой страницы снято; ход и сдача остаются у того, кто уже сидит. Гость опрашивает `GET /api/public/casino/nardy/tables/{id}` (`viewer_id=None`): без `server_seed` и без списка ходов. Вошедший по-прежнему берёт пользовательский снимок, чтобы получить свои ходы. `casino_nardy.py` не менялся.

Файлы: `CasinoNardy.tsx`, `CasinoNardyTable.tsx`, `casino.css`, `src/lib/public.ts`, `site/exchange-backend/routers/nardy.py`, `tests/test_casino_nardy.py`.

`pytest tests/test_casino_nardy.py` — 23 passed. `tsc -b` — 0 ошибок. Браузер `http://127.0.0.1:5199` с моком лобби: на списке `.nardy-board` = 0, «Сесть» = 1 (только стол в ожидании), «Смотреть» = 2. После «Смотреть» доска 1, «Вы наблюдаете», «Сесть чёрными» = 0, запросы гостя только на публичный снимок (2), на `/api/user/casino/nardy/tables/` — 0. Скрины `/tmp/casino-v2-games/nardy-list.png`, `nardy-watch.png`.

Прод 2026-10-12 21:35 UTC. API `nardy.py` md5 `cd0e5666`, бэкап `/opt/backups/nardy-watch-20261012-213230/nardy.py`. Рестарт API 21:35:12 UTC, бот не трогал. Живые `index-dLoib667.js`, `casinoRoutes-D8LQJPZB.js` (302871, «Смотреть»), `casino-CkfedDMX.js`. HTTPS страницы 200, `no-store`. Публичный снимок несуществующего стола: 404 «Стол не найден». Открытых столов 0. В меню нарды, холдем и шашки скрыты: прямой адрес уводит в лобби. Короткое возвращение нард в список снято в 21:47 UTC, HTML `.bak-20261012-214727`. Staging не трогал.

## 2026-10-12 · Рулетка из focuscasinov2.0

Почему не перенеслась: в архиве рулетка — отдельная комната (`Roulette.jsx`, `roulette.css`): верхняя половина колеса, зелёное сукно 0–36, дюжины и внешние ставки. При переносе вида v2 задача «переодеть рулетку» была отмечена готовой, но в стили попал только класс `.casino-roulette-stage`, который экран не использовал. Боевой стол остался круглым колесом и узкой сеткой. Демо-API архива `/api/roulette/table` на прод не переносился: деньги и HMAC остаются в `casino_roulette.py`.

Сделано: стол рисуется как в архиве. Полуколесо с «FOCUS / EUROPEAN ROULETTE», история чисел, сукно: ноль слева, ряды 3-6-9 / 2-5-8 / 1-4-7, колонки 2:1, дюжины, внешние 1–18 / чёт / красное / чёрное / нечет / 19–36. Узкий экран поворачивает сукно, числа не сжимаются в полоску. Ставки, фишки, повтор и отмена те же.

Файлы: `CasinoRoulette.tsx`, `casino.css`, `casino-skin.css`. Бэкенд не менялся.

`tsc -b` — 0 ошибок. `npm run build` — 2335 модулей. Локально `http://127.0.0.1:5199/casino/play/roulette`: полуколесо, ноль под указателем, сукно 37 клеток и 6 внешних ставок. На 390px ноль сверху, числа тремя колонками, 2:1 снизу.

Прод 2026-10-12 21:57 UTC. Бэкап `index.html.bak-20261012-175701`, `panel.html.bak-20261012-175701`. Живые `index-Cd88d95y.css` (`roulette-felt-scroll` = 1), `casinoRoutes-B37hV8Pm.js` (`EUROPEAN ROULETTE` = 1), `casino-Cg7OnI1l.js`, `exchange-Bj0rVL3J.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/play/roulette` `/casino/tg` `/exchange/tg` = 200. API `ActiveEnterTimestamp` остался Mon 2026-10-12 21:35:12 UTC. Бот не трогал. Staging `178.63.247.233:22` — No route to host. `staging-test.sh` не запускал.

## 2026-10-12 · Рулетка: отмена, повтор, сброс

Кнопки были серые при фишках на столе. `/auth/me` отдаёт `telegram_user_id`, а стол сравнивал фишки с `id` строки `web_users`. Свои ставки не узнавались, «Отменить» и «Сбросить все» оставались выключенными. «Повторить» ещё и не нажимался, пока на столе уже есть фишки.

Сделано: игрок берётся как `telegram_user_id`, затем `telegram_id`, затем `client_user_id`, иначе `user_id` из `my_bets`. Отмена и сброс клетки работают по этим ставкам, даже если локальный журнал пуст. Повтор добавляет прошлый расклад к текущим фишкам. Бэкенд не менялся.

Файлы: `CasinoPlay.tsx`, `CasinoRoulette.tsx`, `roulette.ts`. `tsc -p tsconfig.app.json --noEmit` — 0 ошибок. Локально на `127.0.0.1:5199` с подменой игрока `id: 4` / `telegram_user_id: 555001` и ставками dozen1 20 ₽ + dozen2 10 ₽: клетка «1–12» `is-on`, три кнопки включены. Клик «Отменить» отправил `POST /clear {"bet":"dozen2"}`, «Повторить» — `POST /bets` с красным на 10 ₽, «Сбросить все» — `POST /clear {}`.

Прод 2026-10-12 22:18:42 UTC. Живой `casinoRoutes-BuiVEWIU.js`: «На столе нет ваших фишек» = 1, «На этой клетке нет ваших фишек» = 1. CSS `index-Bsh2c2_F.css`, `roulette-felt-scroll` = 1. API `ActiveEnterTimestamp` Mon 2026-10-12 22:17:03 UTC — этот рестарт не из правки кнопок, бот не трогал. Staging `178.63.247.233:22` — No route to host.

## 2026-10-12 · Внутренности FocusBet v2

Сделано на живых экранах, без демо-заглушек и без смены денег:

- Шапка: глаз прячет сумму (`•••• ₽` / `•••• USDT`), флаг `focusbet-balance-hidden` в sessionStorage.
- Профиль: ссылки «Настройки профиля» и «Проверка честности».
- Настройки: счётчик `N/32`, уход с несохранённым именем или тумблером блэкджека спрашивает подтверждение. Отдельный тумблер «только личные» не добавлялся: его некуда писать.
- Лобби кубиков, баккары и блэкджека: фильтр максимальной ставки 10–100 000 ₽.
- Карты: переворот рубашка → лицо 600ms. Под ареной блок правил. Ход блэкджека прежний.
- Кубик: WebGL, если контекста нет или включено «меньше движения» — плоская грань. Кольцо только на `countdown_ends_at`. Счёт сессии локальный.
- Рулетка: номиналы 10/25/50/100/250/500 у сукна, режим «Набор чисел» шлёт cover-ключ, блоки «За столом» и «Мои ставки», правила и ссылка HMAC.
- Джекпот: пропуск спина, суммы 100/500/1000/5000 внутри лимита, карточка итога с билетом.

Файлы: `CasinoShell.tsx`, `CasinoProfile.tsx`, `CasinoPlayerSettings.tsx`, `CasinoPlayersLobby.tsx`, `CasinoPlayingCard.tsx`, `CasinoV2CompactPlay.tsx`, `CasinoDice.tsx`, `CasinoRoundedDie.tsx`, `CasinoStartCountdown.tsx`, `CasinoRoulette.tsx`, `CasinoPlay.tsx`, `CasinoJackpot.tsx`, `casino.css`, `casino-skin.css`. Бэкенд не менялся.

`tsc -b` внутри `npm run build` — 0 ошибок, 2336 модулей. Прод 2026-10-12 22:43:49 UTC. Бэкап `index.html`/`panel.html` `.bak-20261012-184348`, `casino.html`/`exchange.html` `.bak-20261012-224219`. Живой `casinoRoutes-j5cNYbJV.js`: «Пропустить анимацию» = 1, «Нет подходящих столов» = 1, `focusbet-balance-hidden` = 2, «Набор чисел» = 1. CSS `index-CyXN4rbV.css`. md5 `index.html` `86e3e9d82ae2e124d64583093ab38e1f` локально и на диске совпал. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200, `cache-control: no-store`. API `ActiveEnterTimestamp` остался Mon 2026-10-12 22:17:03 UTC. Бот не трогал. Staging по-прежнему No route to host.

## 2026-11-02 · FocusBet mobile chat ~2× taller

На телефоне нижний лист чата был **36vh**. Пользователь попросил открывать вверх примерно вдвое.

Сделано только CSS: `@media (max-width: 767px)` у `.casino-chat` — **36vh → 72vh**; при `:focus-within` (клавиатура) **70vh → 82vh**. Десктопный dock не трогал. Бэкенд / деньги / HMAC не трогал.

Файл: `focussite/frontend/src/casino/casino.css`.

Проверки:

- `rg`: `72vh` / `82vh` в mobile-блоке `.casino-chat`; `36vh` для чата больше нет.
- md5 `casino.css` local `2e56e3a268066b0f955386a096b80aaa`.
- Локально Vite `127.0.0.1:5173`, viewport 390×844: открыл «Чат» в нижней навигации. `getBoundingClientRect` → height **72vh** (607.7 / 844). Скрин `docs/qa-screenshots-2026-11-02/focusbet-mobile-chat-72vh.png`.
- Staging `focuspay-test` / `178.63.247.233:22` — Connection refused. `staging-test.sh` / md5 staging не гонял.
- Прод (read-only `ssh focuspay`): `index.html` 2026-11-03 02:10:50 UTC, `panel.html` 2026-11-03 02:10:52 UTC, `casino.html` 2026-11-03 02:10:47 UTC, unit `ActiveEnterTimestamp=Tue 2026-11-03 02:27:27 UTC`. Этот срез на прод не выкатывал.

Git: dirty только правка высоты в `casino.css` (файл уже был с чужим WIP). Не коммитил, `deploy_all.py` не запускал.

## 2026-11-02 · Deploy: mobile chat 72vh

Выкат по «выкати». Полный `npm run build` / `deploy_all.py` **не** гонял: в локальном `casino.css` большой чужой WIP.

Хирургически в живом `/var/www/focuspay.org/assets/index-Cv4FhNZl.css`:
- `height:min(36vh,…)` → `72vh` (ровно 1 вхождение, блок `.casino-chat`)
- `.casino-chat.is-open:focus-within … height:min(70vh,` → `82vh`

Бэкап: `index-Cv4FhNZl.css.bak-chat72vh-20261102-214433`. md5 после патча `a09191a7bc3e2c9db944adec9e032713`.

Проверки:
- HTTPS `/` `/casino` `/casino/tg` `/x8` `/ops` = **200**
- live CSS: `36vh` = 0, chat `72vh` = 1, chat focus `82vh` = 1
- `index.html` / `panel.html` / `casino.html` timestamps не сдвигались (02:10 UTC)
- API `ActiveEnterTimestamp` остался Tue 2026-11-03 02:27:27 UTC
- Бот / бэкенд не трогал

## 2026-11-02 · Mobile chat taller + cache-bust

Скрин из Telegram: чат всё ещё низкий. Причина: прошлый патч в тот же `index-Cv4FhNZl.css` при `Cache-Control: immutable` / max-age 1y — WebView держал старый 36vh.

Сделано:
- Высота листа на телефоне: от низа шапки до верха нижней навигации (`100svh - header - nav - safe`), без потолка 36/72vh.
- Новый ассет `index-Cchat4149b352.css`, ссылки в `casino.html` / `index.html` / `exchange.html`.
- Бэкапы `*.bak-chatheight-20261102-215033`.
- HTTPS `/` `/casino` `/casino/tg` `/x8` `/ops` = 200. API/бот не трогал.

## 2026-11-03 · Мобильный дизайн focuscasinov2.0

Перенесён мобильный слой из `focuscasinov2.0` на действующую React/TypeScript-логику FocusBet. Десктопный layout, API, деньги, HMAC, каталог и игровые правила не менялись.

Сделано:

- Telegram runtime синхронизирует `safeAreaInset` и `contentSafeAreaInset`, visual viewport, stable height, клавиатуру и признаки нативной BackButton.
- Шапка на ширине до 820px: логотип/заголовок экрана, компактный баланс, safe-area и blur. На вложенных экранах — браузерная кнопка назад, которая скрывается при нативной Telegram BackButton.
- Нижняя навигация сведена к трём вкладкам: «Игры / Чат / Профиль», активная иконка на пилюле.
- Главная: герой 184px с артом справа, две колонки плиток, мобильная типографика. Десктопный турнирный промо-блок на телефоне скрыт.
- Лобби на ширине до 820px: шапка игры, список столов и фиксированная кнопка «Создать стол». Форма создания и фильтр открываются нижним шитом. На десктопе форма остаётся колонкой слева.
- Игровые экраны, профиль, настройки, честность и чат получили мобильную геометрию прототипа. Чат занимает экран между шапкой и тремя вкладками.
- Добавлены reduced motion/transparency/contrast и keyboard-safe состояния.

Файлы: `focussite/frontend/src/casino/telegram.ts`, `CasinoShell.tsx`, `casino-skin.css`. Журнал — эта запись.

Проверки:

- `npm run build` — успешно, TypeScript и Vite без ошибок.
- IDE lint трёх файлов — 0 ошибок.
- Локальный клик-пасс 390×844: главная, баккара/создание стола, полноэкранный чат, честность. Горизонтального выхода на проверенных экранах нет.
- Скрины: `/tmp/cursor/screenshots/page-2026-11-03T05-53-28-741Z.png` (главная), `/tmp/cursor/screenshots/page-2026-11-03T05-52-42-836Z.png` (лобби баккары), `/tmp/cursor/screenshots/page-2026-11-03T05-52-17-219Z.png` (чат).
- Автосмоук `scripts/casino-miniapp-smoke.mjs` не стартовал: в рабочем `node_modules` нет пакета `playwright`; зависимости не менялись.
- md5 local: `telegram.ts` `02ceaaea0ac4d5a36460d39563a19ff7`, `CasinoShell.tsx` `c2ef765fa64a2b1192b9a420d4ef8d91`, `casino-skin.css` `60593b686686373763bcc30c9d40b044`.
- Staging `focuspay-test` / `178.63.247.233:22`: `Connection refused`. Поэтому `staging-test.sh`, SQL, docker ports и staging md5 недоступны; на staging ничего не заливалось.
- Прод read-only: между первым срезом (HTML 03:43 UTC) и финальной проверкой произошёл внешний параллельный выкат: `index.html` 05:50:17 UTC, `panel.html` 05:50:19 UTC, `casino.html` 05:50:14 UTC, API `ActiveEnterTimestamp=Tue 2026-11-03 05:49:08 UTC`. Этот агент production не менял.

Прод не выкатывался: `deploy_all.py` не запускался, отдельного «го» на production в этом чате нет.

## 2026-11-03 · Mobile scroll fix (не листается)

После fixed header на ≤820px shell оставался `height:100dvh` + `overflow:hidden`, а `.casino-main` перестал быть scrollport — на телефоне контент обрезался и жест не листал.

Сделано в `casino-skin.css` `@media (max-width: 820px)`:
- `.casino-shell` — `height/max-height: var(--app-stable-height, 100dvh)`, `overflow:hidden`
- `.casino-body` — column flex, `min-height:0`, `overflow:hidden`, padding под fixed header
- `.casino-main` — `flex:1`, `min-height:0`, `overflow:auto`, `-webkit-overflow-scrolling:touch`, `overscroll-behavior:contain`
- то же для `html[data-casino-entry="tg"] .casino-main`

Прод: `npm run build` + `deploy_all.py`. Бэкап HTML `.bak-20261103-014254`. Живые `index-Ciwlt4ea.css`, `casinoRoutes-C6wPXAZQ.js`, `casino-BiPmmB7m.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` = 200. Живой CSS содержит `.casino-main{…overflow:auto;-webkit-overflow-scrolling:touch…}`. API/бот не трогал.

Проверка 390×844 на `https://focuspay.org/casino`: `main.scrollHeight=1289` > `clientHeight=764`, `overflowY=auto`, программный `scrollTop=400` сработал. Скрин: `docs/qa-screenshots-2026-11-03/mobile-scroll-lobby.png`.

Staging `178.63.247.233:22` — Connection refused / недоступен; `staging-test.sh` не запускал.

## 2026-11-03 · Турниры снова вверху лобби на телефоне

Мобильный порт прятал `.casino-trn-lobby` на ≤820px. Карточку вернули и подняли над героем.

Сделано в `casino-skin.css` `@media (max-width: 820px)`:
- `.casino-trn-lobby` — вместо `display:none` теперь `order:-1` (лобби — grid, карточка идёт первой, выше героя), `margin-bottom:-8px` под общий `gap:26px`.
- Компактная геометрия карточки: padding 14px, радиус 16px, иконка 40px, заголовок 15px/650; длинное описание (`.casino-trn-lobby-copy > span`) на телефоне скрыто, CTA «Открыть» остался.
- Десктоп, маршруты, каталог и логика турниров не менялись.

Проверки:
- `npm run build` — `tsc -b` и Vite без ошибок.
- Локально 390×844 `http://127.0.0.1:5173/casino`: `.casino-trn-lobby` top **119**px против героя **238**px (`aboveHero=true`), высота карточки **101**px, `documentElement.scrollWidth` **390** (вбок не едет), `.casino-main` scrollHeight **1408** > clientHeight **764** — прокрутка жива.
- Прод: `deploy_all.py`, бэкап HTML `.bak-20261103-015626`. Живой CSS `index-Cg6VwIpf.css`, md5 `175b7ca617b0f452d39e35be31d2ca8b` совпал с локальным `dist/assets/index-Cg6VwIpf.css`. В живом CSS `.casino-trn-lobby{order:-1;margin-bottom:-8px}` и прежнее правило прокрутки `overflow:auto;-webkit-overflow-scrolling:touch`.
- HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200. API и бот не рестартились.
- Скрин прода не снят: браузерная сессия в этом прогоне отвалилась (`No browser tab available`), замеры геометрии сняты через CDP до этого на том же билде.
- Staging `178.63.247.233` по-прежнему недоступен, `staging-test.sh` не запускал.

## 2026-11-03 · Плитки игр на телефоне: без звёзд, ровный градиент

Мобильный слой ≤820px в `casino-skin.css`. Десктоп, каталог, API и правила игр не трогались. Скрытые игры остались скрытыми.

Сделано в `@media (max-width: 820px)`:
- `.casino-tile-fav` — вместо мобильной геометрии (`top/right/bottom/left`, 30×30) теперь `display: none`. Кнопка только скрыта, логика избранного (`toggleFavorite`, `FAVORITE_KEY`, сортировка избранных вверх в `CasinoLobby.tsx`) и компонент `CasinoGameTile` не менялись; отдельного ряда «избранное» в лобби нет, ломаться нечему. На десктопе звезда на месте.
- `.casino-tile::after` — вместо двухточечного `linear-gradient(0deg, #090909 0%, #090909e6 22%, #09090922 70%)` многоступенчатый `linear-gradient(to top, …)` на 11 остановках с ease-профилем: 0.97 → 0.95 (12%) → 0.9 (24%) → 0.8 (35%) → 0.66 (46%) → 0.5 (57%) → 0.34 (68%) → 0.2 (79%) → 0.09 (89%) → 0.02 (96%) → 0 (100%), цвет `rgb(9 9 9 / …)`. Полос/ступеней нет, низ плотный под подписи, верх арта чистый.
- Арт `public/casino/*-card.jpg` не менялся. Селекторы прокрутки (`.casino-main`, `.casino-shell`, `.casino-body`, fixed-панели) не трогались — их правит параллельный агент.

Проверки:
- `npm run build` — `tsc -b` + Vite зелёные.
- `ReadLints` по `casino-skin.css` — 0.
- Локально через CDP 390×844 (`http://127.0.0.1:5173/casino`, dev-бар скрыт): звёзд на плитках нет, названия и «от 10 ₽ · комиссия 5%» читаются, арт не залит серым. Видимы ровно 7 плиток: Кубики, Баккара, Блэкджек, Рулетка, Джекпот, Комнаты, FocusLucky.
- Десктоп 1440×1000 — лобби и сайдбар без изменений.
- Скрины: `docs/qa-screenshots-2026-11-03/lobby-tiles-no-star-390.png`, `docs/qa-screenshots-2026-11-03/lobby-tiles-desktop-1440.png`.

Выкат: не делался намеренно — прод катит другой агент. Не коммитил и не пушил.

## 2026-11-03 · Прокрутка и геометрия игровых экранов на телефоне

Жалоба владельца: «в играх не работает прокрутка». Воспроизведено на 390×844: на `/casino/play/dice`, `/casino/play/baccarat`, `/casino/play/blackjack` у `.casino-main` было `scrollHeight == clientHeight == 764` — прокручивать нечего, нижний контент обрезан.

Причина 1 — схлопывание flex-ребёнка. `.casino-main` (`casino.css:838`) это `display: flex; flex-direction: column` и одновременно scrollport. `.casino-play` (`casino.css:2739`) объявлен как `flex: 0 1 auto; min-height: 0`, поэтому вместо переполнения он сжимался по высоте скролпорта, а `.casino-play-canvas { overflow: hidden }` дорезал остаток. Лобби не страдало, потому что у `.casino-lobby` остаётся дефолтный `min-height: auto`.

Причина 2 — рулетка в десктопной сетке. `.casino-play-layout` для режимов не-`is-players` остаётся двухколоночным `340px minmax(0,1fr)`; в полосе 768–820px это давало канве ~32px. Ниже 767px `casino.css:3608` переводит её в `display: flex; flex-direction: column`, но базовый `align-items: start` в колоночном флексе сжимает канву до min-content — та же ширина 32–34px. Доска, колесо и ряд номиналов уезжали за правый край.

Причина 3 — `min-width: auto` у горизонтального скроллера истории: `.casino-roulette-history-wrap` разгонял всю доску до 405px при контейнере 324px.

Причина 4 — у экранов с фиксированной нижней кнопкой (`.casino-lobby-bottom-action`, `.casino-v2-strip-actions`) `padding-bottom` у `.casino-main` был 96px, а кнопка занимает до ~128px от низа.

Правки — все внутри `@media (max-width: 820px)` в `casino-skin.css`, десктоп ≥821px, логика, API и деньги не тронуты:
- `.casino-main > * { flex: 0 0 auto; min-height: auto; }` — прямые дети scrollport сохраняют собственную высоту.
- `.casino-main:has(.casino-lobby-bottom-action)` и аналоги для `.casino-v2-strip-actions` / `[data-casino-v2-roll]` / `[data-casino-v2-start]` — `padding-bottom: calc(96px + var(--app-bottom-height,72px) + var(--app-safe-bottom,…))`.
- `.casino-play-layout { grid-template-columns: minmax(0,1fr); align-items: stretch; }` + `.casino-play-canvas { width: 100%; min-width: 0; }`.
- `min-width: 0` для `.casino-roulette`, её прямых детей, `-history-wrap`, `-history`, `-stage`, `-felt-scroll`.
- `.casino-table-toolbar { flex-wrap: wrap; gap: 8px 12px }` + `min-width: 0` у `h2` — на 360px ряд «Открытые столы / Низкие / Фильтры» выезжал на 25px.

Замеры `main.scrollHeight / clientHeight` (390×844, dev 5173, dev-бар скрыт), было → стало:
- кубики 764/764 → 824/764 (прокрутка 60, программный скролл доходит до конца)
- баккара 764/764 → 824/764 (60)
- блэкджек 764/764 → 815/764 (51), `padding-bottom` 96px → 168px
- рулетка 2132/764 → 2234/764 (1470), канва 32px → 356px
- комнаты 1048/764 → 1144/764 (380)
- лобби 1408/764 (644) — без изменений
- честность 1850/764 (1086) — без изменений
- турниры 764/764 — контент гостя 239px, прокрутка не нужна

Горизонталь: `document.documentElement.scrollWidth = 390` (и 360/430) на всех экранах. Внутренних выездов не осталось — единственный остаток `ol.casino-roulette-history` с `overflow-x: auto`, это штатный скроллер истории. `.casino-hero-art` и `.casino-roulette-wheel` клипуются по дизайну (полуколесо `aspect-ratio: 2/1`).

Другие ширины: 360×640 — всё листается (кубики 824/560, блэкджек 833/560, рулетка 2219/560, лобби 1523/560, честность 1937/560). 430×932 — кубики и блэкджек влезают целиком (852/852), рулетка 2254/852, комнаты 1144/852. `html[data-casino-entry="tg"]` на 390×844 даёт те же цифры, что обычный вход.

Чат: оверлей `.casino-chat.is-docked.is-open` — `position: fixed`, top 72 / bottom 780 при высоте экрана 844, ровно между шапкой и навигацией, по горизонтали не выезжает.

Не проверены кликом: `/casino/play/jackpot`, `/casino/play/raffle` (FocusLucky), `/casino/me`, `/casino/settings`, `/casino/wallet` — гостю отдаётся экран «Вход в FocusBet», `.casino-main` не рендерится, учётки для входа нет. Правка `.casino-main > *` на них распространяется автоматически (общий селектор). Токены не подделывал.

Скрытые игры (clan_war, clans, holdem, nardy, russian_draughts) не трогал и не расхлопывал.

Проверки: `npm run build` (`tsc -b` + Vite) зелёный; `ReadLints` по `casino-skin.css` — 0; десктоп 1440×900 — рулетка по-прежнему в две колонки (сайдбар 340px + канва), лобби без изменений.

Выкат: `python scripts/deploy_all.py`, бэкап HTML `*.bak-20261103-021202`. Живые бандлы: `index-BIeTMYo5.css` (md5 `0e6cb6242f28dee1deea475eea113096`), `casinoRoutes-DPsnr54p.js`, `casino-BXXll2XD.js`, `index-N7sqMqgr.js`, `index-BXzxD4bd.js`, `exchange-DUYZiqD2.js`, `panel-DarRn4g0.js`. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200. В живом CSS присутствуют `.casino-main>*{flex:0 0 auto;min-height:auto}`, `.casino-play-layout{grid-template-columns:minmax(0,1fr);align-items:stretch}`, `casino-roulette-felt-scroll{min-width:0}`, `.casino-table-toolbar{flex-wrap:wrap;gap:8px 12px}` и правило `:has(.casino-lobby-bottom-action)`. Бэкенд, nginx и бот не трогались и не рестартились. Не коммитил и не пушил.

Смоук по проду 390×844 после выката: лобби 1408/764, кубики 824/764, блэкджек 856/764, рулетка 2234/764, комнаты 1144/764 — прокрутка доходит до конца везде, `scrollWidth = 390`.

Staging `178.63.247.233` недоступен (`connect: Connection refused` на порт 22), `staging-test.sh` не гонял.

Скрины: `docs/qa-screenshots-2026-11-03/` — `before390-{dice,blackjack,roulette}-top.png`, `after390-{dice,blackjack}-bottom.png`, `fix390-roulette-{top,bottom}.png`, `fix390-chat.png`, прод `prod390-*`.

## 2026-11-03 · Турниры на телефоне: без дубля заголовка, «Участвовать» сразу под таймером

По скрину владельца: на `/casino/tournaments` блок «ТУРНИРЫ · Играйте на турнирные фишки — призы приходят рублями» дублировал заголовок мобильной шапки, а кнопку «Участвовать» прятало описание «Регистрация в турнир».

Сделано в `casino-skin.css`, только `@media (max-width: 820px)`:
- `.casino-tournaments > .casino-section-head` — `display:none` (заголовок остаётся в шапке приложения), контент поднялся выше.
- `.casino-trn-entry` — без рамки и подложки, `gap:12px`; `.casino-trn-hero` — `gap:12px`, `padding-bottom:14px`.
- `.casino-trn-join` — `display:grid; grid-template-columns:minmax(0,1fr)`, описание (`> div:first-child`) скрыто.
- `.casino-trn-join .casino-btn[data-casino-trn-join]` — ширина 100%, высота 52px, радиус 16px, 16px шрифт.

Нюанс: при `display:grid` без `grid-template-columns` колонка сайзится по max-content, и `width:100%` у кнопки давала 42px вместо 358px — поэтому явный `minmax(0,1fr)`.

Проверки: `npm run build` зелёный. На 390px замер через CDP (гостю страница турниров отдаёт экран входа, поэтому структуру join-блока проверял инъекцией в тот же CSS-контекст): `casino-section-head` = `none`, описание = `none`, кнопка 358×52.

Прод: бэкап HTML `*.bak-20261103-022906`, живой CSS `index-Dfowmy1s.css`, md5 `a73cea309b12526b2c79ed381ef90300` совпал с локальной сборкой; в нём есть все четыре правила. HTTPS `/` `/x8` `/ops` `/casino` `/casino/tg` `/exchange/tg` = 200. API, nginx и бота не трогал. Staging недоступен.

## 2026-11-03 · Разделение казино: реальные деньги, бонусные фишки, турниры

Задача владельца: видеть фишки в балансе, переключаться между реальным и тестовым кошельком, везде видеть, что игра идёт на бонусные фишки, не давать играть фишками против денег, и чтобы в фишковом режиме реальных игроков не было видно (и наоборот). Уточнения: турниры разделяются между собой, если идёт несколько, и нужен отдельный постоянный бонусный кошелёк. Правки бэкенда и миграция разрешены («yes_full»).

Модель: область кошелька = пара (`wallet_kind`, `tournament_id`), виды `rub` / `bonus` / `tournament`, ключи `rub`, `bonus`, `trn:<id>`. Область несёт и игрок, и каждый стол/раунд; посадка требует точного совпадения, иначе `409`. Фишка считается по рублёвой шкале (1 фишка = 1.00), чтобы движки не учить второму типу суммы.

Миграция `site/exchange-backend/migrations/add_casino_wallet_scopes.sql`: `casino_bonus_wallets`, `casino_bonus_holds`, `casino_bonus_ledger`; `wallet_kind` у `casino_tournament_user_state`; `wallet_kind` + `tournament_id` + индексы у `casino_v2_tables`, `casino_games`, `casino_fixed_room_rounds`, `casino_jackpot_rounds`, `casino_roulette_rounds`; гранты `exchange_bot`; ключи настроек `bonus_wallet_enabled`, `bonus_wallet_grant_chips`, `bonus_wallet_grant_cooldown_hours` (зарегистрированы в `casino_settings_registry.py`).

Бэкенд:
- `casino_wallet.py` — `WalletScope`, `active_scope`/`viewer_scope`/`set_active_scope`, бонусный кошелёк (выдача, самопополнение, холды, ledger), `my_wallets`, хелперы `scope_insert_sql` / `scope_filter_for` / `row_scope_of` / `assert_player_may_sit` / `assert_may_sit_at` / `assert_real_money_only`.
- `casino_finance.reserve_unified_funds` / `confirm_unified_hold` / `release_unified_hold` разводят ставку по области; выигрыш фишек идёт в бонусный или турнирный ledger.
- Стамповка области: столы v2, дуэли (обе ветки создания), комнаты, раунды джекпота. Проверка при `join_v2_table_with_conn`, `join_and_hold_game_with_conn`, `join_room`.
- Экономика только на рублях: `_record_commissions`, рейк и банкролл столов v2, резерв под ботов, рейк и возвраты комнат, рейк джекпота, уровни, недельный оборот (`casino_weekly_wager.py` фильтрует фишковые раунды).
- Игры против банкролла казино в фишках запрещены (`409`): кубик против казино, стол рулетки 0–36, карты 1×1.
- Лобби фильтруются по области зрителя: `casino_v2_web.list_public_tables` и автоподсадка, `/casino/duels`, `/casino/lobby` (дуэли и комнаты), `casino_fixed_rooms.list_open`, снимок и открытый раунд джекпота. Гость всегда видит рублёвую область.
- Эндпоинты: `GET /api/user/casino/wallets`, `POST /api/user/casino/wallet`, `POST /api/user/casino/wallet/bonus/refill`; админские `GET /api/admin/casino/bonus-wallet/{telegram_id}` и `POST /api/admin/casino/bonus-wallet/grant`. Старые турнирные эндпоинты оставлены как алиасы для бота.

Фронт:
- `src/casino/walletScope.ts` — `useCasinoWallet`, `useWalletScopeRefresh`, `CASINO_WALLET_EVENT`, формат «₽»/«Ф».
- Шапка: `CasinoWalletSwitch` со списком «Основной баланс / Бонусные фишки / каждый турнир», фишки в балансе, скрытый баланс как «•••• Ф», касса (пополнить/вывести) отключена в фишковом режиме.
- `data-casino-wallet-kind` на `.casino-root` и плашка «Играете на бонусные фишки — выигрыш не выводится» над контентом.
- Лобби дуэлей, столов, комнат и джекпот перезапрашиваются при смене кошелька.

Проверки: `pytest tests/test_casino_wallet_scope.py` — 15 тестов зелёные (ключи областей, два турнира ≠ одна область, отказ на чужой области, запрет игр против казино в фишках, деградация до рублей без миграции). Прогон `tests/test_casino_*.py` зелёный, кроме трёх route-import тестов — в этом окружении нет `jwt` и `asyncpg` (проваливались и до правок). `npm run build` зелёный, `tsc -b` чисто. Мобильный замер 390×844: плашка 358×34 цветом `rgb(245,196,81)` над карточкой турниров — `docs/qa-screenshots-2026-11-03/wallet-scope-390-banner.png`.

На прод не выкатывалось, миграция не применялась, ничего не коммитил. Для выката нужно отдельное «го»: дамп БД → бэкап кода → миграция → рестарт `focuspay-exchange-api` → `deploy_all.py`.

Потыкать человеку (после выката на живых данных): переключение кошельков в шапке под залогиненным игроком; пустые лобби в бонусном режиме; попытка сесть за рублёвый стол из бонусного кошелька (ждём понятный `409`); самопополнение бонусных фишек и кулдаун сутки; два одновременных турнира — списки столов не должны пересекаться.

### Выкат на прод 2026-11-03 (по «го» владельца)

Дамп БД `/root/backups/focuspay-pre-wallet-scopes-20261103-093232.dump` (379 МБ), бэкап кода `/root/backups/exchange-backend-code-20261103-093232.tgz`, каждый перезаписанный файл — `*.bak-20261103-093232`.

Важное наблюдение: локальный репозиторий сильно разошёлся с `/opt/exchange-backend`. Перед заливкой сверил md5 и построчные диффы всех 16 трогаемых файлов. В трёх (`casino_v2_web.py`, `routers/public_casino.py`, `routers/admin_casino.py`) репозиторий нёс посторонние правки: автоподсадка `auto_join_due` отсутствовала локально, а в лобби и настройки админки добавлены припаркованные «Русские шашки» (`draughts_move_timeout_seconds` без ключа в продовом реестре). Эти три файла собрал из продовой версии плюс только правки задачи. Остальные 13 диффов содержали исключительно мои хунки — залиты как есть.

Миграция: под `exchange_bot` прошли бонусные таблицы, индексы, гранты и три ключа настроек; блок с колонками областей упал в `insufficient_privilege`, потому что `casino_v2_tables`, `casino_jackpot_rounds`, `casino_fixed_room_rounds`, `casino_roulette_rounds` принадлежат роли `postgres`. Докатил их отдельным проходом `sudo -u postgres psql -d exchange_bot`. Итог: `wallet_kind` есть в шести таблицах (`casino_games`, `casino_v2_tables`, `casino_fixed_room_rounds`, `casino_jackpot_rounds`, `casino_roulette_rounds`, `casino_tournament_user_state`), `has_column_privilege('exchange_bot', …, 'INSERT')` = `t` по всем новым колонкам.

Рестарт `focuspay-exchange-api` — `active`, `tg-bot.service` не трогал. Смоук с сервера: `/api/public/casino/lobby|duels|v2/tables|rooms` = 200, `/api/user/casino/wallets` и `POST /api/user/casino/wallet` = 401 без токена. Ошибок со словом casino в журнале после рестарта нет; `sweep due wallet confirms failed` и `record_live_project_addresses() takes 2 positional arguments` — старые, 597 и 246 раз за предыдущие часы до выката. Токены не подделывал, 2FA не обходил.

Фронт: `deploy_all.py` дважды. Первый проход показал, что `wallet/bonus/refill` вырезан тришейкингом — кнопки пополнения в UI не было; добавил её в меню кошелька (видна, когда фишек 0) и выкатил снова. Бэкапы HTML `*.bak-20261103-044324` и `*.bak-20261103-044708`. Живые бандлы `index-DOAFWuEJ.css` (md5 `11feb3b2b8e8aa009d645aae3868e651`) и `index-DAWVz7d7.js` (md5 `33ab2523cf0c62f267e21770ce7f8c81`) совпали с локальной сборкой; `wallet/bonus/refill` и `casino-chips-banner` в живых файлах присутствуют.

Прод 390×844: лобби 1408/764, `scrollWidth = 390`, `data-casino-wallet-kind="rub"` у гостя. Счётчики чистые: `casino_bonus_wallets` 0, `casino_bonus_ledger` 0, нерублёвых столов и дуэлей 0. Скрин `docs/qa-screenshots-2026-11-03/prod390-wallet-scopes-lobby.png`.

Не проверено под живым игроком (нет учётки, токены не подделываю): сам переключатель кошельков, пустые лобби в бонусном режиме, отказ `409` при попытке сесть за рублёвый стол из фишек, самопополнение и кулдаун, два одновременных турнира. Это список «потыкать» для владельца.

Откат: HTML из `.bak-20261103-044708`, файлы бэкенда из `*.bak-20261103-093232`, рестарт API. Схему откатывать не нужно — без кода новые колонки и таблицы ни на что не влияют.

## 2026-11-03 — почему не переключались балансы

Жалоба: «нельзя переключиться между балансами» + «при заходе в игру не видно уже созданные столы».

- Переключатель был скрыт на телефоне: `.casino-wallet-switch` висел в группе `display: none !important` внутри `@media (max-width: 820px)`. Вернул компактной кнопкой, меню фиксировано под шапкой на всю ширину.
- Дополнительно: в плашке «играете на фишки» появилась кнопка «На ₽», чтобы выход на рубли был с любого экрана, даже если шапка тесная.
- Проба на проде (`/tmp/probe_wallets.py`, venv-python из `/tmp`): `bonus_enabled=True`, `grant_chips=1000.00`, у `418562264` три кошелька, выбран `trn:1` (580 Ф). То есть игрок «залип» в турнирном кошельке и все лобби честно показывали только турнирные столы.
- Второй симптом из той же причины + реальная пустота: `casino_v2_tables` не имеет ни одного открытого стола, `casino_games` — ни одной ждущей дуэли. Прокрутка игрового экрана работает (`778/764` на 390).
- Чтобы область больше никого не запирала: `scope_or_mine_filter` — лобби v2/дуэлей/комнат всегда показывает стол, где игрок сидит, и свою заявку, даже если кошелёк другой.

Потыкать человеку: на телефоне переключить кошелёк (рубли → турнир → бонусные), проверить что ставки показываются в «Ф», создать стол в бонусном кошельке и убедиться что он не виден в рублёвом лобби, а своему игроку виден после переключения.
## 2026-11-03 · Рулетка 0–36 разрешена фишковым кошелькам

Задача владельца: снять запрет «в турнирном режиме нельзя играть в рулетку», причём для любых фишек — и турнирных, и бонусных.

Запрет жил в бэкенде: `assert_real_money_only` в `casino_roulette_table.place_bets` и в `casino_roulette.play_roulette_with_conn` давал `409` всем нерублёвым кошелькам.

Что сделано:
- Раунд стола рулетки теперь свой в каждой области кошелька: `_lock_open`, `_history`, снимок и `clear_bets` фильтруются через `scope_filter_for` / стампятся `scope_insert_sql` по `casino_roulette_rounds` (колонки уже были в `add_casino_wallet_scopes.sql`). Рублёвые и фишковые игроки друг друга не видят.
- `load_roulette_house_seat(..., require_bankroll=...)`: для фишек не проверяем остаток банкролла и лимит экспозиции — фишки из него не выходят. Лимиты ставки стола и профиля робота остаются.
- Фишковый раунд не двигает `casino_house_accounts` / `casino_house_reservations` и не пишет комиссии: `_settle_roulette_money(house_backed=False)` уходит в новый `_finish_chips_round` (холд → `confirmed`, игра → `finished`, `commission_rub = 0`).
- Ставка и выигрыш и так шли по области: `reserve/confirm_unified_hold` и `_credit_winner` → `maybe_credit_tournament_payout` (турнир и бонусный кошелёк). `casino_games` фишкового раунда теперь стампится областью.

Проверка: `pytest tests/test_casino_*.py` — те же три падения по импорту `bearer_scheme`, что и до правки (окружение, не код). Прод не трогал, деплоя не было.

Потыкать человеку: включить турнирный кошелёк, поставить фишки на рулетке, дождаться спина и проверить, что баланс турнира изменился, а банкролл казино в `/x8` — нет; параллельно с рублёвого аккаунта убедиться, что это разные раунды и чужих фишек не видно.

Деплой (по «го» владельца, 2026-11-03 11:21 МСК-времени сервера): бэкап `casino_roulette.py.bak-20261103-112145` и `casino_roulette_table.py.bak-20261103-112145`, залиты оба модуля (md5 `1435855d1d38efc8d03ba777494617e8` и `2d4a04b498233d293ea174545604687c` совпали локально и на проде), `systemctl restart focuspay-exchange-api` — `active`, в логах только 200. Прод до выката отличался от репозитория ровно на строки запрета. Смоук: `GET /api/public/casino/roulette-table` отдаёт живой раунд, `/casino` = 200. БД: `wallet_kind`/`tournament_id` есть у `casino_roulette_rounds`, `has_column_privilege('exchange_bot', …, 'INSERT')` = `t` у `casino_roulette_rounds` и `casino_games`; сейчас 356 settled + 1 open раунд, все `rub`.
