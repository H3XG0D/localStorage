# Onboarding разработчика FocusPay

Этот документ — стартовая карта монорепозитория FocusPay. Он помогает найти правильную точку в коде, понять связь между компонентами и не затронуть production-критичные механизмы.

**Канон рабочих правил:** [`AGENTS.md`](../AGENTS.md). Если этот документ расходится с контрактом API, текущей конфигурацией или правилом безопасности, приоритет у исходного кода и `AGENTS.md`.

## 1. Что строит проект

FocusPay — криптообменник RUB ↔ USDT/BTC/LTC/TRX. Пользователь создаёт и сопровождает заявку через публичный сайт или Telegram-бот. Сотрудники обрабатывают заявки через операторскую и административную панели. Партнёры и внешние обменники используют отдельные кабинеты и API.

### Продуктовые поверхности

| Поверхность | Пользователь | URL / канал | Код |
|---|---|---|---|
| Публичный сайт | Клиент | `/`, `/exchange`, кабинет | `focussite/frontend/src/` |
| Административная панель | Администратор | `/x8` | `focussite/frontend/src/panel/admin/` |
| Операторская панель | Оператор | `/ops` | `focussite/frontend/src/panel/operator/` |
| HTTP API | Все web-клиенты и интеграции | `/api/...` | `site/exchange-backend/` |
| Telegram-бот | Клиент, оператор, администратор | Telegram | `bot/tg_bot_btc/` |
| Payfast webhook | Платёжный провайдер | Внутренний callback через nginx | `bot/tg_bot_btc/services/webhook_server.py` |

### Как компоненты связаны

```text
Браузер ──────► React public site ─┐
                                   │
Админ / оператор ─► React panel ──┼──► FastAPI /api ─► PostgreSQL
                                   │          │
Партнёр / обменник ───────────────┘          ├──► internal / bot integrations
                                              └──► SSE события для web-клиентов

Telegram ─► tg_bot_btc ─► PostgreSQL и внутренний API-мост ─► FastAPI
Payfast  ─► отдельный webhook-сервис бота ─► проверка и переходы заявки
```

У сайта, API и бота есть общие бизнес-сущности, но не всегда один слой владения. Всегда устанавливайте источник истины для конкретного изменения:

- web-контракт и права доступа — FastAPI-роутер;
- UI-поведение — соответствующая React-страница и её API-модуль;
- Telegram FSM и обработка пользовательских сообщений — бот;
- допустимый жизненный цикл заявки — `bot/tg_bot_btc/services/order_transitions.py` и серверные проверки;
- схема БД — SQL-миграции и текущие запросы, а не предположения по полям.

## 2. Карта репозитория

| Путь | Назначение | Можно менять? | С чего начать чтение |
|---|---|---|---|
| `AGENTS.md` | Каноничные правила проекта, стек, production-ограничения | Только при явной задаче | Прочитать полностью до начала работы |
| `README.md` | Короткая входная карта | Да, если карта меняется | Этот файл |
| `docs/` | Проектные договорённости, RBAC, ограничения, интеграции, аудиты | Да, вместе с существенными изменениями | `FROZEN.md`, `PERMISSION_MATRIX.md`, `OPS_AI.md` |
| `focussite/frontend/` | Активный React 19 + TypeScript + Vite 6 фронтенд | Да | `src/App.tsx`, `src/panel/PanelApp.tsx` |
| `site/exchange-backend/` | FastAPI, API-контракты, бизнес-правила, SQL-миграции | Только с явным согласием | `main.py`, затем нужный `routers/*.py` |
| `bot/tg_bot_btc/` | Production Telegram-бот, webhook и бот-специфичные services | Да, с повышенной осторожностью | `main.py`, затем handler/service нужного потока |
| `focussite/docker-compose.yml` и `focussite/docker/` | Изолированный локальный стек | Только для локальной инфраструктуры | `focussite/DOCKER_LOCAL.md` |
| `focus-panel/` | Старый Vue-макет | Нет, только чтение | Использовать лишь как визуальный референс |
| `site/focuspay.org/` | Упоминаемый legacy compiled-сайт | В текущей копии отсутствует | Не использовать как источник реализации |

