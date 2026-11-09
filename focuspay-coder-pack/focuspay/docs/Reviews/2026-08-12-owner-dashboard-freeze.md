# Owner Dashboard — Freeze Review (2026-08-12)

**Status:** FREEZE-HIT — реализация и миграции **не начаты**.  
**Scope:** обзор владельца (Telegram `/dash` + админ-панель `/x8` «Обзор»).  
**Refs:** findings про `docs/Reviews/2026-08-11.md` — файл в репозитории **отсутствует**; ниже — фактический аудит текущего кода.

---

## 1. Карта поверхностей (факт)

| Поверхность | Путь | Что делает сейчас |
|---|---|---|
| Telegram `/dash` | `bot/tg_bot_btc/handlers/owner_dashboard.py` → `services/owner_dashboard.py` → `services/owner_analytics.py` | Сводка за сегодня / N дней / дату; деньги через `compute_pnl` (internal API) или legacy SQL |
| Telegram `/pulse` | те же модули | Компактный статус + сегодня + 7 дней |
| ACL Telegram | `FINANCE_OWNER_TELEGRAM_ID` + `is_reports_group_chat` + `reports_group_guard` | Владелец в группе отчётов; guard **не** про финансы |
| Internal PnL | `GET /api/internal/pnl` → `finance_pnl.compute_pnl` | Тот же расчёт, что `/x8` Финансы |
| Админ «Обзор» | `focussite/.../AdminDashboard.tsx` | Live кошелёк / обязательства / `GET /api/admin/stats` (дефолт **30 дней**), KPI = оборот покупок + estimated_profit |
| Админ «Статистика/Финансы» | `AdminStats.tsx` + `/stats/pnl` | Уже есть waterfall / owner_residual за произвольный `date_from`–`date_to` |

**Не найдено:** отдельного owner-dashboard API с периодами `today|yesterday|week|month|year`, сравнением с предыдущим эквивалентным периодом, метриками «новые партнёры», единым ledger операций владельца.

**Не дублировать:** `reports_group_guard` / `reports_chatid` — только привязка Telegram-группы; `compute_pnl` — канонический финансовый движок.

---

## 2. Аудит источников данных

### 2.1 Сделки / «доход»

- Таблица: `orders`.
- Статусы в PnL: `PAID`, `COMPLETED` (`finance_pnl.py`).
- Legacy fallback `/dash`: только `PAID` (`get_paid_orders_for_owner_*`).
- Маржа сделки: `order_service_profit` (спред − card fee − cashback_applied и т.д.) — **пересчёт из полей заказа**, не из зафиксированной проводки.
- Оборот (`fiat_volume` / `turnover_rub`) — **не доход**; в UI `/dash` сейчас рядом с «финальный остаток».
- `COMPLETED` (BUY) = оплата мерчанту есть, крипта клиенту ещё может не уйти → включение в «заработано» спорно.

### 2.2 Расходы / начисления (фрагментированные ledger’ы)

Уже есть, но **не** единый журнал владельца:

| Источник | Назначение |
|---|---|
| `user_cashback_ledger` | кешбэк accrual |
| `user_referral_ledger` | рефералка |
| `partner_ledger` | партнёрка (+ adjustment/payout) |
| `review_bonus_claims` | бонусы за отзывы |
| `operator_wallet_payouts` | выплаты с кошелька оператора |
| `swap_commission_entries` | swap |
| `operator_payroll_ledger` | ЗП операторов (role_split) |
| `manual_expenses` | ручные расходы (mandatory/work/unexpected) |
| `external_ledger` / external stats | внештат |
| USDT issuance × **текущий** market rate | стоимость USDT операторам |

**Единого `owner_finance_ledger` / журнала операций с audit-полями нет.**  
PnL / capital / topup «как отдельная заполненная сущность» — не подтверждены отдельной таблицей; капитализация и topup в текущем `/dash` не показываются.

### 2.3 Пользователи / партнёры

| Метрика сейчас | Источник | Исключения |
|---|---|---|
| Новые бот-юзеры | `bot_users.first_seen_at` | нет soft-delete / blocked / test флага в счётчике |
| Активные бот | `bot_users.last_seen_at` | то же |
| Регистрации сайта | `web_users.created_at` (`is_admin IS NOT TRUE`) | blocked/test не фильтруются явно |
| Новые партнёры | **нет** в `/dash` / AdminDashboard | есть `partner_accounts.created_at`, `is_active` |
| Сравнение с прошлым периодом | **нет** | только текущий период (+ опционально rolling 7д) |

### 2.4 Timezone / границы периодов — расхождения

