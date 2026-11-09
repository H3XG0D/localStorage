# AGENTS.md — FocusPay (для ИИ-агентов)

Читай это ПЕРВЫМ. Здесь — что за проект, как устроен, куда деплоить и **что нельзя делать**.
Проект и деплой боевые: на них работают реальные пользователи и персонал. Осторожность важнее скорости.

---

## 1. Что это за проект

**FocusPay** — сервис обмена криптовалюты (RUB ↔ USDT/BTC/LTC/TRX) с Telegram-ботом,
публичным сайтом и панелями админа/оператора. Идёт **миграция фронтенда** со старого
скомпилированного стека на новый React.

Три поверхности:
1. **Публичный сайт** (`/`) — лендинг, обмен, заявка+чат, авторизация, кабинет, рефералка, FocusLucky.
2. **Панель админа** (`/x8`) — ~18 разделов (заявки, юзеры, финансы, операторы, промо, партнёры и т.д.).
3. **Панель оператора** (`/ops`) — очередь заявок, смены, клиенты, промо, зарплата, чат.

Бэкенд — **FastAPI** (Python), его мы НЕ переписываем, только читаем как контракт.

---

## 2. Структура репозитория

| Путь | Что это | Трогаем? |
|---|---|---|
| `focussite/frontend/` | **АКТИВНАЯ кодовая база** (React 19 + Vite 6 + Tailwind v4). Сайт И панель. | ДА — тут вся работа |
| `site/exchange-backend/` | Боевой FastAPI-бэкенд (роутеры, миграции). Источник контракта API. | Только чтение (правки — по явному согласию) |
| `site/focuspay.org/` | Скомпилированный СТАРЫЙ сайт (`main-*.js`) — референс функционала. | Только чтение |
| `focus-panel/` | Vue-макет дизайна панели — только визуальный референс (мы делаем на React). | Только чтение |
| `focussite/frontend/src/` | Публичный сайт: `pages/`, `components/`, `lib/`. | ДА |
| `focussite/frontend/src/panel/` | Панель: `admin/`, `operator/`, `ui/`, `lib/`. | ДА |
| `bot/tg_bot_btc/` | **Продакшн Telegram-бот** (в этом репо). На сервере: `/opt/tg_bot_btc`, unit `tg-bot.service`. | ДА — правки как в backend |

**Важно про бота:** править только `bot/tg_bot_btc/` в этом репозитории. Каталог `~/Desktop/tg_bot_btc` — мёртвая копия от 2026-08-21, с продом не совпадает. Снимок живого `/opt/exchange-backend` лежит в ветке `snapshot/prod-20260905` (тег `snapshot-prod-20260905`), в `main` не мержить. `.env` в git не кладём. Бэкапы (`*.dump`, `*.dump.gz`) тоже в ignore.

**Стек:** React 19, TypeScript, Vite 6 (multi-entry), Tailwind v4 (CSS-переменные, без tailwind.config),
shadcn-подобные примитивы (публичный сайт) / собственные примитивы (панель), react-router 7,
framer-motion, sonner (тосты), lucide-react (иконки).

### Два входа Vite (multi-entry)
- `index.html` → `src/main.tsx` → публичный сайт. Светлая/тёмная тема (`lib/theme.tsx`).
- `panel.html` → `src/panel/main.tsx` → панель (админ+оператор). **Всегда тёмная** тема (`src/panel/panel.css`).
- Обе собираются одной командой `npm run build`; nginx раздаёт `/` из `index.html`, а `/x8` и `/ops` из `panel.html`.

---

## 3. Сервер и деплой

**Прод:** `153.80.249.77` (Debian 13), SSH `root@` **только по ключу** (парольный вход выключен). Staging: `178.63.247.233`, пользователь `focuspay-staging`. Карта хостов и `~/.ssh/config` — [`docs/SSH_ACCESS.md`](docs/SSH_ACCESS.md).
- Хелпер: `.ssh_run.py` в корне репо (`echo 'uptime' | python .ssh_run.py`). По умолчанию алиас `focuspay` и ключи/агент. `FOCUSPAY_SSH_PASSWORD` — устаревший fallback, на живых хостах пароль не принимается.
- **Первый SSH-коннект иногда падает** (`Authentication failed` / `Server connection dropped`) — это транзиентно (rate-limit/MaxStartups). Повторить через ~8–10с. На проде `MaxAuthTries 3` + fail2ban: в конфиге SSH ставь `IdentitiesOnly yes`.