## 3. Первый час в проекте

### 1. Сохранить контекст рабочей копии

```bash
git status --short
git log --oneline -10
```

В репозитории может быть крупный незакоммиченный WIP одновременно во frontend, backend и bot. Не форматируйте и не «подчищайте» чужие файлы, не объединяйте вашу задачу с чужими изменениями и перед правкой сверяйте дифф конкретного файла.

### 2. Прочитать ограничения до выбора решения

Минимум:

1. [`AGENTS.md`](../AGENTS.md) — система, границы и production-практики;
2. [`docs/FROZEN.md`](FROZEN.md) — что нельзя применять автоматически;
3. [`docs/PERMISSION_MATRIX.md`](PERMISSION_MATRIX.md) — если задача касается `/x8`, `/ops`, шаблонов, финансов или внешних сделок;
4. [`docs/OPS_AI.md`](OPS_AI.md) — если работа пришла из Ops AI или относится к `/x8/ai-tasks` и `/ops/dev-requests`;
5. документацию конкретной подсистемы: например `bot/tg_bot_btc/SECURITY.md`, `bot/tg_bot_btc/DEPLOY.md`, `focussite/DOCKER_LOCAL.md`.

### 3. Выбрать поверхность и найти маршрут

Начинайте поиск не с полного-text search по слову, а с точки входа:

| Задача | Первое место поиска |
|---|---|
| Страница публичного сайта | `focussite/frontend/src/App.tsx` |
| Экран `/x8` | `focussite/frontend/src/panel/admin/AdminRoutes.tsx` |
| Экран `/ops` | `focussite/frontend/src/panel/operator/OperatorRoutes.tsx` |
| HTTP-ответ, валидация или права | `site/exchange-backend/routers/<домен>.py` |
| Вход, JWT, 2FA, scope | `site/exchange-backend/auth.py`, `routers/auth_router.py` |
| Сообщение или кнопка Telegram | `bot/tg_bot_btc/main.py`, затем `handlers/` |
| Расчёт, подтверждение или переход заявки | `bot/tg_bot_btc/services/order_transitions.py`, связанные `services/` |
| Callback Payfast | `bot/tg_bot_btc/services/webhook_server.py` |
| Схема или новые данные | `site/exchange-backend/migrations/`, затем реальные запросы |

Дальше следуйте цепочке **route/handler → page/service → API client/запросы → API router → запросы к БД/интеграции**.

### 4. Не угадывать API

Перед изменением UI откройте реальный endpoint в `site/exchange-backend/routers/`. Фронтенд должен читать поля, которые сервер действительно возвращает; `kind` и `campaign_kind`, `orders` и `mine`, `fiat_sum` и `fiat_volume` не взаимозаменяемы. При неясности форма ответа проверяется у авторизованного API разрешённым способом, без создания токенов в обход входа или 2FA.

## 4. Frontend: сайт, admin и operator

Корень: `focussite/frontend/`. Это React 19, TypeScript strict, Vite 6 и Tailwind v4. Здесь две независимые SPA, которые собираются одной командой.

### Точки входа

| Вход | HTML | Bootstrap | Назначение |
|---|---|---|---|
| Public | `index.html` | `src/main.tsx` | Сайт, клиентский кабинет, portal партнёра/обменника |
| Panel | `panel.html` | `src/panel/main.tsx` | Admin `/x8` и operator `/ops` |

`vite.config.ts` объявляет обе страницы как build input. В development `/x8` и `/ops` переписываются на `panel.html`; `/api` проксируется в `VITE_API_TARGET`, а при отсутствии переменной — на `https://focuspay.org`.

