# Doliv Lab Sandbox

Isolated copy of doliv for working deposits, tokens, teamleads, and float tracking.

**Do not touch** production `~/Desktop/doliv` or live `~/Desktop/tg_bot_btc`.

## Ports

| Service  | Lab  | Typical prod |
|----------|------|--------------|
| Postgres | 5433 | 5432         |
| API      | 8002 | 8000         |
| Frontend | 5175 | 5173         |

Compose project name: `doliv_lab` (own volumes).

## Up

```bash
cd ~/Desktop/doliv-lab
docker compose up -d --build
# or local backend against lab postgres:
cp .env.lab backend/.env
docker compose up -d postgres
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8002
```

Frontend:

```bash
cd frontend && npm i && npm run dev -- --port 5175
```

## Seed

```bash
cd backend && python seed.py
```

Default users (see `seed.py`): owner / admin / trader / doliv (+ lab teamlead after feature seed).

## Smoke

```bash
curl -s http://localhost:8002/health
# expect {"status":"ok","env":"lab"} or {"status":"ok"}
```

### Manual smoke (after each feature phase)

| # | Who | Check |
|---|-----|--------|
| 1 | admin / admin123 | Set working rate (Настройки → Курс) |
| 2 | trader1 / trader123 | Карты → add card → В работу → hold drops on Депозит |
| 3 | trader1 | Zaliv within max payment |
| 4 | trader1 | Expense / Net on Карты |
| 5 | teamlead1 / teamlead123 | Pause trader (фаза 5+) |
| 6 | trader1 | Send-to-doliv still works |

Seed logins: `owner/owner123`, `admin/admin123`, `teamlead1/teamlead123`, `trader1/trader123`, `merchant1/merchant123`, `doliv1/doliv123`.

Full E2E checklist: [SMOKE.md](./SMOKE.md).

## Tests

```bash
cd backend && pytest -q
```
