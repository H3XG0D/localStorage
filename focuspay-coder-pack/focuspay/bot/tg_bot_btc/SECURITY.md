# Безопасность FocusPay

## Ротация секретов

При утечке `.env`, workspace или подозрении на компрометацию — **сразу** ротируйте:

| Секрет | Как ротировать |
|--------|----------------|
| `TELEGRAM_BOT_TOKEN` | @BotFather → Revoke / новый token |
| `DATABASE_DSN` password | `ALTER USER exchange_bot PASSWORD '...'` + обновить `.env` |
| `WEBHOOK_SECRET`, `CALLBACK_SECRET`, `RECEIPT_SECRET` | Сгенерировать новые (`openssl rand -hex 32`) |
| `MERCHANT_API_KEY`, `MERCHANT_SECRET_KEY` | В кабинете Payfast |
| `SECRET_KEY` (JWT) | Новый ключ → все admin/operator сессии сбросятся |
| `SELL_WALLETS_JSON` | Только при смене кошельков |

После ротации: `systemctl restart tg-bot tg-bot-webhook focuspay-exchange-api`.

## Prod checklist

- [ ] Cloudflare proxy ON — [`deploy/cloudflare-setup.md`](deploy/cloudflare-setup.md)
- [ ] **`WEBHOOK_ALLOWED_IPS` задан (ОБЯЗАТЕЛЬНО)** — IP адреса Payfast/провайдеров. Пустое значение = reject all webhooks (кроме localhost)
- [ ] `SELL_WALLETS_JSON` задан
- [ ] UFW: только 22/80/443 — [`deploy/ufw-focuspay.sh`](deploy/ufw-focuspay.sh)
- [ ] Сервисы под пользователем `focuspay` — [`deploy/setup-focuspay-user.sh`](deploy/setup-focuspay-user.sh)
- [ ] `.env` права `600`
- [ ] Callback URL без token: `https://домен/callback` (HMAC в заголовках)
- [ ] nginx `cloudflare-real-ip.conf` подключён ([`deploy/nginx-cloudflare-real-ip.conf`](deploy/nginx-cloudflare-real-ip.conf))

## Мониторинг

- Telegram security alerts (`SECURITY_TELEGRAM_CHAT_ID`)
- Admin panel → Security events (`/api/admin/security/events`)
- `journalctl -u tg-bot-webhook -u focuspay-exchange-api`