> **Осторожно:** локальный frontend dev server по умолчанию работает против боевого API. Не выполняйте реальные мутации ради проверки интерфейса.

### Публичная SPA

- Роуты: `src/App.tsx`.
- Страницы: `src/pages/`.
- Общие компоненты: `src/components/`; shadcn-подобные примитивы — `src/components/ui/`.
- Сеть, сессия, тема и live events: `src/lib/`.

Основные маршруты: `/`, `/exchange`, `/exchange/order/:orderId`, `/login`, `/register`, `/cabinet/*`, `/partner/*`, `/exchanger/*`, `/casino/creator`.

`src/main.tsx` оборачивает приложение в `ThemeProvider`, `BrowserRouter` и `SessionProvider`. Public API-клиент расположен в `src/lib/api.ts`: он работает от `/api`, управляет user/partner/exchanger токенами, отправляет cookies и очищает токен при `401`. Пользовательская сессия живёт в `src/lib/session.tsx`; профиль загружается через `/auth/me`.

Типовые API-модули:

| Что нужно изменить | Где искать |
|---|---|
| Вход, CAPTCHA, TOTP, Telegram login | `src/lib/auth.ts`, `src/pages/Login.tsx` |
| Курсы, отзывы, рефералы | `src/lib/public.ts` |
| Создание и действия с web-заявкой | `src/lib/orders.ts`, `src/pages/Exchange.tsx`, `src/pages/Order.tsx` |
| Профиль, balance, cashback, promo, FocusLucky | `src/lib/user.ts` |
| Чат и загрузка файлов по заявке | `src/lib/chat.ts`, `src/components/OrderChat.tsx` |
| Партнёрский и exchanger portal | `src/lib/portals.ts`, `src/pages/PartnerPortal.tsx`, `src/pages/ExchangerPortal.tsx` |

### Панель сотрудников

- Корневой router: `src/panel/PanelApp.tsx`.
- Admin-пути и навигация: `src/panel/admin/AdminRoutes.tsx`.
- Operator-пути и навигация: `src/panel/operator/OperatorRoutes.tsx`.
- Аутентификация, запросы и polling: `src/panel/lib/`.
- UI-система панели: `src/panel/ui/`, стили: `src/panel/panel.css`.

`PanelApp` выбирает scope по URL: `/x8/*` получает `PanelSessionProvider scope="admin"`, `/ops/*` — `scope="operator"`. Panel API-клиент в `src/panel/lib/panelApi.ts` хранит admin и operator токены отдельно, ограничивает запрос 20 секундами и при `401` очищает сессию. Login/2FA/me/logout находятся в `src/panel/lib/panelAuth.ts`.

Основные экраны:

| Роль | Примеры URL | API слой |
|---|---|---|
| Admin | `/x8`, `/x8/orders`, `/x8/users`, `/x8/chat`, `/x8/ai-tasks`, pricing, payroll, promo, partners, casino, security, settings | `src/panel/lib/adminApi.ts` |
| Operator | `/ops`, `/ops/orders`, `/ops/create`, `/ops/client/:userId`, shifts, payroll, promo, chat, templates, reviews, profile | `src/panel/lib/operatorApi.ts` |
| Общие чаты/шаблоны/broadcast | Соответствующие panel screens | `src/panel/lib/chatApi.ts` |

Права в UI — это удобство, а не security boundary. Окончательная авторизация — на сервере; изучайте [`PERMISSION_MATRIX.md`](PERMISSION_MATRIX.md) и `site/exchange-backend/permissions.py`.

### State, SSE и стили

В проекте нет Redux, Zustand, React Query или централизованного server-state. Обычный паттерн: страница вызывает typed API-функцию в `useEffect`/`useCallback`, хранит данные, loading и error в `useState`, а после мутации перезагружает данные или локально обновляет состояние.

