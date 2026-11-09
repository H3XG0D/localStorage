# Как это работает и что проверить

Lab: Doliv `http://localhost:5175` (API `:8002`). FocusPay: FE `:5173`, API `:8000` (admin `admin` / `admin123456`).

## Кто что делает

```
Клиент / внештатник / ops  →  FocusPay
                                      ↓  мост (X-Bridge-Key)
Трейдеры / карты / депозит  →  Doliv
Партнёры по API             →  Doliv Merchant (как Payfast)
```

- **FocusPay** — обмен, операторы, внештатники и их USD-баланс.
- **Doliv** — трейдеры, карты, float, апрув депозита, очередь выплат.
- **Не** два кабинета трейдера.

## Переключатель ролей (lab)

На `http://localhost:5175` в шапке и на экране входа кнопки: **Owner / Админ / Тимлид / Трейдер / Мерчант / Долив**. Только `npm run dev`, не для продакшена.

## Логины Doliv (seed)

| Кто | Логин | Пароль |
|-----|--------|--------|
| Admin | admin | admin123 |
| Тимлид | teamlead1 | teamlead123 |
| Трейдер | trader1 | trader123 |
| Доливщик | doliv1 | doliv123 |

У trader1: **1000 USDT** личный депозит + карта СБП с **80 000 ₽ float**.

Lab-ключи (уже в seed + `.env` FP):

- Bridge: `X-Bridge-Key: doliv-lab-bridge-dev-key`
- Merchant: `api_key=lab_merchant_key` / `secret=lab_merchant_secret`

FP `.env`: `DOLIV_BRIDGE_URL=http://127.0.0.1:8002` + тот же ключ. Backend FP стартовать с `TG_BOT_PATH=~/Desktop/tg_bot_btc` (иначе не поднимется).

## Как пользоваться по ролям

### 1. Трейдер (Doliv `/trader`)

**Депозит** → заявка «Пополнить» или «Вывести» (сеть + адрес кошелька). Самому баланс не начисляется. Fee: **$3 USDT**, **$2 BTC/LTC**.

**Выплаты** → очередь PayoutJob. Принять за **15 мин**, указать сумму ≤ float на картах. Стараться закрыть одним крупным claim (меньше чеков). «Выплатил» после перевода.

**Карты** → C2C/СБП в работу → hold с личного депозита.

### 2. Админ Doliv (`/admin`)

**Мост / апрувы** — одобрить/отклонить депозит-вывод; создать payout job вручную; float сводка; ключи (уже засеяны).

**Пользователи** — пул % тимлида (12%).

### 3. Внештатник (FocusPay `/exchanger`)

Сделки как раньше. На **Вывод баланса**:

- крипта на кошелёк (как было);
- **новый блок: «Вывести ₽ на карту / СБП»** → заявка уходит трейдерам Doliv.

На дашборде видна **конверсия** (успешные / успешные+фейл).

### 4. Оператор FocusPay (`/ops` заявки)

Сверху: **Doliv float на картах**.  
SELL (своя заявка, статус PENDING): кнопка **«Отправить выплату трейдерам Doliv»**.

### 5. Партнёр (Merchant API)

Как к Payfast: HMAC `create_order_payin` → `bill` (реквизит с карты трейдера) → poll `get_order` → cancel / callback.  
Инструкция: [`INTEGRATION.md`](./INTEGRATION.md).

## Чеклист проверки (10 мин)

1. Doliv FE `:5175` + API `:8002` живы. `cd backend && python seed.py` (идемпотентно).
2. **trader1** → Депозит: заявка вывод 10 USDT TRC20 + адрес → статус pending.
3. **admin** → Мост / апрувы → OK. У трейдера баланс −13 (10+fee 3).
4. **admin** → создать payout job 15 000 ₽ СБП.
5. **trader1** → Выплаты → принять 15000 (float 80k хватает).
6. FP (после рестарта backend): ops → Заявки, виден float Doliv.
7. FP внештатник → Вывод → «₽ на СБП» → в Doliv появляется job.
8. Admin FP → Внештатники: колонка **Конверсия**.
9. Merchant smoke (из `INTEGRATION.md`) с lab ключами → `status_pending=ok` и `bill.reciver` (телефон СБП или номер карты в работе).

## Если не работает

- Seed: `DEV_MODE=true`, Postgres lab `:5433`.
- Мост 503/502: FP не видит `DOLIV_BRIDGE_*` или Doliv API не на `:8002`.
- Claim 400 «Insufficient card float»: нет открытой сессии с float (seed SBP).
- Merchant error «No accepting card»: карта не в работе / сумма вне коридора 1000–50000.
