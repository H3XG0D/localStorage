# FocusPay local containers

This setup is local-only. It does not deploy, connect to, or change the production server.

Services:

- `gateway`: frontend static files and the only host-published HTTP port.
- `backend`: FastAPI exchange API.
- `bot`: Telegram polling process.
- `bot-webhook`: merchant callbacks, receipt files, and Mini App endpoints.
- `db`: PostgreSQL.
- `redis`: internal rate-limit and IP-blocklist storage.

The backend and bot images contain the active source trees from `site/exchange-backend` and
`bot/tg_bot_btc`. The backend needs bot modules for the existing status and review bridges;
this is code duplication inside images, not a shared writable source mount.

## First run

From PowerShell:

```powershell
Set-Location focussite
Copy-Item .env.docker.example .env.docker
notepad .env.docker
docker compose --env-file .env.docker config
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
```

Set a real local Telegram token and replace all `CHANGE_ME` values before starting the bot.
`FOCUSPAY_DB_SEED_DUMP` must point to a local schema dump. The dump is mounted read-only into
PostgreSQL and is not sent to Docker build contexts or the server.

Open the local gateway at `http://localhost:8080`. The port is bound to loopback only and is
not reachable from another device on the LAN.

## Port policy

Only `gateway` has a Compose `ports` entry. The following services have no host ports:

- PostgreSQL `5432`
- Redis `6379`
- FastAPI `8000`
- merchant webhook `8081`
- optional Telegram webhook `8082`

These ports are reachable only through Docker service names and the gateway routes. Do not add
`ports` to internal services. Change `FOCUSPAY_HTTP_PORT` only when the local port is occupied.

## Safe local defaults

- Telegram runs in polling mode unless `TELEGRAM_WEBHOOK_URL` is explicitly set.
- OpenAPI and ReDoc are disabled and blocked by the gateway.
- Secrets are supplied through `.env.docker`, which is ignored by git.
- Containers run without added capabilities and with `no-new-privileges`.
- Application containers use a read-only root filesystem and temporary filesystems for `/tmp`.
- Receipts, chat uploads, avatars, bot state, logs, and PostgreSQL data use named Docker volumes.

## Stop and inspect

```powershell
docker compose --env-file .env.docker logs --tail=200 gateway backend bot bot-webhook
docker compose --env-file .env.docker down
```

`down` keeps named volumes. Add `-v` only when intentionally deleting the local database and
uploaded files.