- Public live updates: `src/lib/useLiveEvents.ts`; страница заявки сочетает SSE с fallback polling.
- Panel polling: `src/panel/lib/useAuthedPoll.ts`.
- Реалтайм — **SSE, не WebSocket**. `EventSource` передаёт access token в query string, событие служит сигналом обновить данные авторизованным запросом.

Дизайн-системы изолированы:

| Поверхность | Система |
|---|---|
| Публичный сайт | `src/index.css`, Tailwind v4, CSS-токены, светлая и тёмная темы, public `components/ui/` |
| Панель | `src/panel/panel.css`, near-black тема, `src/panel/ui/` primitives, всегда тёмная |

Не переносите произвольно shadcn-подобные public-примитивы в панель или panel-примитивы на сайт. Не хардкодьте цвета: используйте существующие CSS-переменные и токены нужной системы.

## 5. Backend: API, права и данные

Корень: `site/exchange-backend/`. Это FastAPI backend, который является контрактом для сайта и панелей. Не переписывайте backend без явного согласия; для frontend-задач обычно достаточно чтения нужного router.

### Точка входа и инфраструктурные слои

- ASGI-приложение и подключение роутеров: `main.py`.
- Startup/shutdown, asyncpg pool, runtime settings, listeners и фоновые задачи: `main.py`.
- Глобальный пул PostgreSQL: `db.py`.
- Pydantic Settings и проверка production-конфигурации: `config.py`.
- JWT, password hashing, browser sessions и RBAC helpers: `auth.py`.
- Атомарные разрешения: `permissions.py`.
- SQL-схема и изменения: `migrations/`.

На старте backend поднимает не только API, но и фоновые процессы: runtime settings, синхронизации, расчёты/уведомления, cleanup CAPTCHA и другие интеграции. Не отключайте, не перезапускайте и не меняйте их scheduling без отдельного согласования.

### API-префиксы

| Префикс | Домен |
|---|---|
| `/api/public` | Публичная конфигурация, ставки, CAPTCHA, отзывы, рефералы |
| `/api/public` и web-order router | Жизненный цикл web-заявок |
| `/api/auth` | Логин и сессии user/admin/operator/partner/exchanger |
| `/api/user` | Кабинет пользователя, заявки, balance, cashback, referrals, battle |
| `/api/admin` | Управление заявками, пользователями, ставками, финансами, операторами, промо и интеграциями |
| `/api/operator` | Очереди, смены, заявки, выплаты, клиенты, чаты и отзывы |
| `/api/partner` | Партнёрский кабинет, ledger и выводы |
| `/api/exchanger`, `/api/exchanger/v1` | Внешние обменники и HMAC API сделок |
| `/api/internal`, `/api/internal/casino` | Доверенные внутренние bot/casino-интеграции |
| `/api/bot` | Интеграция с exchanger bot |
| `/api/casino/creator` | Creator API казино |

Для первого чтения: `routers/public.py`, `routers/web_orders.py`, `routers/auth_router.py`, `routers/operator.py`, `routers/admin_orders.py`, `routers/partner.py`, `routers/exchanger.py`, `routers/exchanger_v1.py`, `routers/internal_casino.py`.

### Авторизация и миграции

API использует Bearer JWT; browser-сессии сохраняются как хэши токенов. У panel есть cookie fallback. Operator login включает обязательный 2FA-flow. Никогда не создавайте JWT импортом внутренней функции, не пропускайте 2FA и не используйте чужие секреты для «быстрого» доступа.

Миграции — SQL-файлы в `site/exchange-backend/migrations/`; обнаруженного Alembic или общего автоматического migration runner нет. Перед любым изменением схемы:

1. прочитайте существующие миграции и реальные запросы;
2. подтвердите точные имена таблиц и колонок;
3. согласуйте порядок применения, backup и production-план;
4. не применяйте и не исправляйте данные без явного разрешения.

Финансовые ledger, economics snapshot, payout, external/casino и Ops AI migrations особенно чувствительны.

