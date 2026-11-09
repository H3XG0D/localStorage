# Secret Rotation Automation

Автоматическая ротация критичных секретов FocusPay (WEBHOOK_SECRET, CALLBACK_SECRET, RECEIPT_SECRET).

## Компоненты

### Скрипты

1. **rotate_secrets.sh** — ротация секретов
   - Генерирует новые секреты (64-символьные hex)
   - Создаёт бэкап .env
   - Обновляет .env файл
   - Перезапускает сервисы
   - Записывает timestamp ротации

2. **check_secret_age.sh** — проверка возраста секретов
   - Проверяет когда последний раз ротировали
   - WARNING если >75 дней
   - CRITICAL если >90 дней
   - Отправляет алерт в Telegram (если `--alert`)

### Systemd Units

1. **focuspay-secret-rotation.service/timer** — автоматическая ротация каждое 1-е число месяца в 03:00 MSK
2. **focuspay-secret-age-check.service/timer** — проверка возраста каждый понедельник в 09:00 MSK

## Установка на сервере

```bash
# 1. Скопировать скрипты на сервер
scp bot/tg_bot_btc/scripts/*.sh root@217.60.34.76:/opt/exchange-backend/scripts/

# 2. Сделать исполняемыми
ssh root@217.60.34.76 "chmod +x /opt/exchange-backend/scripts/*.sh"

# 3. Установить systemd units
scp bot/tg_bot_btc/systemd/focuspay-secret-*.{service,timer} root@217.60.34.76:/etc/systemd/system/

# 4. Reload systemd и запустить timers
ssh root@217.60.34.76 "
  systemctl daemon-reload
  systemctl enable focuspay-secret-rotation.timer
  systemctl enable focuspay-secret-age-check.timer
  systemctl start focuspay-secret-rotation.timer
  systemctl start focuspay-secret-age-check.timer
"

# 5. Проверить статус
ssh root@217.60.34.76 "
  systemctl list-timers | grep focuspay-secret
  systemctl status focuspay-secret-rotation.timer
  systemctl status focuspay-secret-age-check.timer
"
```

## Ручное использование

### Dry-run ротации (проверить без изменений)
```bash
cd /opt/exchange-backend
./scripts/rotate_secrets.sh --dry-run
```

### Выполнить ротацию сейчас
```bash
cd /opt/exchange-backend
./scripts/rotate_secrets.sh
```

### Проверить возраст секретов
```bash
cd /opt/exchange-backend
./scripts/check_secret_age.sh
```

### Проверить с отправкой алерта в Telegram
```bash
cd /opt/exchange-backend
./scripts/check_secret_age.sh --alert
```

## Требования

- `openssl` для генерации случайных секретов
- `curl` для отправки Telegram алертов
- В `.env` должны быть:
  - `TELEGRAM_BOT_TOKEN` — токен бота
  - `SECURITY_ALERTS_CHAT_ID` — ID чата для security алертов
- systemd (для автоматизации)

## Мониторинг

### Проверить следующий запуск
```bash
systemctl list-timers | grep focuspay-secret
```

### Посмотреть логи последней ротации
```bash
journalctl -u focuspay-secret-rotation.service -n 50
```

### Посмотреть логи проверки возраста
```bash
journalctl -u focuspay-secret-age-check.service -n 50
```

## Rollback

Если после ротации что-то сломалось:

```bash
# 1. Остановить сервисы
systemctl stop focuspay-exchange-api

# 2. Восстановить из бэкапа
cd /opt/exchange-backend
cp .env.backup-YYYYMMDD-HHMMSS .env

# 3. Запустить сервисы
systemctl start focuspay-exchange-api

# 4. Проверить логи
journalctl -u focuspay-exchange-api -n 100
```

Бэкапы хранятся в `/opt/exchange-backend/.env.backup-*`

## Security Notes

⚠️ **ВАЖНО после ротации:**
- Обновите webhook secrets у внешних payment providers
- Проверьте что все webhook callbacks работают
- Убедитесь что старые бэкапы .env защищены (chmod 600)

## Интеграция с ops digest

Возраст секретов автоматически включается в daily business digest (задача 2.11).
