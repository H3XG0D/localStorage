# Persistent staging runtime (24/7)

Runbook for the approved, long-lived **isolated staging** environment on `178.63.247.233`. It is not a production deployment procedure. Do not expose its UI publicly, connect it to production infrastructure, use production credentials/data, or promote it to production without the approval gate at the end of this document.

## Карта окружений

| Назначение | Хост и runtime | Код и данные | Telegram |
| --- | --- | --- | --- |
| Production | `153.80.249.77`; backend unit `focuspay-exchange-api`, polling unit `tg-bot.service`, webhook unit `tg-bot-webhook.service` | Backend: `/opt/exchange-backend`; exchange bot: `/opt/tg_bot_btc`; production DB и webroot существуют только здесь | Только production identities и реальные чаты |
| Persistent staging | `178.63.247.233`; Compose project `focuspay-staging-runtime` | Checkout: `/opt/focuspay`; protected env: `/etc/focuspay/staging-runtime.env`; named volumes: `focuspay_staging_runtime_*` | Только staging identities и выделенные test chats |
| Локальная разработка | Рабочая станция | Локальная ветка и незакоммиченные изменения; не источник production deployment | Боты по умолчанию не запускаются |

Никогда не синхронизируйте рабочие каталоги между серверами через `scp`/архивы и не редактируйте production-код «на месте». Окружения получают одну и ту же утверждённую Git-ревизию или собранный из неё артефакт, но хранят разные секреты и данные.

## Repository assets and scope

The repository currently provides:

- `docker-compose.staging-runtime.yml` — persistent Compose topology, named `focuspay-staging-runtime`.
- `.env.staging-runtime.example` — required environment-variable contract.
- `docker/nginx.staging-runtime.conf` — gateway configuration.
- `docker/staging-db/` — bootstrap/migration scripts and synthetic fixtures.

The runtime publishes only `gateway` on `127.0.0.1:${STAGING_RUNTIME_HTTP_PORT:-18080}`. PostgreSQL, Redis, backend and Fake PayFast are internal-only. The `bot` and `casino` Compose profiles are opt-in; both run real staging polling processes only after their corresponding `STAGING_RUNTIME_ENABLE_*` value is set to `1` in the protected server environment file.

The repository also provides `scripts/staging-runtime-preflight.sh`, `scripts/staging-runtime-health.sh`, `scripts/staging-runtime-update.sh`, and `systemd/focuspay-staging-runtime.service`. Use those reviewed assets rather than reproducing lifecycle commands by hand.

## Еженедельный выпуск без расхождения версий

1. Работайте локально в отдельной Git-ветке. Незакоммиченная рабочая папка не может быть источником staging или production deploy.
2. Выполните применимые тесты и сборку, затем зафиксируйте утверждённый commit SHA: `git status --short` должен быть пустым, а `git rev-parse HEAD` — записан.
3. На staging сначала сохраните предыдущий SHA, убедитесь в чистоте checkout, затем переключите `/opt/focuspay` ровно на этот approved SHA. Запустите `staging-runtime-update.sh --apply`, healthcheck и ручной smoke через SSH tunnel.
4. Только после отдельного production approval выкатывайте **этот же SHA**. Для frontend используйте `focussite/frontend/scripts/deploy_all.py`, чтобы `/`, `/x8` и `/ops` обновлялись вместе. Backend и bot обновляются только по утверждённым production unit и каталогам из таблицы выше.
5. На каждом этапе фиксируйте SHA и результат healthcheck. Если checkout на staging или production dirty, остановитесь: сначала выделите или зафиксируйте посторонние изменения.

Ни staging, ни production не получают код из «текущей папки» разработчика. Это исключает расхождение: меняются версии через Git, а не копии каталогов.

Исключение только для изолированного staging `178.63.247.233` на время работы по плану казино: прямая заливка рабочей папки разрешена скриптом `scripts/staging-sync.sh` (rsync в `/opt/focuspay` и `/opt/focuspay-casino`, затем `staging-runtime-update.sh --apply`). На production правило «только утверждённый commit SHA» действует без изменений: ни `scp`/архивы, ни грязное дерево на `153.80.249.77`.

## Approval, prerequisites and isolation checks

Before copying code or creating secrets, record approval for this exact host and confirm all of the following:

