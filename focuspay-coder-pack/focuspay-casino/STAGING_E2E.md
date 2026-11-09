# Casino staging PvP/recovery E2E

Этот runner проверяет live lifecycle Casino PvP через staging FastAPI и PostgreSQL из внутренней Compose-сети. Он не запускает polling, не импортирует Telegram SDK для отправки сообщений и не обращается к PayFast.

## Обязательные safety-инварианты

- Запуск возможен только при `ENVIRONMENT=staging` и явном `STAGING_E2E=1`.
- API должен быть ровно `http://backend:8000`, а `DATABASE_DSN` должен ссылаться на hostname `postgres`. Любой URL/DSN с `focuspay.org` или `153.80.249.77` отклоняется до первого сетевого вызова.
- Нужны внутренний staging token и DSN из staging secret store. Runner не выводит их значения.
- Разрешены только синтетические fixture ID: игроки `100000001`, `100000002`, администратор `100000003` и игровой чат `-1001234567890` (`https://t.me/focuspay_fixture`). Любой другой Telegram ID отклоняется адаптером.
- PostgreSQL используется только для durable assertions. Runner не выполняет `DELETE`, не удаляет volumes и не модифицирует bootstrap fixtures напрямую.

Сценарии создают уникальные `e2e-*` game IDs. Поэтому запуск предназначен для свежего disposable bootstrap staging DB: winner-кейсы намеренно меняют только синтетические balances и ledger этого изолированного окружения.

## Запуск

Подготовить изолированный staging bootstrap с fixture SQL и staging secret files, затем из `focussite/`:

```bash
docker compose -f docker-compose.staging.yml --profile casino-e2e up \
  --build --abort-on-container-exit --exit-code-from casino-e2e casino-e2e
```

`casino-e2e` не публикует host ports. Он использует backend image, read-only mount Casino sources и внутреннюю сеть `app_net`; production Compose/SSH/deploy не задействованы.

После завершения допустимый teardown:

```bash
docker compose -f docker-compose.staging.yml --profile casino-e2e down
```

Не использовать `-v`: volumes и содержащиеся в них staging данные не удаляются runner-ом или teardown-командой.

## Проверяемый контур

- `ActiveGameChatGuard` пропускает только fixture game chat.
- `/allgames` в личке формирует только navigation link без финансового lifecycle.
- Два игрока проходят create/hold, join/hold, CAS persist, commit и idempotent settle с проверкой balances, holds, ledger, outbox и state version.
- Отказ synthetic публикации карточки после hold приводит к `card_publication_failed`, release и очистке PvP cache.
- Новый recovery worker завершает committed draw/cancel/timeout; waiting/active без immutable outcome остаются pending/manual-review кандидатами.
- Повторный recovery lease и outbox retry не создают второй settlement, ledger movement или outbox row.