**Бэкенд на сервере:** systemd-сервис `focuspay-exchange-api` (uvicorn, порт 8000), рабочая папка
`/opt/exchange-backend`, пользователь `focuspay`, venv `/opt/exchange-backend/venv`.
nginx проксирует `/api/` → :8000.
⚠️ В `/opt/exchange-backend` файл `operator.py` затеняет stdlib `operator` — наивный `python` из этой
папки падает circular import. Запускай probe-python из `/tmp` с venv, DSN бери из `.env` (строка `DATABASE_DSN`).

**nginx:** webroot `/var/www/focuspay.org/`. Конфиг `sites-available/focuspay.conf`.
`/` → `index.html`; `/x8`,`/ops` → `panel.html`; `/assets/` статика; `/api/` → :8000.

### Как деплоить
Всё из `focussite/frontend/`:
```bash
npm run build                                         # собрать оба входа
FOCUSPAY_SSH_PASSWORD=... python scripts/deploy_all.py --dry-run   # посмотреть план
FOCUSPAY_SSH_PASSWORD=... python scripts/deploy_all.py             # выкат
```
`deploy_all.py` (multi-entry): бэкапит `index.html` и `panel.html` (`.bak-<ts>`), заливает ассеты,
атомарно меняет оба HTML, удаляет старые бандлы, проверяет что `/`, `/x8`, `/ops` = 200.
Есть и `scripts/deploy.py` — только публичный сайт (index.html), для сайта без панели.

Vite dev-прокси уже настроен: `npm run dev` проксирует `/api` на боевой `153.80.249.77` — можно
разрабатывать против реальных данных.

---

## 4. Как мы работаем (правила)

1. **Не гадать про API — читать контракт.** Формы ответов смотри в `site/exchange-backend/routers/*.py`.
   Если сомневаешься — залогинься через API и сними реальный JSON (см. ниже). Типы на фронте держим
   «свободными» (`Record<string, unknown>` + известные поля), рендерим защитно (`String()`, `?? "—"`).
2. **Сверяй имена полей.** Самая частая причина «данные не подтягиваются» — фронт читает не то поле
   (напр. ждал `mine`, а бэкенд отдаёт `orders`; `fiat_sum` vs `fiat_volume`; `kind` vs `campaign_kind`).
3. **Всегда `npm run build` перед деплоем.** Сборка ловит TS-ошибки. Не деплоить со сломанной сборкой.
4. **Тема/дизайн.** Публичный сайт: монохром, Manrope/DM Mono, светлая+тёмная. Панель: тёмная
   near-black (`#0a0a0a`), Inter/JetBrains Mono, акценты статусов зелёный/жёлтый/красный. Только
   CSS-переменные тему (`var(--...)` / токены), НЕ хардкодить цвета.
5. **Реалтайм = SSE (не WebSocket).** Уже есть каналы: операторский чат `/api/operator/chat/events`
   и публичный `/api/public/chat/events` (канал `web_chat_buyer`). EventSource не шлёт заголовки —
   токен передаётся как `?access_token=`, а событие несёт только `order_id`-сигнал, контент тянется
   авторизованным запросом. Polling оставлять как fallback.
6. **Прогресс/тудушки** веди через TodoWrite для больших задач.
7. **Память проекта** — в `docs/` этого репозитория (`OPS_AI.md`, `PERMISSION_MATRIX.md`, `FROZEN.md`,
   `INTEGRATION.md`, `DEPLOYMENT_CHANGELOG.md`) + этот `AGENTS.md` как канон правил.
   Контракт панели — §5 ниже; источник истины по формам ответов — роутеры в `site/exchange-backend/routers/`.
   Обновляй при значимых изменениях.

### Как снять реальный ответ API (для сверки полей)
Залогинься и дёрни эндпоинт с сервера (пример — админ):
```python
# запускать из /tmp через venv-python на сервере
tok = POST /api/auth/admin/login {username, password} -> access_token
GET /api/admin/<...> с заголовком Authorization: Bearer <tok>
```
Оператор требует 2FA (TOTP): `login` → `{pre_auth_token}` → `login/2fa {pre_auth_token, code}`.
**НЕ форджить токены** в обход 2FA (импортом `create_access_token` и т.п.) — это обход защиты, запрещено.