## 6. Telegram-бот и Payfast webhook

Корень: `bot/tg_bot_btc/`. Это production-бот с пользовательским обменным flow, операционными функциями, подтверждением оплаты и отдельным FastAPI webhook-сервисом. Изменения в этой области могут влиять на реальные деньги, статусы и коммуникации с клиентами.

### Как пройти от апдейта Telegram к бизнес-логике

- Точка входа, startup и регистрация обработчиков: `main.py`.
- `/start`, CAPTCHA, реферальная/promo attribution, защита активной заявки: `handlers/start.py`.
- Основной exchange FSM: `handlers/exchange_flow.py`.
- Бизнес-направленные Telegram handlers: `handlers/`.
- Сервисы денежных операций, заявок, risk и операций: `services/`.
- Работа с bot DB: `services/db.py`.

Порядок handler registration в `main.py` намеренный: admin callbacks регистрируются раньше, CAPTCHA использует раннюю группу, а review/chat FSM имеют повышенный приоритет. Не перемещайте регистрацию обработчиков без понимания конфликтов фильтров и диалоговых состояний.

`main.py` стартует в webhook-режиме, если задан `TELEGRAM_WEBHOOK_URL`; иначе используется polling. Pending updates сохраняются намеренно. Перед запуском проверяется обязательная bot-конфигурация: token, DSN, callback secret, admin IDs, а для production webhook — merchant key и IP allowlist.

### State machine заявки

`services/order_transitions.py` задаёт допустимые статусы и переходы. Ключевой инвариант: `AWAITING_CHECK` не может стать `COMPLETED` напрямую — подтверждение сначала переводится в `PENDING`. Не обходите transition layer, не обновляйте статус прямым SQL и не меняйте этот граф без отдельного согласования и тестов.

Группы services удобно читать по назначению:

| Домен | Примеры |
|---|---|
| Заявки и деньги | `order_transitions.py`, `order_financial.py`, `order_expirer.py`, `payfast_*`, `payout_*`, `financial_guards.py` |
| Merchant API | `merchant_client.py`, `merchant_api_helpers.py` |
| Антифрод и идентификация | `antispam.py`, `buyer_access_guards.py`, `buyer_risk.py`, CAPTCHA/device-review services |
| Партнёры, cashback, promo | `partner_*`, `user_referral_*`, `cashback_tier.py`, `promo_*` |
| Операторы и owner | `admin_callbacks.py`, `owner_*`, `operator_*` |
| Telegram WebApp | `tg_webapp_initdata.py`, `webapp_requisites.py` |

### Webhook Payfast

Webhook — отдельное FastAPI app: `services/webhook_server.py`. Он проверяет конфигурацию и DB на startup, принимает только разрешённые IP через trusted-proxy/allowlist, проверяет HMAC, связывает body с путём заявки, заново проверяет сумму и settlement. GET callback запрещён.

Инварианты также находятся в `services/webhook_security.py`: ограничение возраста HMAC, fail-closed пустой IP allowlist вне localhost development, допуск суммы и допустимый статус для завершения BUY. Не меняйте HMAC, IP allowlist, сумму-допуск, completion logic, merchant settings или reconciliation без отдельного согласования.

### Production file stores

Часть runtime stores — это реальные состояния production, а не cache тестов. Например `services/ops_group_store.py` управляет привязкой операционного чата. Аналогичные file-backed stores: `community_chat_store.py`, `news_chat_store.py`, `reviews_chat_store.py`, `external_deals_group_store.py`, `client_review_group_store.py`, `operator_shift_store.py`, `swap_commission_store.py`.

Ручное изменение либо удаление файлов в production data directory может переназначить чаты для финансовых, security и moderation уведомлений. Не выполняйте такие действия без согласованного runbook и backup.

## 7. Ключевые потоки: от интерфейса до обработки

