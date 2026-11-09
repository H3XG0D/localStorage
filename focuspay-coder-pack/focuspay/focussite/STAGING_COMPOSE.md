# Автономный staging Compose

`docker-compose.staging.yml` описывает изолированную топологию **FocusPay staging**: `postgres`, `redis`, `backend` и opt-in `casino-bot`. Gateway и frontend намеренно отсутствуют. Имя проекта — `focuspay-staging`; сеть и все persistent volumes имеют префикс `focuspay_staging_` и не пересекаются с `focuspay_local_*`.

> Этот runbook не запускает Compose. Не используйте эту топологию с production URL, IP, Telegram-токенами, PostgreSQL, PayFast или данными.

## Статус готовности

| Проверка | Статус |
| --- | --- |
| Fake PayFast contract tests | ready |
| Targeted backend PayFast tests | ready |
| Payment bootstrap static checks | ready |
| PayFast live E2E | pending: нужен disposable PostgreSQL |
| Casino E2E | ready for isolated staging run |
| Server bootstrap A | pending: clean reinstall and hardening |

## Prerequisites: чистый сервер и изоляция сети

Используйте только заново установленный и hardening-проверенный staging server. До начала работ Server bootstrap A должен подтвердить, что host, Docker daemon, volumes, сеть и CI runner не имеют общих ресурсов с production.

- Не выполняйте SSH, deploy, production cleanup, restart или remote migration из этого runbook.
- Не подключайте staging к production PostgreSQL/Redis, production DNS, публичным FocusPay endpoint, реальному Telegram или PayFast.
- Выделите отдельный GitHub Actions self-hosted runner с labels `self-hosted`, `linux`, `staging-isolated`; он не должен иметь production credentials, SSH-конфигурации или routes к production.
- Внутренняя сеть Compose — только `focuspay_staging_app_net`; published host ports для PostgreSQL, Redis, backend и Fake PayFast запрещены.
- Используйте только disposable volumes и synthetic fixtures. Production dump, PII, реальные реквизиты и реальные merchant/Telegram secrets запрещены.

## Staging environment contract

Создайте `focussite/.env.staging` из `focussite/.env.staging.example`; для casino smoke/E2E создайте соседний `/home/qwe/Desktop/focuspay-casino/.env.staging` из его example. Файлы находятся только в staging secret store, не в Git, командной строке, artifacts или логах.

Перед любым bootstrap или E2E выполните fail-closed preflight:

- `ENVIRONMENT=staging`.
- DB, Redis, public, merchant и callback URL указывают только на изолированные staging/loopback endpoints; в них отсутствуют `focuspay.org`, любой его поддомен и production IP `153.80.249.77`.
- `INTERNAL_API_SECRET` в точности совпадает с `STAGING_INTERNAL_API_SECRET`.
- Все обязательные secrets заполнены непустыми неплейсхолдерными значениями; placeholder и пустое значение — fail.
- Compose namespace остаётся `focuspay-staging`, а в итоговой topology нет `ports:` для PostgreSQL, Redis, backend и Fake PayFast.
- Fixtures исключительно synthetic; Telegram polling и real PayFast не запускаются.
- E2E разрешён только явным opt-in флагом. Его отсутствие — fail, а не skip успешного обязательного сценария.

Backend проверяет staging contract до сетевых клиентов: отклоняет production host/IP, пустые и placeholder значения, несовпадающий internal secret, некорректный `CASINO_EXCHANGER_ID` и отсутствующий test Telegram allowlist.

## Static validation before startup

Сначала выполняйте только проверки, которые не создают контейнеры, не используют сеть и не раскрывают секреты:

```bash
bash -n focussite/docker/staging-db/00-apply-migrations.sh
bash focussite/docker/staging-db/bootstrap_static_test.sh
(cd site/exchange-backend && python -m pytest -q tests/test_staging_config.py)
python -m pytest -q test_support/test_fake_payfast_http.py
python -m pytest -q site/exchange-backend/tests/test_payfast_http_fake.py
python -m pytest -q bot/tg_bot_btc/tests/test_payfast_http_fake.py
(cd site/exchange-backend && python -m pytest -q \
  tests/test_payfast_recovery_window.py tests/test_payfast_http_fake.py)
```

После получения env из staging secret store допускается только рендер topology без старта контейнеров:

```bash
cd focussite
docker compose --env-file .env.staging -f docker-compose.staging.yml config >/dev/null
```

Не публикуйте stdout этой команды в CI logs или artifacts: rendered configuration может содержать значения env. Эта проверка не запускает контейнеры. Проверяйте `name: focuspay-staging` и отсутствие published ports до bootstrap.

## Bootstrap profiles

Bootstrap выполняется только в уже подготовленной disposable PostgreSQL и только после static validation. Он не создаёт контейнеры и не обращается во внешнюю сеть.

### PvP profile

`pvp` — default profile для FocusCasino PvP/recovery fixtures. Он создаёт только synthetic players, approved binding, committed game, cashback-only funding и active holds с выключенным raffle. Он не применяет payment migrations и не создаёт PayFast records.

