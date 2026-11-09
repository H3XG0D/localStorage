FocusPay Battle Lab — инструкция для Cursor

Контекст

Делаем прототип мини-игры 🔴 vs 🔵 (механика как CaseBattle) для FocusPay — crypto exchange с Telegram-ботом. Сейчас только игра в изолированной папке. Позже код перенесут в:

~/Desktop/exchange/ — сайт (React + FastAPI, общая БД exchange_bot)

~/Desktop/tg_bot_btc/ — Telegram-бот (только миграции + ссылка, не логика игры)

Не трогать prod, не подключать prod DSN, не деплоить.

Бизнес-цель

Пользователи копят кешбэк и реферальные бонусы на балансе. Battle — способ «слить» эти бонусы: ставка → проигрыш = баланс меньше; rake ~5% с банка уходит из обращения. Выигрыш = чужие проигранные бонусы (PvP, zero-sum минус rake).

Механика (единственное правило)

Каждые 60 сек новый раунд

Игрок ставит ₽ на red или blue

P(red) = red_pool / (red_pool + blue_pool)

RNG выбирает победителя

Победившая сторона делит (red + blue) × (1 - rake) пропорционально своим ставкам

Только одна сторона имеет ставки → отмена раунда, refund

Min ставка 50 ₽, max 5000 ₽ за раунд на user

Пример: red=300 (ты 100 + друг 200), blue=500 → P(red)=37.5%. Red wins → банк 800, payout 760 → ты 253 ₽, друг 507 ₽.

Стек lab (простой, без exchange)

focuspay-battle-lab/
├── CURSOR.md              ← этот файл
├── README.md
├── backend/
│   ├── main.py            # FastAPI
│   ├── battle_engine.py   # resolve, split, rake
│   ├── battle_round.py    # lifecycle 60s
│   ├── wallet.py          # MockWallet (in-memory или SQLite)
│   ├── models.py
│   ├── config.py
│   ├── requirements.txt
│   └── tests/
│       └── test_battle_engine.py
├── frontend/
│   ├── package.json       # Vite + React + TS + Tailwind
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/Battle.tsx
│   │   ├── hooks/useBattlePoll.ts   # GET /api/battle/current каждые 2s
│   │   └── api/client.ts
│   └── vite.config.ts     # proxy /api → :8001
└── scripts/
    └── start.sh           # backend :8001 + frontend :5174

Backend: FastAPI, SQLite battle_lab.db (или in-memory) — не PostgreSQL exchange

Frontend: Vite React, порт 5174 (не 5173 exchange)

Auth в lab: заголовок X-Lab-User: alice или dropdown «игрок 1/2/3» — без JWT

API контракт (сохранить для интеграции в exchange)

Method | Path | Body | Response

GET | /api/battle/current | — | { round_id, seconds_left, red_total, blue_total, red_pct, blue_pct, bank, my_bet: {side, amount} | null, balance_available }

POST | /api/battle/bet | { side: "red"|"blue", amount_rub: number } | updated current

GET | /api/battle/history?limit=20 | — | [{ round_id, winner, red_total, blue_total, ended_at }]

POST | /api/dev/seed | { user_id, amount } | только lab — начислить mock-баланс

В exchange пути станут /api/user/battle/* + JWT; тела и response — те же.

Wallet abstraction (важно для переноса)

# wallet.py — lab
class WalletProvider(Protocol):
    async def available(self, user_id: str) -> float: ...
    async def hold_bet(self, user_id: str, round_id: int, amount: float) -> None: ...
    async def release_win(self, user_id: str, round_id: int, amount: float) -> None: ...
    async def confirm_loss(self, user_id: str, round_id: int) -> None: ...
    async def refund_round(self, user_id: str, round_id: int) -> None: ...

class MockWallet(WalletProvider): ...  # lab

# позже в exchange:
# class ExchangeLedgerWallet(WalletProvider):  # user_cashback_db hold/spend

battle_engine.py не должен знать про SQLite vs PostgreSQL — только WalletProvider.

UI (Battle.tsx)

Крупно: таймер, 🔴 XX% | 🔵 YY%, суммы пулов

Кнопки: [🔴 100] [🔴 500] [🔴 ALL] [🔵 …]

Баланс сверху

Анимация resolve: 3–4 кадра (CSS), потом «+253 ₽» / «−100 ₽»

Mobile-first, тёмная тема

Фоновый scheduler

В main.py on startup: asyncio task каждую 1 сек проверяет ends_at

T-3 сек: lock новых ставок

Resolve → payout → новый round

Тесты (обязательно)

test_split_two_winners_on_red

test_rake_deducted

test_one_side_only_refunds

test_proportional_odds_rng (mock random)

Что НЕ делать в lab

❌ Не подключать exchange_bot PostgreSQL / prod

❌ Не копировать весь exchange/backend

❌ Не Telegram bot handlers

❌ Не real JWT / web_users (пока mock user)

Запуск lab

cd ~/Desktop/focuspay-battle-lab
python3 -m venv backend/.venv && source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn main:app --reload --port 8001

cd frontend && npm i && npm run dev -- --port 5174
# → http://localhost:5174

scripts/start.sh — обёртка над обоим.

Порядок реализации для Cursor

Scaffold + test_battle_engine.py (engine без API)

MockWallet + SQLite

FastAPI routes + scheduler

React UI + polling

Анимация + history

README с примерами curl

Интеграция потом (другой чат / этот проект exchange)

Скопировать battle_engine.py, battle_round.py → exchange/backend/

Реализовать ExchangeLedgerWallet через user_cashback_db hold/spend (как hold на заказ)

routers/battle.py + JWT get_current_user

migrations/add_battle.sql → также tg_bot_btc/migrations/

frontend/src/pages/Battle.tsx — перенести, API base /api/user/battle

BATTLE_ENABLED=false на prod до QA

Бот: опционально ссылка «🎮 Battle» → https://site/cabinet/battle

Референсы в монорепо (read-only, не редактировать из lab)

Баланс: ~/Desktop/exchange/backend/user_unified_balance.py

Hold/spend: ~/Desktop/exchange/backend/user_cashback_db.py

Кабинет: ~/Desktop/exchange/frontend/src/pages/Cabinet.tsx
