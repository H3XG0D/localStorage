# FocusPay Battle Lab

Изолированный прототип 🔴 vs 🔵 для FocusPay. Не подключается к prod PostgreSQL.

## Быстрый старт

```bash
cd ~/Desktop/focuspay-battle-lab
chmod +x scripts/start.sh
./scripts/start.sh
```

Откройте http://localhost:5174 — выберите игрока (alice / bob / carol) в dropdown.

## Ручной запуск

```bash
# Backend :8001
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001

# Frontend :5174
cd frontend && npm i && npm run dev -- --port 5174
```

## API (контракт для exchange)

Все запросы принимают заголовок `X-Lab-User: alice` (в exchange — JWT).

### GET /api/battle/current

```bash
curl -s -H "X-Lab-User: alice" http://localhost:8001/api/battle/current | jq
```

```json
{
  "round_id": 1,
  "seconds_left": 42,
  "red_total": 300,
  "blue_total": 500,
  "red_pct": 37.5,
  "blue_pct": 62.5,
  "bank": 800,
  "status": "open",
  "my_bet": { "side": "red", "amount": 100 },
  "balance_available": 900
}
```

### POST /api/battle/bet

```bash
curl -s -X POST http://localhost:8001/api/battle/bet \
  -H "Content-Type: application/json" \
  -H "X-Lab-User: alice" \
  -d '{"side":"red","amount_rub":100}' | jq
```

### GET /api/battle/history?limit=20

```bash
curl -s http://localhost:8001/api/battle/history?limit=5 | jq
```

### POST /api/dev/seed (только lab)

```bash
curl -s -X POST http://localhost:8001/api/dev/seed \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","amount":5000}' | jq
```

## Тесты

```bash
cd backend && python3 -m pytest tests/ -v
```

## Механика

- Раунд 60 сек, lock за 3 сек до конца
- P(red) = red / (red + blue), rake 5%
- Min ставка 50 ₽, max 5000 ₽ на user за раунд
- Одна сторона без ставок → refund

## Интеграция в exchange

См. `CURSOR.md`. Пути в prod: `/api/user/battle/*` + `ExchangeLedgerWallet`.
