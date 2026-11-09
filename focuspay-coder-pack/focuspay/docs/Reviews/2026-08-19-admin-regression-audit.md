# Админ-панель `/x8` — регрессии после редизайна

**Дата:** 2026-08-19  
**Принцип:** не переписывать то, что в новой панели уже сделано хорошо. Вернуть только потерянное, нужное в работе.  
**Референс старой панели:** `~/Desktop/exchange/frontend/src/pages/admin/` + `components/admin/` (~17 303 строк).  
**Прод:** `https://focuspay.org/assets/panel-03AfgQKf.js` совпадает с локальной сборкой `focussite/frontend/dist/assets/panel-03AfgQKf.js`.

---

## 1. Что в новой панели сохранено и улучшено (не трогаем)

- Обзор владельца: периоды, тренды, ledger, «Требует внимания» (`AdminDashboard.tsx`).
- Операторы: роли client/finance, грейды, индикатор `shift_gate`.
- `/x8/payroll`: фонд, доли ролей, грейды, распределение смены, оклады.
- Выплаты операторам: вкладки pending/paid/rejected.
- Рассылка: стикеры, AI-черновик, HTML-preview, отмена job.
- FocusLucky: close/activate/draw/pay-balance + новая кампания без розыгрыша.
- AI-задачи, sticker-AI, виджет чата.
- Заявки: фильтры crypto/partner, пресеты, sync-crypto, мобильные карточки.
- Поиск и пагинация там, где в старой версии их не было.

---

## 2. Живые баги (волна 1)

Проверены в коде и в прод-бандле. Боевой API (без JWT): существующие маршруты дают `401`, отсутствующие — `404`.

| Баг | Следствие | Где |
|---|---|---|
| Pending-выплаты читают `r.payouts`, API отдаёт `{"items":[...]}` | Вкладка «Выплаты» всегда пуста, KPI = 0 | `AdminExternal.tsx:41` vs `admin_external.py:785` |
| KPI оборота читает `turnover_usd` / `liabilities_usd` | «Оборот $» пустой | API: `total_turnover_base_rub`, `total_balance_usd`, `active_count` |
| Тиры партнёров: чтение с корня, PATCH `step`/`every_n` | Поля пустые; шаг/потолок не сохраняются (`400 No fields to update`) | `AdminPartners.tsx:85-107` vs `admin_referral_partners.py:56-61,221-234` |
| Кнопки Ban / Unban / CSV / Lockdown | 404 на проде | `GET /api/admin/security/events/export`, `/bans`, `/lockdown` → 404; `/events` и `/events/stats` → 401 (есть) |
| Прибыль в заявках без `can_view_finance` | Чистая видна любому админу | `AdminOrders.tsx` DealBubble |

Решение по безопасности (без правок бэкенда): убрать нерабочие кнопки из UI. Реализация эндпоинтов — отдельное согласование.

---

## 3. Исчезнувшие экраны

| Старый роут | Что было | Backend готов |
|---|---|---|
| `/x8/partners/:id` | Кабинет партнёра: KPI, тир, клиенты, заявки, ledger, выводы с реквизитами | `GET /promos/{id}`, `GET .../withdrawals`, `PATCH /referral-partners/{id}` |
| `/x8/users/:userId` | Карточка клиента: рефералка, ledgers, отзывы, заявки | `GET /users/{id}` → `build_buyer_profile` |
| `/x8/operators/:id` | Статистика смен, балансы по дням | `GET /operators/{id}/stats` (`getOperatorStats` в `adminApi.ts` не вызывается) |
| `/x8/promo/:id` | Активации `gift_entries` | `GET /promos/{id}` |
| `/x8/finance` | Единый P&L + расходы + зарплаты | Разъехалось на `/stats`, `/expenses`, `/payroll` |

---

## 4. Потери по разделам (кратко)

**Партнёры / рефералы (главная боль).** `GET /referral-partners` уже отдаёт `summary` и метрики каждого партнёра (`effective_percent`, `paid_fiat_sum`, `service_profit_*`, `refs_until_next_tier`, `referral_link`). UI выбрасывал summary и рисовал 5 колонок. Нет страницы партнёра, нет `patchPartner`, unified-выводы всегда шли с `source=partner`.

