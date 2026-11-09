# Database Backup Automation

Автоматическое резервное копирование PostgreSQL базы данных FocusPay с поддержкой offsite хранения.

## Компоненты

### Скрипты

1. **backup_db.sh** — создание локального pg_dump
   - Читает DATABASE_DSN из .env
   - Создаёт custom format dump с timestamp
   - Сжимает через gzip -9 для offsite transfer
   - Retention policy: удаляет бэкапы старше N дней (default 7)
   - Выводит статистику (размер, время, количество)

2. **backup_offsite_sync.sh** — синхронизация на внешний сервер
   - Использует rsync для надёжной передачи
   - Поддержка SSH key authentication
   - Включается через OFFSITE_BACKUP_ENABLED=true в .env
   - Graceful fallback если offsite недоступен

3. **backup_full.sh** — wrapper для полного цикла
   - Вызывает backup_db.sh → backup_offsite_sync.sh
   - Используется systemd timer

### Systemd Units

- **focuspay-db-backup.service** — oneshot сервис для бэкапа
- **focuspay-db-backup.timer** — запуск каждый день в 02:00 MSK

## Установка

### 1. Локальный бэкап (без offsite)

```bash
# Скопировать скрипты на сервер
scp bot/tg_bot_btc/scripts/backup*.sh root@217.60.34.76:/opt/exchange-backend/scripts/

# Сделать исполняемыми
ssh root@217.60.34.76 "chmod +x /opt/exchange-backend/scripts/backup*.sh"

# Создать директорию для бэкапов
ssh root@217.60.34.76 "mkdir -p /var/backups/focuspay && chmod 700 /var/backups/focuspay"

# Установить systemd units
scp bot/tg_bot_btc/systemd/focuspay-db-backup.{service,timer} root@217.60.34.76:/etc/systemd/system/

# Активировать timer
ssh root@217.60.34.76 "
  systemctl daemon-reload
  systemctl enable focuspay-db-backup.timer
  systemctl start focuspay-db-backup.timer
"
```

### 2. Настройка offsite (опционально)

Добавить в `.env` на сервере:

```bash
# Offsite backup configuration
OFFSITE_BACKUP_ENABLED=true
OFFSITE_BACKUP_HOST=backup.example.com
OFFSITE_BACKUP_USER=focuspay
OFFSITE_BACKUP_PATH=/backups/focuspay
OFFSITE_BACKUP_SSH_KEY=/root/.ssh/backup_key  # optional, если не default
```

Создать SSH ключ для автоматической авторизации:

```bash
# На продакшн сервере
ssh-keygen -t ed25519 -f /root/.ssh/backup_key -N ""

# Скопировать публичный ключ на backup сервер
ssh-copy-id -i /root/.ssh/backup_key.pub focuspay@backup.example.com

# Протестировать подключение
ssh -i /root/.ssh/backup_key focuspay@backup.example.com "mkdir -p /backups/focuspay"
```

## Ручное использование

### Создать бэкап сейчас
```bash
cd /opt/exchange-backend
./scripts/backup_db.sh
```

### Полный цикл (backup + offsite)
```bash
cd /opt/exchange-backend
./scripts/backup_full.sh
```

### Изменить retention policy
```bash
# Хранить 14 дней вместо 7
./scripts/backup_db.sh --keep-days 14
```

## Restore процедура

### Восстановить из локального бэкапа

```bash
# 1. Остановить приложение
systemctl stop focuspay-exchange-api focuspay-bot

# 2. Найти нужный бэкап
ls -lh /var/backups/focuspay/

# 3. Распаковать
gunzip /var/backups/focuspay/exchange_bot_backup_YYYYMMDD_HHMMSS.dump.gz

# 4. Восстановить (ВНИМАНИЕ: это удалит текущие данные!)
# Опция 1: полная перезапись БД
pg_restore \
  -h localhost \
  -U postgres \
  -d exchange_bot \
  --clean \
  --if-exists \
  /var/backups/focuspay/exchange_bot_backup_YYYYMMDD_HHMMSS.dump

# Опция 2: в новую БД (безопаснее для тестирования)
createdb exchange_bot_restore
pg_restore \
  -h localhost \
  -U postgres \
  -d exchange_bot_restore \
  /var/backups/focuspay/exchange_bot_backup_YYYYMMDD_HHMMSS.dump

# 5. Проверить данные
psql -U postgres -d exchange_bot_restore -c "SELECT COUNT(*) FROM orders;"

# 6. Если всё ОК, переключить приложение на новую БД или переименовать
psql -U postgres -c "
  ALTER DATABASE exchange_bot RENAME TO exchange_bot_old;
  ALTER DATABASE exchange_bot_restore RENAME TO exchange_bot;
"

# 7. Запустить приложение
systemctl start focuspay-exchange-api focuspay-bot
```

