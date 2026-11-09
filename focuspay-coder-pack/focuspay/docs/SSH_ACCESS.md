# SSH-доступ к серверам FocusPay

Для разработчиков с выданным ed25519-ключом. Парольный вход на оба живых хоста **выключен**. Секреты (`.env`, DSN, токены, пароли панелей) в этот файл не входят и в чат/git не кладутся.

Ключ с комментарием `N3Lopuh` (fingerprint `SHA256:09jaQwLsWexloJ5l5JGlwpSBmYZGhniqCW41T38cojg`) добавлен 2026-09-07.

Ключ дизайнера `miltos@windows` (fingerprint `SHA256:fPaVipgrm/iXrCCyGmB91Pyt0VZjmOMXwTkJ2IRWf9o`) добавлен 2026-10-12 в `root` на проде `153.80.249.77`. Staging `178.63.247.233` в этот момент не отвечал (`No route to host`).

## Живые хосты

| Алиас | IP | Пользователь | Назначение |
|---|---|---|---|
| `focuspay` | `153.80.249.77` | `root` | **Production.** Сайт, API, бот, БД. Реальные деньги и персонал. |
| `focuspay-test` | `178.63.247.233` | `focuspay-staging` | **Staging.** Docker Compose, синтетические данные. Root SSH запрещён; sudo без пароля. |

Старый VPS `216.73.157.10` (`focuspay-old`) мёртв: маршрута нет, не использовать.

## Настройка у себя (один раз)

1. Приватный ключ, парный к выданному публичному, лежит локально (обычно `~/.ssh/id_ed25519`). Права: `chmod 600` на ключ, `chmod 700` на `~/.ssh`.
2. В `~/.ssh/config` добавь:

```
Host focuspay
    HostName 153.80.249.77
    User root
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30

Host focuspay-test
    HostName 178.63.247.233
    User focuspay-staging
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30
```

`IdentitiesOnly yes` обязателен: на проде `MaxAuthTries 3` и стоит fail2ban. Если ssh переберёт чужие ключи — бан по IP.

3. Проверка:

```bash
ssh -o BatchMode=yes focuspay 'hostname; whoami'
ssh -o BatchMode=yes focuspay-test 'hostname; whoami; id'
```

Ожидание: прод — `root` на `6900291997-hkyzmny.dhost.su`. Staging — `focuspay-staging` на `29347-25-08-2026.dedik.io`.

Первый коннект иногда рвётся (`Authentication failed` / `Server connection dropped`) — подожди 8–10 секунд и повтори. Это rate-limit/MaxStartups, не «ключ не подходит».

Прямые команды без алиаса:

```bash
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes root@153.80.249.77
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes focuspay-staging@178.63.247.233
```

## Production `153.80.249.77`

Сайт: `https://focuspay.org`. Панели: `/x8` (админ), `/ops` (оператор). HTTP/HTTPS снаружи принимает nginx; 80/443 только с Cloudflare. SSH (22) открыт. PostgreSQL и API слушают localhost.

| Что | Где / unit |
|---|---|
| FastAPI | `/opt/exchange-backend`, `focuspay-exchange-api.service` (uvicorn `:8000`) |
| Python venv API | `/opt/exchange-backend/venv` |
| Telegram-бот | `/opt/tg_bot_btc`, `tg-bot.service` (polling) |
| Payfast webhook | `tg-bot-webhook.service` (`127.0.0.1:8081`) |
| Casino-бот | `focuspay-casino-bot.service` |
| Webroot | `/var/www/focuspay.org/` (`index.html`, `panel.html`, `/assets/`) |
| nginx | `sites-enabled/focuspay.org` (+ onion / traders) |
| PostgreSQL | `postgresql@14-main`, только `127.0.0.1:5432` |
| Redis | `redis-server.service` |
| Системный юзер сервисов | `focuspay` (не логинься под ним по SSH) |