---

## 5. Ключевой контракт API (кратко)

Префиксы: `/api/public` (сайт), `/api/auth` (вход), `/api/user` (кабинет),
`/api/admin` (админка), `/api/operator` (оператор).

**Авторизация:** JWT scope `user|admin|operator|partner|exchanger` (+ `*_preauth` для 2FA).
Логин → `{access_token, token_type:"bearer", <entity>}` ИЛИ `{requires_2fa, pre_auth_token}`.
Токен: `Authorization: Bearer`. Панель хранит токены отдельно от сайта
(`focuspay_admin_token`, `focuspay_operator_token`).

**Статусы заявок:** CREATED, AWAITING_CHECK, PENDING, COMPLETED, PAID, FAILED, CANCELED,
EXPIRED, DISPUTE, OPERATOR_PENDING. Направления: buy/sell (+ order_type sell_qr).
Крипта: usdt/btc/trx/ltc. sub_token: SBPRUB(СБП)/CARDRUB(карта).

**Гостевой заказ ОТКЛЮЧЁН** — создание заявки на сайте требует входа.

**Оператор — важные особенности (проверено на живых данных):**
- `/operator/orders` отдаёт `{incoming, orders (мои), team_orders, withdrawals_incoming, ...}`.
- Смена (`/shift/start`) требует балансы по ВСЕМ монетам (usdt/btc/trx/ltc), пустой массив = ошибка.
- Поиск клиента (`/users/search?q=`) принимает Telegram ID или @username (НЕ произвольное имя).
- Профиль клиента (`/users/{id}`) → `{identity, summary, balances, last_deal, recent_orders[]}`.
- Оператору финансы/прибыль не показываем — только балансы кошельков смены.

Полный список эндпоинтов — в роутерах `site/exchange-backend/routers/*.py` (источник истины).
Матрица прав по ролям/экранам — `docs/PERMISSION_MATRIX.md`.

---

## 6. ЧТО НЕЛЬЗЯ ДЕЛАТЬ (важно)

- ❌ **НЕ переписывать бэкенд** (`site/exchange-backend/`) без явного согласия пользователя.
  Правки бэкенда/nginx/рестарт сервиса = боевые изменения, требуют подтверждения и бэкапов.
- ❌ **НЕ ломать чужой вход при деплое.** Деплой заменяет `index.html`+`panel.html` и свои ассеты;
  используй `deploy_all.py` (он бэкапит и не трогает лишнее). Не удалять чужие ассеты вручную.
- ❌ **НЕ хардкодить секреты** (SSH-пароль, токены) в файлы или коммиты. Только через env.
- ❌ **НЕ форджить/подделывать JWT** в обход авторизации и 2FA.
- ❌ **НЕ выкатывать пустой каркас/заглушки** поверх работающей боевой панели — персонал останется
  без инструмента. Деплоить панель только с реальным функционалом.
- ❌ **НЕ коммитить/пушить и не делать необратимых действий** (удаление, перезапись) без спроса.
  На боевом всегда сначала бэкап.
- ❌ **НЕ трогать** `site/focuspay.org/` и `focus-panel/` как код — это референсы (чтение).
- ❌ **НЕ менять** дизайн-язык вразнобой: сайт — монохром светлая/тёмная; панель — тёмная. Держи систему.

## 7. Быстрый старт для нового агента

```bash
cd focussite/frontend
npm install            # если нет node_modules
npm run dev            # dev против боевого API (прокси /api → 153.80.249.77)
npm run build          # сборка обоих входов
python scripts/deploy_all.py --dry-run   # план деплоя (нужен FOCUSPAY_SSH_PASSWORD)
```
Перед задачей: прочитай этот `AGENTS.md`, нужные документы в `docs/` (`FROZEN.md`, `PERMISSION_MATRIX.md`,
`OPS_AI.md`) и нужные роутеры в `site/exchange-backend/routers/`.
Сомневаешься в форме ответа — сними живой JSON, не гадай.

Навыки проекта: `.agents/skills/` (`grill-me` — прожарка неоднозначной просьбы,
`ops-ai-closeout` — закрытие задач Ops AI). Общие навыки — в `~/.agents/skills/`.