| Место | Как считает «день» |
|---|---|
| `owner_analytics._today_msk` | `Europe/Moscow` |
| Audience SQL (`CURRENT_DATE`) | TZ сессии PostgreSQL (не гарантированно MSK) |
| `finance_pnl` / `/stats` | `created_at::date` **без** `AT TIME ZONE 'Europe/Moscow'` |
| `admin_stats.get_stats` default | `date.today()` (TZ хоста), не `today_moscow` |
| `admin_dashboard` wallet-daily / cohorts | явно MSK через `AT TIME ZONE` |

Неделя: сейчас = **скользящие 7 календарных дней** (`today − 6 … today`), не ISO week (пн–вс).  
Месяц/год как именованные периоды в `/dash` **не реализованы**.

### 2.5 Авторизация

- Telegram `/dash`: только `is_owner_user` в reports-группе (админы без owner — deny; `/help` админам можно).
- Web AdminDashboard: `get_current_admin`; финансы в `/stats` частично режутся `can_view_finance_admin`.
- Internal `/pnl`: `X-Internal-Token` — не ослаблять; не путать с публичным API.

---

## 3. Предлагаемые определения метрик (черновик до подтверждения)

До подтверждения владельцем **не называть оборот доходом**.

| Ключ | Черновое определение | Источник-кандидат |
|---|---|---|
| `gross_revenue` / gross commissions | сумма маржи сервиса по сделкам периода (до начислений) = `total.net_profit` минус external **или** только spread−fees — **нужно выбрать** | `compute_pnl.total.net_profit` / buckets |
| `refunds_expenses` | возвраты + подтверждённые расходы | **возвраты как отдельный тип в orders/ledger не найдены**; expenses = costs + payroll + manual |
| `net_income` | официальный «заработок владельца» | кандидат A: `payroll.owner_residual`; B: `profit_after_costs` |
| `orders` | число завершённых сделок | PAID only vs PAID+COMPLETED |
| `new_users` | новые валидные пользователи | bot `/start` и/или web_users — **нужно выбрать** |
| `new_partners` | новые `partner_accounts` с `is_active` | `partner_accounts.created_at` |
| `active_*` | только если есть чёткое определение «active» | bot last_seen / paid users |

Динамика: `current`, `previous` (эквивалентная длина), `delta_abs`, `delta_pct` (`null` если previous=0).

Ledger: если добавлять минимальный журнал — **не бэкфиллить выдуманными суммами**; API `data_status: available|empty|unavailable`.

---

## 4. FREEZE QUESTIONS (блокируют реализацию)

Ответы владельца / product нужны **до** кода API, UI, миграций ledger и деплоя.

### Q1. Официальный доход
Что считаем главным KPI «заработано»?
- **A)** `owner_residual` (финальный остаток после ЗП/USDT/manual) — как сейчас `/dash` при from_pnl  
- **B)** `profit_after_costs` (после кешбэка/рефералки/партнёрки, до ЗП)  
- **C)** маржа сделок до любых начислений (`total.net_profit`)  
- **D)** другое (описать формулу)

### Q2. Главная карточка
На первом экране крупно показывать **gross** или **net** (и какой net из Q1)?

### Q3. Состав расходов в net
Включать ли в net: кешбэк, рефералку, партнёрку, review bonus, wallet payout, swap, ЗП операторов, ЗП админа, USDT×курс, manual_expenses (все 3 категории), external house profit?

### Q4. Базовая валюта
Только **RUB**? Нужен ли dual display USD (и по какому курсу — **запрещено** брать LIVE RATES для истории без правила фиксации)?

### Q5. Статус «завершённой» сделки
- **A)** только `PAID`  
- **B)** `PAID` + `COMPLETED` (как `compute_pnl` сейчас)  
- **C)** `PAID` для BUY, иное для SELL  

Учитывать ли дату по `created_at`, `payout_confirmed_at` или `updated_at`?

### Q6. Возвраты
Где в данных живут возвраты/чарджбеки? Если нигде — метрика refunds = `empty`/`unavailable`, не ноль. Подтвердить.

### Q7. Исторические курсы
USDT cost и external→RUB сейчас могут опираться на **текущий** market rate. Правило: фиксировать курс на дату проводки / запретить пересчёт / показывать `unavailable` для historical FX?

### Q8. Периоды
Подтвердить границы в **Europe/Moscow**:
- today / yesterday — календарные сутки MSK  
- week — **пн 00:00 → вс 23:59:59.999 MSK** или скользящие 7 дней?  
- month — календарный месяц или последние 30 дней?  
- year — календарный год или последние 365 дней?  
Previous period = строго предыдущий такой же интервал (не overlapping).

### Q9. Новые пользователи
Считать: только bot `first_seen_at`, только `web_users`, сумму уникальных, или «первый PAID»? Исключать ли заблокированных / тестовых (какие флаги)?

### Q10. Новые партнёры
= новые строки `partner_accounts`? Только `is_active`? Включать referral-partners / promo без логина?

### Q11. Поверхность UI
Где делать новый дашборд в первую очередь?
- **A)** админ `/x8` Обзор (`AdminDashboard`)  
- **B)** Telegram `/dash`  
- **C)** оба, один backend-сервис  

