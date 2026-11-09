---
type: note
tags: [sandbox, ecosystem, safety]
status: active
updated: 2026-08-11
---

# E1 Sandbox — изолированная тестовая среда

Отделяет эксперименты VPN↔FocusPay wallet от **боевого** FocusPay (`exchange_bot` / systemd `tg-bot*`).

## Что это

| | Production FocusPay | Sandbox |
|---|---|---|
| Postgres | `exchange_bot@:5432` | `focuspay_sandbox@:15433` + `myvpn_sandbox@:15432` |
| Compose | — | `infra/sandbox/docker-compose.yml` (`focusvpn-e1-sandbox`) |
| Wallet API | prod webhook :8081 | `scripts/sandbox_focuspay_wallet.py` :18081 |
| FocusVPN CP | — | :18080 → sandbox PG |
| Telegram | боевой бот | только test-token (опционально) |

Скрипты **отказываются** работать с DSN вида `exchange_bot@:5432` без `focuspay_sandbox` / `:15433`.

## Команды

```bash
make sandbox-up      # поднять 2× Postgres, migrate FocusVPN, seed 300₽
make sandbox-run     # CP + sandbox wallet (фоном, логи в infra/sandbox/run/)
make sandbox-smoke   # hold → extend → confirm на sandbox
make sandbox-stop    # остановить CP/wallet
make sandbox-down    # остановить Postgres (тома сохраняются)
make sandbox-reset   # down -v (полный wipe sandbox)
```

Env: скопируется `infra/sandbox/.env.sandbox` из example при первом `sandbox-up`.

## Правила безопасности

1. Не ставить `DATABASE_DSN` прода в `.env.sandbox`.
2. Не запускать sandbox-скрипты с `FOCUSVPN_SANDBOX` unset.
3. Не применять `add_vpn_crypto_invoices.sql` к prod, пока явно не решите (сначала sandbox).
4. VPN Telegram bot — отдельный test bot token, не токен обменника.
5. Payfast / финансовые FROZEN-пути prod не трогаем из sandbox app.

## Связано

- [[plans/E1-vpn-bot]] · [[007-ecosystem-billing-federation]] · [[CURRENT_TASK]]