**Пользователи.** Модалка показывает 10 плоских полей. API отдаёт `referral`, `ledgers.cashback/referral`, `recent_orders`, `reviews`, `finance`, `active_order`.

**Балансы.** Нет KPI `users_cashback_rub` / `users_referral_rub`. Нет ссылки на клиента/партнёра.

**Внешние обмены.** Кроме парсинга: нет ввода сделки с preview, instant payout, `PATCH .../fee`, `/history`, детали сделки и чек, поля markup/trust/auto_credit.

**Операторы / смены.** Список упрощён намеренно (роли/грейды остались). Профиль `/operators/:id` и `GET .../stats` не подключены. В сменах нет раскрытия заявок и фильтра `operator_id`.

**Заявки.** Нет deep-link фильтров, нумерованной пагинации, блоков Payfast/отмены в модалке. Finance-гейтинг прибыли потерян.

**Отзывы.** Нет `pending-count`, поиска, пагинации, master-detail, суточного лимита бонуса.

**Рассылка.** Нет `upload-photo`, баннера прогресса, карточки job, `GET jobs/{id}/photo`.

**Админ-чат.** Нет отправки файла и `before_id` (в операторском чате осталось).

**Расходы.** `patchExpense` есть в `adminApi.ts`, кнопки нет.

**Дашборд.** Обёртки `getPnl`, `dashWalletDaily`, `dashVolumeCohorts` нигде не вызываются.

**Настройки.** Нет QR 2FA (секрет текстом). Не блокер.

---

## 5. Мёртвые обёртки `adminApi.ts`

`getPnl`, `dashWalletDaily`, `dashVolumeCohorts`, `patchExpense`, `getOperatorStats`, `getPromo`, `createExchangeDiscount`, `patchPartner`, `promoPayout`, `getOperatorPayrollSplits`.

Плюс бэкенд без UI: `/ai/audit*`, `/broadcast/upload-photo`, `/reviews/pending-count` (админ).

---

## 6. Предложения (не в этой волне)

- Свести `/x8/payroll` и `/x8/operator-payroll` во вкладки одного раздела.
- Один вход «быстрый партнёр» (сейчас живёт в промокодах).
- Бейджи ожидающих в навигации: отзывы, выплаты внештатников, выводы партнёров.
- Экран журнала AI-аудита (`GET /ai/audit`) — бэкенд готов.
- Либо эндпоинты Ban/CSV/Lockdown в бэкенде, либо кнопки остаются скрытыми.

---

## 7. Волны восстановления

**Волна 1 (этот PR, фронт):** парсинг выплат и KPI внешних обменов; тиры партнёров; скрыть 404-кнопки безопасности; `can_view_finance` на прибыли заявок.

**Волна 2 (этот PR, фронт):** обзор партнёров (`summary` + колонки + ссылки); страница `/x8/partners/:id`; реферальный блок в карточке клиента; KPI кешбэка/рефералки в балансах.

**Волна 3 (по согласованию, не в этом PR):**

| Что | Файлы / API |
|---|---|
| Профиль оператора `/x8/operators/:id` | `getOperatorStats` → `GET /operators/{id}/stats` |
| Внешние: история, деталь, чек, fee, markup/trust | `GET .../history`, `GET /deals/{id}`, `/receipt`, `PATCH /payouts/{id}/fee` |
| Отзывы: счётчик, поиск, пагинация, лимит бонуса | `GET /reviews/pending-count`, `?q=` |
| Рассылка: фото, прогресс, карточка job | `POST /broadcast/upload-photo`, `GET /jobs/{id}` |
| Админ-чат: файлы, история вверх | `POST .../messages/file`, `?before_id=` |
| Правка расхода | `patchExpense` → `PATCH /manual-expenses/{id}` |
| Дашборд: waterfall, wallet-daily, когорты | `getPnl`, `dashWalletDaily`, `dashVolumeCohorts` |

---

## 8. Где искать старую панель

`/home/qwe/Desktop/exchange/frontend/src/pages/admin/` — исходники до редизайна 12.08. В репозитории FocusPay старые бандлы `site/focuspay.org/` в `.gitignore` и локально отсутствуют.