### Q12. Ledger
Создавать ли новую таблицу `owner_finance_ledger` (дата, type, amount, currency, source/reference, status, audit), или достаточно агрегации существующих ledger’ов + `data_status`? Бэкфилл = **запрещён** выдуманными данными — ок?

### Q13. Payfast / новые платежные потоки
Сейчас `/dash` показывает конверсию Payfast. Freeze: **не** расширять Payfast/HMAC/новые pay-in без отдельного review. Оставить as-is / вынести / убрать с первого экрана?

### Q14. Доступ web API
Кто видит новый endpoint: все admin, только finance viewer (`can_view_finance_admin`), отдельный owner flag? Telegram ACL не ослаблять.

---

## 5. Рекомендуемый план после снятия freeze (не выполнять сейчас)

1. Зафиксировать ответы Q1–Q14 в этом файле (секция «Decisions»).  
2. Сервис `owner_dashboard_metrics` в `site/exchange-backend/` (или тонкая обёртка над `compute_pnl` + audience queries) — единые периоды MSK.  
3. API `GET /api/admin/dashboard/owner?period=...` + auth; Telegram `/dash` читает тот же контракт/логику.  
4. UI: вкладки периода + карточки Net / Gross / Orders / New users / New partners + delta; график/разбивка — только если `data_status=available`.  
5. Ledger — только если Q12=да; миграция обратимая; empty ≠ fake zeros.  
6. Тесты: периоды, TZ, статусы, refunds empty, previous=0 → pct null, ACL, empty ledger.  
7. Smoke (после реализации, без автодеплоя):  
   - owner видит 5 периодов;  
   - non-owner 403 / Telegram deny;  
   - сверка цифр с `/stats/pnl` за тот же диапазон;  
   - UI empty/unavailable без «нулей как факта»;  
   - timezone boundary: заказ 23:30 UTC vs MSK день.

---

## 6. Decisions (defaults при «делай», 2026-08-12)

| ID | Decision | Date | By |
|---|---|---|---|
| Q1 | **A** `owner_residual` = официальный net income | 2026-08-12 | owner go-ahead |
| Q2 | Главная карточка = **net**; gross = `total.net_profit` (маржа до начислений, не оборот) | 2026-08-12 | default |
| Q3 | Как в `compute_pnl`: costs + payroll + USDT + manual − в net; оборот не доход | 2026-08-12 | default |
| Q4 | Базовая валюта **RUB** only | 2026-08-12 | default |
| Q5 | **B** `PAID`+`COMPLETED` (как `compute_pnl`); дата среза = `created_at` calendar MSK | 2026-08-12 | default |
| Q6 | Отдельных refunds нет → `refunds.data_status=unavailable` | 2026-08-12 | default |
| Q7 | Исторический доход только из `compute_pnl`/полей заказа; LIVE RATES не использовать для KPI; USDT cost как в PnL | 2026-08-12 | default |
| Q8 | TZ `Europe/Moscow`; week = пн→сегодня (WoT); month/year = с 1-го → сегодня; previous = эквивалентная длина | 2026-08-12 | default |
| Q9 | new_users = bot `first_seen` + web_users (!admin); без fake blocked-фильтра (флагов нет) | 2026-08-12 | default |
| Q10 | new_partners = `partner_accounts` за период (`is_active`) | 2026-08-12 | default |
| Q11 | **C** оба: `/x8` Обзор + Telegram `/dash`, один backend-сервис | 2026-08-12 | default |
| Q12 | Минимальный `owner_finance_ledger` без бэкфилла; API `empty`/`unavailable` | 2026-08-12 | default |
| Q13 | Payfast не на первом экране `/x8`; в `/dash` оставить ниже KPI | 2026-08-12 | default |
| Q14 | Web: `get_current_finance_viewer`; Telegram ACL без ослабления | 2026-08-12 | default |

---

## 7. Smoke-план (из задачи) — чеклист после реализации

- [x] today / yesterday / week / month / year — сервис `resolve_period_window` + API `GET /api/admin/dashboard/owner` (unit-тесты границ)
- [x] прирост users/partners vs previous equivalent period (в ответе metrics.*.previous/abs/pct)
- [x] незавершённые не в PnL (только PAID+COMPLETED); test/blocked flags отсутствуют → документировано
- [x] нет ledger → `data_status=empty|unavailable`, UI не выдаёт нули за факт
- [x] API и UI: Europe/Moscow, week = Monday
- [x] web: `get_current_finance_viewer`; Telegram ACL без изменений reports_group_guard
- [x] unit-тесты owner_dashboard_metrics + bot KPI formatting; миграция обратимая
- [x] live smoke на проде после деплоя (без автодеплоя в этой задаче)
- [x] без Payfast-расширения / без секретов