```bash
PGHOST=... PGPORT=... PGUSER=... PGDATABASE=... \
  bash focussite/docker/staging-db/00-apply-migrations.sh pvp
```

### Payments profile

`payments` — явный profile для synthetic payment schema и fixtures. Он создаёт synthetic exchanger, operators, shifts, одну confirmed external deal и минимальные ledger entries; Casino tables не устанавливаются.

```bash
PGHOST=... PGPORT=... PGUSER=... PGDATABASE=... \
  bash focussite/docker/staging-db/00-apply-migrations.sh payments
```

Не передавайте DSN/пароли в shell history или logs. Все профили одноразовые и fail-closed: partial/non-empty bootstrap завершается ошибкой до DDL. Для чистого повторного прогона нужна новая disposable database/volume.

### Full panel + PvP profile

`full-panel-pvp` создаёт полный synthetic bootstrap публичного сайта и панелей, затем Casino migrations и PvP fixtures: двух игроков, active chat binding, завершённую игру и игру `outcome_committed` с recovery holds. Он требует отдельную пустую database/volume; не используйте volume от `full-panel`, `pvp` или `payments`.

Для persistent runtime PostgreSQL volume задаётся как `STAGING_RUNTIME_POSTGRES_VOLUME=focuspay_staging_runtime_full_panel_pvp_postgres`. Смена профиля или volume после bootstrap требует новый одобренный synthetic volume.

## Fake PayFast and targeted tests

Fake PayFast contract tests и targeted backend PayFast tests готовы к локальному/CI запуску и используют только существующий fake/harness. Они не должны иметь real merchant credentials, callback URL вне loopback или внешнюю сеть.

CI запускает эти проверки только вручную через `workflow_dispatch` inputs `run_fake_payfast_contract` и `run_backend_payfast_tests`. Secret store для них не используется.

## PayFast opt-in E2E

PayFast live E2E использует только отдельный disposable Compose-проект и не принимает DSN от активной staging topology.

Prerequisites:

- изолированный self-hosted staging runner с Docker;
- `STAGING_E2E_PAYFAST=1`;
- уникальный `STAGING_E2E_PAYFAST_RUN_ID` из 12–32 строчных букв/цифр;
- Fake PayFast и callback receiver доступны только во внутренней сети disposable проекта; real PayFast и Telegram polling выключены.

Lifecycle создаёт собственные internal-only Compose network и PostgreSQL volume, bootstrap применяет только `payments` schema/fixtures к новой БД `e2e_payfast_<run-id>`, а teardown удаляет только volume, принадлежащий этому run ID. Он не читает, не использует и не удаляет `focuspay_staging_*` volumes.

```bash
STAGING_E2E_PAYFAST=1 STAGING_E2E_PAYFAST_RUN_ID='<unique-run-id>' \
  bash focussite/docker/staging-db/payfast-e2e-lifecycle.sh prepare
STAGING_E2E_PAYFAST=1 STAGING_E2E_PAYFAST_RUN_ID='<same-run-id>' \
  bash focussite/docker/staging-db/payfast-e2e-lifecycle.sh run
STAGING_E2E_PAYFAST=1 STAGING_E2E_PAYFAST_RUN_ID='<same-run-id>' \
  bash focussite/docker/staging-db/payfast-e2e-lifecycle.sh teardown
```

Не передавайте DSN/пароли в shell history или logs. CI job `payfast-e2e` доступна только вручную с `run_payfast_e2e=true` на `staging-isolated` runner и выполняет тот же lifecycle с cleanup через `trap`.

## Casino opt-in E2E

Casino E2E готова для isolated staging run, но не для обычного PR. Prerequisites: clean/hardened staging server, проверенный безопасный `.dockerignore` в соседнем `focuspay-casino`, оба staging env в secret store, запущенная изолированная base topology и выполненный `pvp` bootstrap.

CI job `casino-e2e` доступна только вручную с `run_casino_e2e=true` на `staging-isolated` runner. Runner обязан предоставить соседний ephemeral `focuspay-casino` workspace. Job передаёт staging env files только через masked CI secrets, fail-closed отказывается перезаписывать уже существующий env, создаёт `.env.staging` в ожидаемых Compose путях с `umask 077`, выставляет profile `casino-e2e`, где `STAGING_E2E=1` обязателен, и удаляет temporary files после run. Не включайте `casino-smoke`/`casino-e2e` в обычные PR jobs.

Casino build context находится в соседнем `/home/qwe/Desktop/focuspay-casino`. Пока не будет разрешён отдельный `.dockerignore` в этом каталоге, не запускайте casino build profile: Docker передаёт build context до инструкций `COPY`, поэтому локальные `.env` и артефакты нельзя надёжно исключить только Dockerfile.

## Post-start verification

После явно разрешённого isolated startup подтвердите:

1. namespace равен `focuspay-staging`, а PostgreSQL, Redis, backend и Fake PayFast не имеют published host ports;
2. backend healthcheck отвечает только во внутренней сети; он не является подтверждением наличия schema/Redis readiness;
3. использован правильный bootstrap profile и SQL assertions завершились успешно;
4. в логах нет Telegram polling, обращений к real PayFast или production URL/IP;
5. E2E completed только при соответствующем explicit opt-in, а fixtures/ledger остались synthetic и идемпотентными.

Любое нарушение contract, неполный bootstrap, внешний network access, production reference или отсутствие opt-in — fail. Остановите run и сохраните только безопасные диагностические метаданные без secrets/PII.

## Teardown and disposable cleanup

Обычная остановка сохраняет synthetic volumes для диагностики:

```bash
cd focussite
docker compose -f docker-compose.staging.yml down
```

Не используйте `-v` по умолчанию. Удаление disposable staging volumes возможно только после явного подтверждения, что они относятся к `focuspay_staging_`, содержат только synthetic data и больше не нужны для диагностики. Production cleanup и deploy commands в этот runbook не входят.

## Troubleshooting and pass/fail criteria

- **Staging config guard failed:** исправьте staging secret-store values; не ослабляйте validation и не заменяйте значения production аналогами.
- **Bootstrap refuses a non-empty DB:** создайте новую disposable staging DB/volume; не переигрывайте fixtures и ledger поверх существующих данных.
- **PayFast E2E cannot start:** статус остаётся pending до наличия disposable loopback PostgreSQL с payments schema. Не запускайте Compose/migrations удалённо в обход prerequisite.
- **Casino build/E2E blocked:** дождитесь clean server hardening и approved `.dockerignore` соседнего casino repository; не передавайте его local context в обычный CI.
- **Any secret appears in output:** остановите run, revoke/rotate по отдельной утверждённой процедуре и исключите значение из logs/artifacts; не копируйте его в issue или Git.

Проверка получает **pass** только если static guard, required bootstrap assertions и соответствующий opt-in E2E завершились успешно без production/external integrations. Любой skip обязательного live сценария, отсутствующий prerequisite или нарушенный isolation contract — **fail/pending**, но не green result.

## Long-lived staging runtime

`docker-compose.staging-runtime.yml` — отдельная runtime-топология для изолированного staging. Её namespace, сети и volumes имеют префикс `focuspay_staging_runtime_` и не пересекаются с disposable `focuspay_staging_` или local ресурсами. В ней есть PostgreSQL, Redis, Fake PayFast, bootstrap, backend и gateway. Только gateway публикуется на `127.0.0.1:${STAGING_RUNTIME_HTTP_PORT:-18080}`; остальные сервисы доступны лишь во внутренних Compose-сетях.

Создайте защищённый `/etc/focuspay-staging/runtime.env` из `.env.staging-runtime.example` (права `0600`) и запускайте через контролируемый скрипт:

```bash
cd /opt/focuspay
STAGING_RUNTIME_ENV_FILE=/etc/focuspay-staging/runtime.env \
  bash focussite/scripts/staging-runtime-update.sh --apply
```

`staging-runtime-preflight.sh` проверяет env contract, секреты-плейсхолдеры, namespace, отсутствие published internal ports и loopback binding gateway до создания/обновления контейнеров. Он также fail-closed требует явных host firewall `DROP`/`REJECT` правил для production IP `153.80.249.77` в цепочках `OUTPUT` и `DOCKER-USER`. Наличие обычного default route само по себе допустимо: он нужен для разрешённого egress, например тестового Telegram. До запуска инфраструктурная команда обязана установить и сохранить правила на изолированном host; скрипты не меняют firewall и не выполняют remote actions.

Примеры установки (выполняет только инфраструктурная команда после проверки текущей firewall policy; правила должны переживать reboot):

```bash
# UFW host egress (если UFW управляет OUTPUT policy)
sudo ufw deny out to 153.80.249.77

# Docker forwarding path: правило должно быть до разрешающих Docker rules.
sudo iptables -I DOCKER-USER 1 -d 153.80.249.77 -j DROP
```

Для nftables эквивалентно добавьте `ip daddr 153.80.249.77 drop` в host output chain и в forward chain, через которую проходит Docker traffic. Preflight использует `iptables -S OUTPUT` и `iptables -S DOCKER-USER`, поэтому nftables-only host должен предоставить совместимый `iptables-nft` view либо использовать одобренный эквивалентный firewall backend. Не заменяйте блокировку только DNS-правилом: IP-блок обязателен.

Проверка после запуска:

```bash
STAGING_RUNTIME_ENV_FILE=/etc/focuspay-staging/runtime.env \
  bash focussite/scripts/staging-runtime-health.sh
```

Шаблон `systemd/focuspay-staging-runtime.service` предназначен только для изолированного staging host и пользователя `focuspay-staging`; до установки проверьте пути `/opt/focuspay` и `/etc/focuspay-staging/runtime.env`. `bot` и `casino-smoke` находятся в opt-in Compose profiles и дополнительно требуют явный env-флаг; они не запускаются в обычном runtime update.