1. `178.63.247.233` is a dedicated staging host, with no production containers, volumes, Docker contexts, SSH keys, CI runner, VPN routes, DNS records, or credentials.
2. The host firewall allows SSH only from approved administrator addresses. Do not open the staging UI port to the Internet; port `18080` stays bound to loopback.
3. Docker and Compose are installed from a supported source; the staging operator can use them without sharing a production account or Docker socket access.
4. Repository checkout and the sibling paths referenced by Compose are present and trusted. In particular, the Compose build/migration inputs resolve from the staging checkout, not a production checkout.
5. No production PostgreSQL/Redis DSN, production IP (`153.80.249.77`), `focuspay.org` hostname/subdomain, production PayFast endpoint, merchant credential, production Telegram bot, real user data, payment details, receipts, or PII is supplied.
6. Fixtures remain synthetic. Persistent named volumes are staging-only and begin with `focuspay_staging_runtime_`.
7. `scripts/staging-runtime-preflight.sh` must pass before starting or updating: it requires explicit `DROP`/`REJECT` firewall rules for `153.80.249.77` in both host `OUTPUT` and Docker `DOCKER-USER`. A default route is expected for Telegram polling and is not itself a failure; missing deny rules are a hard stop.
8. `docker compose --env-file /etc/focuspay/staging-runtime.env -f docker-compose.staging-runtime.yml config` is reviewed locally without copying its output to tickets, chat, CI logs, or artifacts. Rendered config may contain secrets.

Fail closed: any failed or uncertain isolation check stops the setup. Escalate it; do not substitute production values to make it start.

## Telegram test identities and chats

Create two **new staging-only** bot identities in BotFather. Do not reuse, rename, or revoke a production bot.

1. In BotFather, revoke any previously issued tokens for the two staging identities, then generate new tokens for both. Use distinct staging names/usernames that cannot be confused with production.
2. Create two distinct test-only Telegram chats: one controlled test-user chat for the runtime bot, and a separate operator/observer chat. Never use production group chats, operator chats, or customer conversations.
3. Send tokens only through an approved secret-manager/admin-console workflow. Do **not** paste, dictate, upload, or include tokens in chat, shell history, commit messages, screenshots, terminal recordings, CI output, or issue attachments.
4. Place both new tokens, their distinct usernames/IDs, and only dedicated test chat/admin IDs in `/etc/focuspay/staging-runtime.env`. `TELEGRAM_BOT_TOKEN` with `TELEGRAM_BOT_USERNAME`, `STAGING_TELEGRAM_BOT_USERNAME`, `TELEGRAM_BOT_ID`, and `STAGING_TELEGRAM_BOT_ID` belongs to the exchange bot; both username variables and both ID variables must match the identity returned by Bot API. `BOT_TOKEN` with `CASINO_STAGING_TELEGRAM_BOT_*` belongs to the casino bot. Do not invent a new variable or use either token outside this isolated host.
5. Before enabling either polling profile, confirm that bot has no webhook and that its chat is isolated. Enable only the profile being tested (`bot` or `casino`); both remain disabled by default.

## Secret file on the server

Use a root-owned directory and a root-owned secret file; never copy `.env.staging-runtime.example` with real values into the repository.

```bash
sudo install -d -o root -g root -m 0700 /etc/focuspay
sudo install -o root -g root -m 0600 /dev/null /etc/focuspay/staging-runtime.env
sudoedit /etc/focuspay/staging-runtime.env
sudo stat -c '%a %U:%G %n' /etc/focuspay/staging-runtime.env
# expected: 600 root:root /etc/focuspay/staging-runtime.env
```

Populate every required field from `.env.staging-runtime.example` with unique non-placeholder staging values. Keep these invariants:

- `ENVIRONMENT=staging`, `STAGING_DISABLE_BACKGROUND_TASKS=true`, `STAGING_BOOTSTRAP_PROFILE=full-panel-pvp` и `STAGING_RUNTIME_POSTGRES_VOLUME=focuspay_staging_runtime_full_panel_pvp_postgres`. Volume выделен только для этого нового одноразового bootstrap-профиля: не переиспользуйте данные `full-panel`.
- Уникальные staging-only `STAGING_SYNTHETIC_ADMIN_USERNAME`, `STAGING_SYNTHETIC_ADMIN_PASSWORD`, `STAGING_SYNTHETIC_CLIENT_OPERATOR_PASSWORD` и `STAGING_SYNTHETIC_FINANCE_OPERATOR_PASSWORD`. Имена fixture-операторов фиксированы: `fixture_full_client_ops` и `fixture_full_finance_ops`; их пароли остаются только в защищённом env-файле.
- Unique staging-only `POSTGRES_*`, `DATABASE_DSN`, `SECRET_KEY`, `INTERNAL_API_SECRET`, merchant/fake-PayFast keys, and Telegram token.
- `INTERNAL_API_SECRET` exactly equals `STAGING_INTERNAL_API_SECRET`.
- `ADMIN_TELEGRAM_IDS` includes `940001` and `FINANCE_OWNER_TELEGRAM_ID=940001` (synthetic full-panel admin fixture from bootstrap).
- `DATABASE_DSN` targets service host `postgres`; `REDIS_URL` targets `redis`; public/merchant/callback/receipt URLs stay on Compose-internal hosts as shown in the example.
- `STAGING_RUNTIME_ENABLE_BOT=0` and `STAGING_RUNTIME_ENABLE_CASINO=0` initially.

Do not run `printenv`, `env`, `set`, `docker compose config` to a captured log, or `systemctl show` in a way that reveals values. If any secret appears outside the server secret store, stop work, revoke/rotate it, and record only the secret *name* in the incident.