### Восстановить с offsite сервера

```bash
# 1. Скачать последний бэкап
rsync -avz \
  -e "ssh -i /root/.ssh/backup_key" \
  focuspay@backup.example.com:/backups/focuspay/exchange_bot_backup_YYYYMMDD_HHMMSS.dump.gz \
  /var/backups/focuspay/

# 2. Далее как при локальном restore (см. выше)
```

## Мониторинг

### Проверить статус timer
```bash
systemctl status focuspay-db-backup.timer
systemctl list-timers | grep focuspay-db-backup
```

### Посмотреть логи последнего бэкапа
```bash
journalctl -u focuspay-db-backup.service -n 100
```

### Посмотреть все локальные бэкапы
```bash
ls -lh /var/backups/focuspay/
du -sh /var/backups/focuspay/
```

### Проверить offsite sync
```bash
# На backup сервере
ssh focuspay@backup.example.com "ls -lh /backups/focuspay/"
```

## Тестирование restore (еженедельно)

**ВАЖНО**: регулярно проверяйте что бэкапы валидны!

```bash
# Каждую неделю (ручная задача):
# 1. Скачать последний бэкап
# 2. Развернуть на staging/dev окружении
# 3. Проверить что данные корректны
# 4. Записать результат в ops digest
```

Команда для быстрого теста (без полного restore):

```bash
# Проверить что dump файл валиден
pg_restore --list /var/backups/focuspay/exchange_bot_backup_YYYYMMDD_HHMMSS.dump | head -20
```

## Алерты и мониторинг

Добавить в daily business digest (задача 2.11):
- Последний успешный бэкап (timestamp)
- Размер последнего бэкапа
- Статус offsite sync
- Алерт если бэкап не выполнялся >36 часов

## Troubleshooting

### Бэкап падает с "permission denied"
```bash
# Проверить права на директорию
ls -ld /var/backups/focuspay/
chmod 700 /var/backups/focuspay/
chown root:root /var/backups/focuspay/
```

### rsync не подключается к offsite
```bash
# Проверить SSH ключ
ssh -i /root/.ssh/backup_key focuspay@backup.example.com "echo OK"

# Проверить права на ключ
chmod 600 /root/.ssh/backup_key
```

### Недостаточно места для бэкапа
```bash
# Проверить свободное место
df -h /var/backups/

# Уменьшить retention или увеличить диск
./scripts/backup_db.sh --keep-days 3
```

### Бэкап слишком долго выполняется
```bash
# Проверить размер БД
psql -U postgres -d exchange_bot -c "
  SELECT pg_size_pretty(pg_database_size('exchange_bot'));
"

# Если >10GB, рассмотреть:
# - Увеличить TimeoutStartSec в systemd unit
# - Использовать параллельный dump (pg_dump -j N)
# - Настроить инкрементальный бэкап (WAL archiving)
```

## Security Notes

⚠️ **Важно**:
- `/var/backups/focuspay/` должен иметь права 700 (только root)
- Бэкапы содержат sensitive данные (пользователи, заказы, финансы)
- SSH ключ для offsite должен быть без passphrase (для автоматизации)
- На offsite сервере используйте отдельного пользователя с ограниченными правами
- Регулярно тестируйте restore процедуру

## Disaster Recovery Plan

При полной потере продакшн сервера:

1. Поднять новый сервер с PostgreSQL
2. Скачать последний бэкап с offsite
3. Восстановить БД через pg_restore
4. Развернуть приложение из git
5. Восстановить .env (должен храниться отдельно в encrypted хранилище)
6. Запустить сервисы

**Целевое RTO (Recovery Time Objective)**: 2-4 часа  
**Целевое RPO (Recovery Point Objective)**: 24 часа (daily backups)

Для уменьшения RPO можно настроить WAL archiving + PITR (Point-In-Time Recovery).
