# Cloudflare для focuspay.org (регистратор Njalla)

Сейчас DNS у **Njalla** → трафик идёт напрямую на `178.236.252.170`. Cloudflare ещё не подключён.

## Шаг 1 — аккаунт Cloudflare (5 мин)

1. Откройте https://dash.cloudflare.com/sign-up
2. Зарегистрируйтесь (email + пароль)
3. **Add a site** → введите `focuspay.org` → план **Free**
4. Cloudflare покажет **2 nameserver** вида:
   - `ada.ns.cloudflare.com`
   - `bob.ns.cloudflare.com`  
   (у вас будут свои — скопируйте их)

## Шаг 2 — смена NS в Njalla (2 мин)

1. Войдите на https://njal.la
2. Домен **focuspay.org** → **Nameservers**
3. Выберите **Custom nameservers**
4. Вставьте **оба** NS от Cloudflare (из шага 1)
5. Сохраните

Ожидание: от 5 минут до 24 часов (обычно 15–30 мин).

## Шаг 3 — API Token (2 мин)

1. Cloudflare → **My Profile** → **API Tokens**
2. **Create Token** → шаблон **Edit zone DNS**
3. Zone Resources: **focuspay.org**
4. Создать → скопировать токен (показывается один раз)

На своём ПК:

```bash
cd /home/qwe/Desktop/tg_bot_btc
cp deploy/.cloudflare.env.example deploy/.cloudflare.env
chmod 600 deploy/.cloudflare.env
# Вставьте токен в CLOUDFLARE_API_TOKEN=
```

## Шаг 4 — автонастройка (одна команда)

Когда в Cloudflare статус зоны **Active**:

```bash
./deploy/cloudflare-apply.sh
```

Скрипт сам:
- включит **оранжевое облако** (прокси) на `focuspay.org` и `www`
- SSL **Full (strict)** + Always HTTPS
- WAF **Skip** для `/callback` (без капчи для Payfast)
- rate limit на `/callback` (если план позволяет)

## Шаг 5 — проверка

```bash
curl -sI https://focuspay.org/api/health | grep -i cf-ray
```

Должна быть строка `cf-ray: ...` — значит прокси работает.

## Шаг 6 — на сервере (после cf-ray)

```bash
ssh focuspay 'sudo bash /opt/tg_bot_btc/deploy/ufw-cloudflare-only.sh'
```

Закроет прямой доступ к 443 только с IP Cloudflare (опционально, жёсткий режим).

## Если Payfast перестал слать webhook

1. Cloudflare → **Security** → **Events** — смотрите блокировки на `/callback`
2. Убедитесь: для `/callback` действие **Block** или **Skip**, **не** Challenge
3. IP мерчанта в `.env`: `WEBHOOK_ALLOWED_IPS` (на сервере уже настроено)