## First start and health checks

Run from the `focussite` directory in the staging checkout. Commands use the root-only secret file directly and never export it into the interactive shell. Start only after the firewall preflight has passed:

```bash
cd /path/to/focuspay/focussite
sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env \
  ./scripts/staging-runtime-update.sh --apply
sudo STAGING_RUNTIME_ENV_FILE=/etc/focuspay/staging-runtime.env \
  ./scripts/staging-runtime-health.sh
```

Expected steady state: `postgres`, `redis`, `fake-payfast`, `backend`, and `gateway` are running/healthy; `staging-bootstrap` has exited successfully; `bot` is absent unless explicitly enabled. Confirm no unintended published ports:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo docker network inspect focuspay_staging_runtime_app_net
```

The only acceptable host publication from this Compose project is loopback `127.0.0.1:18080` (or the explicitly approved alternate `STAGING_RUNTIME_HTTP_PORT`). Treat a public bind, production hostname/IP, external payment call, or production data reference as a stop condition.

## UI access through SSH tunnel

Use an SSH local-forward from an approved administrator workstation; do not change host firewall/Nginx or publish the port.

```bash
ssh -N -L 18080:127.0.0.1:18080 <staging-user>@178.63.247.233
```

Open `http://127.0.0.1:18080` locally while the tunnel runs. For a non-default runtime port, change the remote and local ports deliberately. Do not use `-g`, reverse tunnels, public sharing services, or browser links that expose the staging instance.

## Bot mode: polling by default, webhook only by opt-in

The safe default is **bot disabled**. When approved to test the staging bot, use polling with the isolated runtime identity and chats. Confirm BotFather/API shows no webhook first; no externally reachable HTTPS endpoint is required.

1. Change only `/etc/focuspay/staging-runtime.env` using `sudoedit`: set `STAGING_RUNTIME_ENABLE_BOT=1` or `STAGING_RUNTIME_ENABLE_CASINO=1` for the profile being tested.
2. Start the matching opt-in profile:

```bash
cd /path/to/focuspay/focussite
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml --profile bot up -d bot
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml --profile casino up -d casino-bot
```

3. Review logs for the staging bot identity and absence of production URLs/chats. Do not paste log lines containing credentials or user content into chat.

Webhook mode is **not enabled by this runbook**. It requires a separate explicit approval covering a staging-only public HTTPS endpoint, ingress/firewall review, a webhook secret/verification method, BotFather webhook registration, rollback to polling, and evidence that the endpoint cannot route to production. Do not enable it merely because the staging host is persistent.

## Routine operations: status, logs, update, rollback

Use `sudo` commands below so the protected env file is readable without weakening its permissions.

```bash
# status and health
cd /path/to/focuspay/focussite
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml ps
curl --fail --silent --show-error http://127.0.0.1:18080/healthz

# bounded, service-specific logs; do not redirect/archive unredacted output
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml logs --tail=200 gateway backend
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml --profile bot logs --tail=200 bot

# graceful stop; persistent volumes are retained
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml down
```

For an approved update, first preserve the current, known-good Git revision and validate the target revision before starting containers. Do not update from an unreviewed working tree and do not use production deploy scripts.

```bash
cd /path/to/focuspay
git status --short
git rev-parse HEAD                 # record as PREVIOUS_REVISION outside secret-bearing logs
git fetch --tags
git checkout <approved-revision>
cd focussite
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml up -d --build
curl --fail --silent --show-error http://127.0.0.1:18080/healthz
```

If the update fails, stop it, return the checkout to the recorded revision, rebuild, start, and re-run health checks:

```bash
cd /path/to/focuspay
git checkout <PREVIOUS_REVISION>
cd focussite
sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml up -d --build
curl --fail --silent --show-error http://127.0.0.1:18080/healthz
```

Do not use `down -v`, `docker volume rm`, image/volume prune, or database reset during ordinary rollback. Persistent volumes may contain required staging state. Their deletion requires explicit approval after confirming every affected volume is staging-only and only synthetic data is present.

## systemd supervision

Install the reviewed `systemd/focuspay-staging-runtime.service` only after the preflight passes. It invokes the protected env file and approved Compose topology; it does not embed secrets. Verify the rendered unit on the host with `systemd-analyze verify`, then run a reviewed start/restart test before enabling it at boot. Do not add an ad-hoc unit or change its command to include tokens, DSNs, or other secrets.

## Manual production approval gate

Staging success does **not** authorize production work. Before any production deployment, data migration, DNS/ingress change, production token issuance, webhook registration, service restart, or use of production deploy tooling, obtain explicit manual approval from the authorized production owner.

The approval must identify the exact revision, target production host/environment, change window, rollback owner and method, tested staging evidence, and confirmation that no staging secret/data/configuration will be promoted. Without this recorded approval, stop at staging.