| Сценарий | Начать в UI/канале | API и backend | Бот / дальнейшая обработка |
|---|---|---|---|
| Web-заявка клиента | `src/pages/Exchange.tsx`, `src/lib/orders.ts` | `routers/web_orders.py`, связанные public/user routers | Статус и чат обновляются через SSE; последующие операции могут прийти к operator flow |
| Карточка web-заявки, чек и чат | `src/pages/Order.tsx`, `src/lib/chat.ts`, `src/lib/useLiveEvents.ts` | Роутеры web-orders/public chat | SSE — только сигнал; актуальные данные загружаются авторизованным запросом |
| Заявка через Telegram | `handlers/start.py`, `handlers/exchange_flow.py` | DB/internal API bridge по конкретному service | `services/db.py`, `order_transitions.py`, merchant/payout services |
| Подтверждение оплаты провайдером | Не UI-flow | Проверить связанную server-side интеграцию | `services/webhook_server.py`, `webhook_security.py`, Payfast/reconciliation services |
| Очередь и обработка оператором | `panel/operator/OperatorRoutes.tsx`, нужный экран, `operatorApi.ts` | `routers/operator.py`, `permissions.py` | Операционные уведомления и связанные services бота |
| Админское изменение заявки/настроек | `panel/admin/AdminRoutes.tsx`, `adminApi.ts` | Нужный `routers/admin_*.py`, `auth.py`, `permissions.py` | Оценить эффект на бот, background jobs и ledger до реализации |
| Партнёр/внешний обменник | `pages/PartnerPortal.tsx` или `ExchangerPortal.tsx`, `lib/portals.ts` | `routers/partner.py`, `exchanger.py`, `exchanger_v1.py` | HMAC и payout-потоки требуют отдельной проверки безопасности |

## 8. Локальная разработка и проверки

### Frontend

```bash
cd focussite/frontend
npm ci
npm run dev
npm run build
```

`npm run build` выполняет TypeScript build и собирает оба Vite entry. Во frontend нет встроенных `test`/`lint` scripts и нет formal component/E2E test runner. Есть узкие structural smoke scripts в `focussite/frontend/scripts/`, которые запускаются напрямую Node при работе с соответствующим экраном.

### Python-тесты

```bash
cd bot/tg_bot_btc
pytest tests/ -q --tb=short

cd ../../site/exchange-backend
pytest tests/ -q --tb=short
```

Запускайте сначала тесты затронутого компонента и всегда честно фиксируйте, если тест невозможен из-за отсутствующей локальной инфраструктуры. Pytest-настройки находятся в `bot/tg_bot_btc/pytest.ini` и `site/exchange-backend/pytest.ini`.

### Общая проверка репозитория

```bash
./scripts/check.sh
./scripts/check.sh --full
```

`--full` дополняет базовые проверки Python suites, frontend build и Bandit. Выбирайте объём проверки по фактически затронутому коду; перед передачей frontend-изменения `npm run build` обязателен.

### Локальный полный стек

В `focussite/` есть Docker Compose для PostgreSQL, Redis, backend, bot, webhook и nginx gateway. Инструкция и ограничения — [`focussite/DOCKER_LOCAL.md`](../focussite/DOCKER_LOCAL.md). Стенд предназначен для local-only использования, gateway доступен на loopback `localhost:8080`.

### Production deploy: только справка

Frontend deploy выполняется из `focussite/frontend/` через `scripts/deploy_all.py`; он затрагивает одновременно public и panel entry. `scripts/deploy.py` — только public entry. Утилиты имеют backup-механику, но запуск остаётся production-действием.

Не выполняйте deploy, изменения nginx/systemd, restart сервисов и SQL migration без явной просьбы пользователя, согласованного плана и требуемых backup. Текущие unit-файлы и runbook должны быть сверены до исполнения: в части старых текстов деплоя есть исторические примеры, не совпадающие с актуальным `User`, портами или bind address.

## 9. Правила изменения кода

### Обязательный порядок

