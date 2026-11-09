# Развёртывание бота на VPS

Краткая пошаговая инструкция: перенос файлов, установка зависимостей, настройка БД и запуск.

---

## 0. Практика на локальном Linux (перед VPS)

Чтобы потренироваться перед выкладкой на VPS:

**Вариант A — WSL2 (быстро, прямо в Windows)**  
1. В PowerShell от администратора: `wsl --install`.  
2. Перезагрузка, затем в Microsoft Store установи **Ubuntu 22.04**.  
3. Запусти Ubuntu → появится терминал с Linux.  
4. Дальше те же шаги, что и на VPS: установка Python, PostgreSQL, клонирование/копирование проекта, venv, `config_rates.py`, запуск бота и вебхука (разделы 2–8 ниже).  
5. Файлы проекта можно положить из Windows в `\\wsl$\Ubuntu-22.04\home\ТВОЙ_ЛОГИН\` или склонировать git внутри WSL.

**Вариант B — виртуальная машина (как настоящий сервер)**  
1. Установи **VirtualBox** и скачай образ **Ubuntu Server 22.04** с [ubuntu.com/download/server](https://ubuntu.com/download/server).  
2. Создай новую VM (тип Linux, Ubuntu 64-bit), выдели 1–2 GB RAM, 20 GB диск, примонтируй ISO и установи систему.  
3. После установки зайди в систему (локально или по SSH с хоста).  
4. Выполняй шаги из разделов 2–8 как на VPS (apt, PostgreSQL, проект, venv, systemd при желании).

**Какой дистрибутив выбрать под VPS**  
Из твоего списка хостера оптимально взять **Ubuntu 22.04** или **Debian 12** — они есть в списке, долго поддерживаются, и инструкция ниже под них написана. На практике в VM/WSL тоже используй Ubuntu 22.04.

После того как бот стабильно работает в VM/WSL, на VPS делаешь то же самое (разделы 1–10).

---

## 1. Подключение к VPS

- По **SSH** (замени на свой IP и пользователя):
  ```bash
  ssh root@ТВОЙ_IP
  ```
  или с ключом:
  ```bash
  ssh -i путь/к/ключу.pem root@ТВОЙ_IP
  ```

Рекомендуемая ОС: **Ubuntu 22.04** (или 20.04).

---

## 2. Установка на сервере

### 2.1 Python 3.10+

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 --version   # должно быть 3.10+
```

### 2.2 PostgreSQL