Сервисы крутятся от `focuspay`. Код на диске не править «на месте»: выкат идёт из git/артефакта. `.env` на сервере не копировать, не печатать, не коммитить.

Probe Python **не** запускай из `/opt/exchange-backend` (`operator.py` затеняет stdlib). Из `/tmp`:

```bash
/opt/exchange-backend/venv/bin/python
```

DSN — строка `DATABASE_DSN` в `.env`, не в чат.

Read-only ориентиры:

```bash
ssh focuspay 'systemctl is-active focuspay-exchange-api tg-bot.service tg-bot-webhook.service nginx'
ssh focuspay 'stat -c "%y %n" /var/www/focuspay.org/index.html /var/www/focuspay.org/panel.html'
```

Рестарт unit, правки nginx, SQL, выкат фронта (`focussite/frontend/scripts/deploy_all.py`) — только после явного «го» владельца и бэкапа. Не `deploy_all.py` «посмотреть как поедет».

Локальный `npm run dev` во `focussite/frontend` по умолчанию проксирует `/api` на боевой хост. Мутации на живых заявках не делать ради проверки UI.

## Staging `178.63.247.233`

Изолированный стенд. Не ходить с него на прод (UFW DENY OUT на `153.80.249.77`). Не подставлять прод-токены, прод-DSN, прод-ботов.

| Что | Где |
|---|---|
| Checkout FocusPay | `/opt/focuspay` |
| Checkout казино | `/opt/focuspay-casino` |
| Секреты runtime | `/etc/focuspay/staging-runtime.env` (root, `600`) |
| Compose | `focuspay-staging-runtime` |
| Gateway (туннель) | `127.0.0.1:18081` → контейнер 8080 |
| Play-preview | хост nginx `:18082` (публичный preview, не путать с туннелем) |

Рядом крутится старый compose `focuspay-staging-*` без публикации на хост. Рабочий runtime — имена `focuspay-staging-runtime-*`.

Заход в UI через локальный туннель, не открывая порт наружу:

```bash
ssh -N -L 18081:127.0.0.1:18081 focuspay-test
```

В браузере: `http://127.0.0.1:18081/` (сайт), `/x8`, `/ops`. Не использовать `-g` и не светить staging в интернет.

На сервере:

```bash
ssh focuspay-test
cd /opt/focuspay/focussite
dc() { sudo docker compose --env-file /etc/focuspay/staging-runtime.env \
  -f docker-compose.staging-runtime.yml "$@"; }
dc ps
```

`printenv`, `docker compose config` в лог/чат не гонять — в env секреты. Runbook: [`focussite/STAGING_RUNTIME.md`](../focussite/STAGING_RUNTIME.md).

## Что читать до первой правки

1. [`AGENTS.md`](../AGENTS.md) — канон: что трогать, что нельзя, как деплоить.
2. [`docs/DEVELOPER_ONBOARDING.md`](DEVELOPER_ONBOARDING.md) — карта репо и потоков.
3. [`docs/FROZEN.md`](FROZEN.md) — запреты без human OK.
4. [`docs/PERMISSION_MATRIX.md`](PERMISSION_MATRIX.md) — если задача про `/x8` или `/ops`.

Код: фронт — `focussite/frontend/`. Backend — `site/exchange-backend/` (на проде не переписывать без согласия). Бот — `bot/tg_bot_btc/`. Мёртвая копия `~/Desktop/tg_bot_btc` не используется.

## Жёсткие правила

- Не коммитить, не пушить, не деплоить на прод без явной просьбы.
- Не класть `.env`, ключи, пароли, JWT в git, тикеты, скриншоты.
- Не форджить JWT и не обходить 2FA.
- Не `docker compose down -v` на staging: снесёт named volume с данными стенда.
- Не править `site/focuspay.org/` и `focus-panel/` как код — это референсы.
- Если fail2ban забанил IP после кривых попыток входа — писать владельцу, не долбить порт 22.