1. Прочитать нужный контракт, текущий код и документацию домена.
2. Установить владельца данных и все затрагиваемые поверхности.
3. Сделать наименьшее изменение, согласованное со стилем соседнего кода.
4. Для frontend защищённо обработать неполные поля: использовать `Record<string, unknown>` и известные поля, `String()` / `?? "—"` там, где контракт допускает вариации.
5. Запустить релевантные проверки.
6. При значимой архитектурной или операционной перемене обновить связанный документ в `docs/`.
7. Не коммитить, не пушить и не деплоить без явной команды.

### Security и финансовые границы

Без отдельного явного согласования нельзя менять:

- секреты, `.env`, DSN, JWT/2FA и все токены;
- RBAC, scopes, auth middleware, session recovery, CAPTCHA и антифрод;
- Payfast/HMAC, merchant settings, callback, reconciliation, допускаемую сумму и checkout logic;
- переходы статусов заявок, payout, ledger, economics snapshot, комиссии, курсы, лимиты и зарплатные формулы;
- SQL-схему, migrations, backfill и production data;
- systemd units, nginx, Cloudflare, UFW/fail2ban, bind address/порты и background jobs;
- production file stores для групп/чатов.

Для панели помните: UI не определяет право. Нельзя показывать операторам финансовые поля только потому, что экран спрятан или поле не используется; серверная permission-проверка и контракт остаются источником истины.

## 10. Документы по темам

| Когда нужна информация | Читать |
|---|---|
| Все общие правила и production контекст | [`AGENTS.md`](../AGENTS.md) |
| SSH на прод и staging | [`SSH_ACCESS.md`](SSH_ACCESS.md) |
| Нельзя автоприменять / трогать без OK | [`FROZEN.md`](FROZEN.md) |
| Роли admin/operator и доступы | [`PERMISSION_MATRIX.md`](PERMISSION_MATRIX.md) |
| Ops AI и `/x8/ai-tasks` | [`OPS_AI.md`](OPS_AI.md) |
| Privacy, AI и новости | `docs/PRIVACY_AI_NEWS.md` |
| Merchant / partner bridge | [`INTEGRATION.md`](INTEGRATION.md) |
| Local Docker stack | [`focussite/DOCKER_LOCAL.md`](../focussite/DOCKER_LOCAL.md) |
| Deploy, security, backups и bot migrations | `bot/tg_bot_btc/DEPLOY.md`, `SECURITY.md`, `scripts/BACKUP.md`, `migrations/README.md` |
| Backend security self-check | `site/exchange-backend/deploy/security/README.md` |
| Casino | `CASINO_DEPLOYMENT.md` и связанные docs; считать rollout незавершённым, пока не подтверждено иное |

## 11. Актуальность знаний и Obsidian

Obsidian vault хранит полезные решения, аудиты и межпроектные планы, но не заменяет текущий код и правила репозитория.

### Иерархия источников

При расхождении проверяйте источники в таком порядке:

1. текущий код, SQL-миграции, unit-файлы и `git diff` конкретного checkout;
2. [`AGENTS.md`](../AGENTS.md), `docs/FROZEN.md` и контракт нужного API router;
3. недавние коммиты и их тесты;
4. актуальные runbook’и в этом репозитории;
5. Obsidian: решения, исторические ревью и межпроектный контекст;
6. исторические snapshot-файлы и старые deploy-примеры.

FocusPay в vault доступен через `~/Documents/brain/Projects/FocusPay` (исторически ссылался на docs мёртвой копии бота). Актуальные ревью — `docs/Reviews/` в этом репо. Статусные заметки vault в основном датированы 12 августа 2026 года; они не являются источником текущего production-состояния. `CURRENT_TASK`, `STATUS`, старые board/TODO заметки vault нельзя использовать как единственную истину о состоянии задачи или деплоя.

Полезные источники vault:

