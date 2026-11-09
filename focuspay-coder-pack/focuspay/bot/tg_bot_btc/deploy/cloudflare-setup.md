# Cloudflare — настройка перед prod

## 1. DNS

1. Добавьте домен в Cloudflare.
2. A-запись `focuspay.org` → IP сервера с **прокси включён** (оранжевое облако).
3. То же для `www`.

Реальный IP сервера не должен светиться в публичном DNS.

## 2. SSL/TLS

- Режим: **Full (strict)**.
- На сервере: Let's Encrypt (как в `nginx-focuspay.org.conf`).

## 3. nginx real_ip

```bash
sudo cp deploy/nginx-cloudflare-real-ip.conf /etc/nginx/cloudflare-real-ip.conf
sudo cp deploy/nginx-focuspay.org.conf /etc/nginx/sites-available/focuspay.org
sudo nginx -t && sudo systemctl reload nginx
```

Конфиг доверяет только Cloudflare IP ranges и берёт клиентский IP из `CF-Connecting-IP`.

## 4. WAF

Security → WAF → Managed rules: включить OWASP и Cloudflare Managed Ruleset.

## 5. Rate limiting

Security → WAF → Rate limiting rules:

| Rule | Match | Action |
|------|-------|--------|
| API flood | URI Path starts with `/api/` | Block, 100 requests / 10 seconds / IP |
| Auth brute | URI Path contains `/api/auth/` | Block, 20 requests / 1 minute / IP |
| Webhook | URI Path equals `/callback` | **Block** (не Challenge!), 30 requests / 1 minute / IP |

**Важно:** для `/callback` не используйте Challenge/CAPTCHA — Payfast не пройдёт проверку.

Создайте WAF Custom Rule: Skip для `/callback` (Managed rules off, только rate limit).

## 6. Дополнительно

- Bot Fight Mode: ON (для публичного сайта).
- Security Level: Medium или High.
- «Always use HTTPS»: ON.
- Минимизировать версию TLS: 1.2.

## 7. WEBHOOK_ALLOWED_IPS

В `.env` укажите **только IP Payfast** (не Cloudflare). nginx передаёт реальный IP мерчанта через `CF-Connecting-IP`.

Узнать IP мерчанта после первых callback:
```bash
grep "POST /callback" /var/log/nginx/access.log | awk '{print $1}' | sort -u
```

## 8. Проверка

```bash
# Ответ через Cloudflare (заголовок cf-ray)
curl -sI https://focuspay.org/api/health

# Прямой запрос на origin IP с другой машины — должен быть отказ или пустой ответ
curl -sI --resolve focuspay.org:443:ORIGIN_IP https://focuspay.org/api/health
```

## 9. Секреты и права

```bash
chmod 600 /opt/tg_bot_btc/.env /opt/exchange-backend/.env
```

`MERCHANT_CALLBACK_URL` без `?token=` — только HMAC в заголовках `X-Signature` + `X-Timestamp`.