```bash
sudo apt install -y postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### 2.3 Создание БД и пользователя

```bash
sudo -u postgres psql
```

В консоли PostgreSQL:

```sql
CREATE USER exchange_bot WITH PASSWORD 'ТВОЙ_НАДЁЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE exchange_bot OWNER exchange_bot;
\q
```

Пароль запомни — он понадобится в DSN.

---

## 3. Перенос файлов на VPS

**Вариант A — через SCP (с твоего ПК в папку проекта):**

```bash
scp -r C:\Users\qwe\Desktop\tg_bot_btc root@ТВОЙ_IP:/opt/
```

Или только нужное (без `__pycache__`, `receipts`, лишнего):

- Папки: `handlers`, `services`, `migrations`, `scripts`
- Файлы: `main.py`, `requirements.txt`

```bash
scp -r handlers services migrations scripts main.py requirements.txt root@ТВОЙ_IP:/opt/tg_bot_btc/
```

**Вариант B — через Git:**

На ПК:

```bash
cd C:\Users\qwe\Desktop\tg_bot_btc
git init
git add .
git commit -m "deploy"
# создай репо на GitHub/GitLab и добавь remote
git remote add origin https://github.com/ТВОЙ_ЛОГИН/tg_bot_btc.git
git push -u origin main
```

На VPS:

```bash
sudo apt install -y git
cd /opt
sudo git clone https://github.com/ТВОЙ_ЛОГИН/tg_bot_btc.git
sudo chown -R $USER:$USER tg_bot_btc
cd tg_bot_btc
```

**Вариант C — архив:**

На ПК: заархивировать проект (без `__pycache__`, без `receipts` если не нужны), залить на сервер через FileZilla/WinSCP или `scp archive.zip root@IP:/opt/` и на VPS: `unzip archive.zip -d /opt/tg_bot_btc`.

---

## 4. Перенос базы данных (если уже есть данные на ПК)

Если PostgreSQL стоит у тебя локально и нужно перевезти данные:

**На своём ПК (Windows):**

```bash
# Установи PostgreSQL client если ещё нет, затем:
pg_dump -U exchange_bot -h 127.0.0.1 -d exchange_bot -F c -f exchange_bot_backup.dump
```

Или в виде SQL:

```bash
pg_dump -U exchange_bot -h 127.0.0.1 -d exchange_bot > exchange_bot_backup.sql
```

Перенеси файл на VPS (например `scp exchange_bot_backup.sql root@IP:/opt/tg_bot_btc/`).

**На VPS — восстановление:**

Если делал `.dump`:

```bash
sudo -u postgres pg_restore -d exchange_bot -U exchange_bot /opt/tg_bot_btc/exchange_bot_backup.dump
```

Если делал `.sql`:

```bash
sudo -u postgres psql -d exchange_bot -f /opt/tg_bot_btc/exchange_bot_backup.sql
```

Если БД на VPS **новая** и таблиц ещё нет — сначала примени миграции (см. ниже).

---

## 5. Миграции (новая БД или новые таблицы)

Если база пустая или нужно добавить колонки/таблицы — выполни SQL из папки `migrations` в нужном порядке. Обычно:

1. Создание таблиц (если есть отдельный `create_tables.sql` или аналог).
2. `add_merchant_order_id.sql`
3. `add_sub_token.sql`
4. `add_bot_users.sql`
5. `add_web_chat_telegram_bridge.sql` (чат @focus_operator ↔ `/ops/chat`)

Пример:

```bash
cd /opt/tg_bot_btc
sudo -u postgres psql -d exchange_bot -f migrations/add_merchant_order_id.sql
sudo -u postgres psql -d exchange_bot -f migrations/add_sub_token.sql
sudo -u postgres psql -d exchange_bot -f migrations/add_bot_users.sql
```

Права:

```sql
sudo -u postgres psql -d exchange_bot -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO exchange_bot;"
sudo -u postgres psql -d exchange_bot -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO exchange_bot;"
```

---

## 6. Виртуальное окружение и библиотеки

На VPS:

```bash
cd /opt/tg_bot_btc
python3 -m venv venv
source venv/bin/activate   # Linux/Mac
pip install --upgrade pip
pip install -r requirements.txt
```

Проверка:

```bash
python -c "import telegram; import asyncpg; import fastapi; print('OK')"
```

---

## 7. Настройка конфига на VPS

Отредактируй `services/config_rates.py` на сервере:

1. **DATABASE_DSN** — хост БД на VPS (обычно `127.0.0.1` или `localhost`):
   ```python
   DATABASE_DSN = "postgresql://exchange_bot:ТВОЙ_ПАРОЛЬ@127.0.0.1:5432/exchange_bot"
   ```

2. **MERCHANT_CALLBACK_URL** в `.env` — публичный URL callback через nginx:
   `https://твой-домен.ru/callback` (без token в query; авторизация — HMAC в заголовках).

3. Токен бота, админские ID, группа и т.д. оставь как нужно (можно не менять, если уже верные).

В `main.py` в `on_startup` тоже проверь DSN — лучше брать из конфига, чтобы не дублировать:

```python
from services.config_rates import DATABASE_DSN
# ...
async def on_startup(app):
    await init_db(DATABASE_DSN)
```

(Если у тебя уже импорт и использование `DATABASE_DSN` из конфига — ничего не меняй.)

---

## 8. Запуск

Нужно держать включёнными **два процесса**:

1. **Бот (polling)** — приём сообщений из Telegram.
2. **Вебхук-сервер** — приём callback от мерчанта (FastAPI).

### Запуск вручную (для проверки)

Терминал 1 — бот:

```bash
cd /opt/tg_bot_btc
source venv/bin/activate
python main.py
```

Терминал 2 — вебхук (порт 8080, можно другой):

```bash
cd /opt/tg_bot_btc
source venv/bin/activate
uvicorn services.webhook_server:app --host 0.0.0.0 --port 8080
```

Открой в браузере: `http://ТВОЙ_IP:8080/docs` — должна открыться документация FastAPI.

### Запуск через systemd (всегда работают после перезагрузки)

Создай два юнита.

**Бот:**

```bash
sudo nano /etc/systemd/system/tg-bot.service
```

Содержимое:

```ini
[Unit]
Description=Telegram Exchange Bot
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tg_bot_btc
Environment=PATH=/opt/tg_bot_btc/venv/bin
ExecStart=/opt/tg_bot_btc/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Вебхук:**

```bash
sudo nano /etc/systemd/system/tg-bot-webhook.service
```

```ini
[Unit]
Description=Telegram Bot Webhook (Merchant callback)
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tg_bot_btc
Environment=PATH=/opt/tg_bot_btc/venv/bin
ExecStart=/opt/tg_bot_btc/venv/bin/uvicorn services.webhook_server:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Включение и старт:

```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-bot tg-bot-webhook
sudo systemctl start tg-bot tg-bot-webhook
sudo systemctl status tg-bot tg-bot-webhook
```

Логи:

```bash
sudo journalctl -u tg-bot -f
sudo journalctl -u tg-bot-webhook -f
```

---

## 9. Файрвол и callback URL

**Не открывай** порты 8080/8081/8000 наружу. Webhook и API слушают только `127.0.0.1`, снаружи — nginx на 443.

```bash
sudo bash deploy/ufw-focuspay.sh
```

В настройках мерчанта укажи **callback_url**:

```
https://focuspay.org/callback
```

Авторизация webhook — HMAC-подпись тела (`X-Signature` + `X-Timestamp`), не token в URL.

Перед prod: Cloudflare proxy — см. [`deploy/cloudflare-setup.md`](deploy/cloudflare-setup.md).

Системный пользователь для сервисов (не root):

```bash
sudo bash deploy/setup-focuspay-user.sh
```

---

## 10. Чек-лист

| Шаг | Действие |
|-----|----------|
| 1 | Подключиться по SSH к VPS |
| 2 | Установить Python 3.10+, PostgreSQL |
| 3 | Создать БД и пользователя `exchange_bot` |
| 4 | Перенести файлы (scp / git / архив) в `/opt/tg_bot_btc` |
| 5 | При необходимости перенести дамп БД и восстановить или применить миграции |
| 6 | `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt` |
| 7 | В `config_rates.py` выставить DSN и callback_url для VPS |
| 8 | Запустить бота и вебхук (вручную или через systemd) |
| 9 | UFW: только 22/80/443; callback `https://домен/callback`; Cloudflare proxy |

После этого бот должен работать на VPS, а мерчант — слать уведомления на твой сервер.

---

## 11. Чат @focus_operator на сайте (Telegram Business API)

Единый inbox для операторов: сообщения с сайта и из лички @focus_operator попадают в `/ops/chat`.

### Миграция

```bash
cd /opt/tg_bot_btc
sudo -u postgres psql -d exchange_bot -f migrations/add_web_chat_telegram_bridge.sql
```

### Переменные окружения

**exchange-backend** (`/opt/exchange-backend/.env`):

- `INTERNAL_API_SECRET` — общий секрет (или используется `WEBHOOK_SECRET`)
- `TELEGRAM_BOT_TOKEN` — тот же бот, что и у tg_bot_btc

**tg_bot_btc** (`/opt/tg_bot_btc/.env`):

- `INTERNAL_API_SECRET` — тот же секрет, что у exchange-backend
- `EXCHANGE_API_URL=http://127.0.0.1:8000`
- `CHAT_UPLOAD_DIR=/opt/tg_bot_btc/chat_uploads`

### Подключение Business-аккаунта

**Сначала** включите Business Mode у бота (без этого Telegram покажет *«This bot doesn't support Telegram Business yet»*):

1. Откройте **@BotFather** в Telegram.
2. Отправьте `/mybots` → выберите **@focuspay1_bot** (ваш бот).
3. **Bot Settings** → **Business Mode** → **Turn on**.

Проверка (на сервере, подставьте токен):
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getMe" | grep can_connect_to_business
```
Должно быть `"can_connect_to_business":true`.

Затем подключите бота к аккаунту @focus_operator:

1. В Telegram откройте аккаунт **@focus_operator** → **Настройки** → **Telegram для бизнеса** → **Чат-боты** (Chat Automation).
2. Введите `@focuspay1_bot` — предупреждение должно исчезнуть.
3. Выберите **All Private Chats** (или «All Private Chats Except…») и включите **Reply to Messages**.
4. Нажмите **Done** / сохраните.

Раздел **Telegram для бизнеса** на аккаунте @focus_operator обычно требует **Telegram Premium**.

Перезапустите сервисы:

```bash
sudo systemctl restart tg-bot focuspay-exchange-api
```

### Проверка

1. Напишите в личку @focus_operator с тестового аккаунта.
2. В кабинете оператора откройте **Чат** — должно появиться сообщение с меткой «Telegram».
3. Ответьте из `/ops/chat` — клиент должен получить ответ в Telegram.
4. Напишите через виджет на сайте — тот же диалог (метка «Сайт + TG», если клиент тот же Telegram user).

### Уведомления операторам

- Бейдж непрочитанных в меню **Чат**
- Звук и браузерные уведомления (кнопка «🔔 Звук» в чате, разрешите уведомления в браузере)