| Зачем | Где искать | Как использовать |
|---|---|---|
| Риски security/hardening | `Projects/FocusPay` и `SECURITY_AUDIT_OWASP_20260812.md` | Исторический inventory рисков; не утверждать, что finding всё ещё открыт или уже закрыт без проверки текущего diff, тестов, конфигурации и rollout |
| Архитектурные решения экосистемы | `Projects/MYVPN/adr/007-ecosystem-billing-federation.md` | Принятое решение: федерация, а не общая физическая БД; FocusPay владеет Telegram identity и RUB ledger, FocusVPN — VPN-сущностями |
| Межсервисный биллинг VPN | `Projects/MYVPN/plans/E1-vpn-bot.md`, `Ecosystem/Integration-users-balance.md` | Контракты могут быть реализованы, но production deployment и секреты должны подтверждаться отдельно |
| Исторические решения финансового dashboard | `docs/Reviews/2026-08-12-owner-dashboard-freeze.md` | Прочитать перед изменением owner metrics; не создавать искусственный ledger backfill |

### Недавний подтверждённый контекст

- Недавние коммиты 23 августа 2026 года включают immutable snapshot экономики заявки (`bot/tg_bot_btc/services/economics_snapshot.py`) и более явную обработку ошибок receipt review/Payfast: отсутствие Payfast UUID — это диагностируемая ошибка, а не повод слать некорректный fallback request.
- В текущем WIP есть security и production-hardening изменения в backend, frontend и bot: guest-session cookie binding, CAPTCHA/security configuration, RBAC/finance и fail-secure webhook IP policy. Пока конкретный diff не прошёл review, тесты, конфигурационную проверку и production rollout, нельзя объявлять исторические P1 finding закрытыми.
- Casino остаётся local-only до выполнения отдельных условий rollout из `CASINO_DEPLOYMENT.md`: не запускать его миграции, не менять nginx/services и не деплоить без независимого согласования, backup и runbook.

## 12. Текущее состояние и расхождения документации

Этот раздел защищает от принятия исторических артефактов за текущую реализацию.

- В рабочем дереве могут одновременно находиться незакоммиченные изменения frontend, backend и bot. Перед работой всегда смотрите `git status` и ограничивайте свой diff.
- `README.LOCAL.md` — снимок от 11–12 августа 2026 года, а не текущий onboarding. Он сохранён для исторического контекста.
- Боевой бот — `bot/tg_bot_btc` в этом репо (`/opt/tg_bot_btc` на сервере). `~/Desktop/tg_bot_btc.DEAD-20260821` — архив от 21 августа 2026 года, не править.
- Упоминаемый в старых описаниях `site/focuspay.org/` отсутствует в текущем checkout. Не используйте legacy compiled assets как доступный референс.
- В `bot/tg_bot_btc/DEPLOY.md` есть старые примеры запуска от root и на иных портах. Перед deployment-действием сверяйте с текущими systemd unit-файлами в `bot/tg_bot_btc/deploy/`.
- В ряде старых инструкций migration runner может упоминаться как существующий, хотя в `site/exchange-backend/` не обнаружен единый автоматический runner. Порядок SQL-миграций должен подтверждаться отдельно.
- Casino и Sticker AI нельзя считать полным production rollout только по наличию кода: casino deployment ограничен условиями, а Sticker AI feature-flagged и частично scaffold.

## 12. Краткий checklist перед передачей изменения

- [ ] Я знаю, какой компонент является владельцем поведения и данных.
- [ ] Я прочитал реальный API-contract/router или handler, а не угадал его форму.
- [ ] Изменение не затрагивает финансовый, auth, webhook, infrastructure или migration контур без явного согласования.
- [ ] Я не добавил и не вывел в лог секреты.
- [ ] UI использует дизайн-систему своей поверхности и её CSS-токены.
- [ ] Я выполнил релевантную сборку/тесты и указал результат.
- [ ] Я не закоммитил, не запушил и не задеплоил изменения без явной просьбы.
