# AGENTS.md — Doliv (P2P Doliv Panel)

Веб-панель учёта операций P2P-долива. Три роли: **трейдер**, **доливщик**, **админ**.

Язык общения — русский. Английский только в коде, командах, путях и идентификаторах.

## Роль этого каталога

Это **канонический baseline**. Песочница для новых фич — `~/Desktop/doliv-lab` (отдельный форк со сдвинутыми портами). Если задача экспериментальная — уточнить, здесь править или в lab.

Проект не под git. Перед крупными правками стоит попросить бэкап.

## Стек

- **Backend:** FastAPI + SQLAlchemy (async) + PostgreSQL 16, Alembic для миграций, python-jose + passlib/bcrypt для авторизации. Работа с файлами: pypdf, Pillow + pillow-heif, openpyxl.
- **Frontend:** React + Vite + TypeScript + Tailwind, TanStack Query, react-router-dom, recharts, lucide-react.
- **Тесты:** backend — pytest + pytest-asyncio + aiosqlite; frontend — vitest + jsdom + msw + testing-library.

Зависимости в `backend/requirements.txt` запинены точными версиями — не поднимать их «заодно».

## Запуск

```bash
docker compose up --build
docker compose exec backend python seed.py     # наполнить тестовыми данными
```

Порты: backend `8000`, frontend `5173`, postgres `5432`. Volumes: `postgres_data`, `upload_data`.

Локально без Docker: venv в `backend/`, `pip install -r requirements.txt`.

## Тесты

```bash
cd backend && pytest
cd frontend && npm run test          # vitest run
cd frontend && npm run build         # tsc -b && vite build, ловит TS-ошибки
```

Перед сдачей задачи прогонять сборку фронта — она отлавливает ошибки типов.

## Связь с FocusPay

FocusPay обращается к Doliv через мост: переменные `DOLIV_BRIDGE_URL` и `DOLIV_BRIDGE_KEY`. Реализация моста — `~/Desktop/exchange/backend/doliv_bridge.py`, потребители — роутеры `operator.py` и `exchanger.py`.

Меняя API Doliv, проверять, не ломается ли контракт моста. Карта экосистемы — `~/.zcode/knowledge/ECOSYSTEM.md`.

## Правила

- Не коммитить, не пушить, не деплоить без явной просьбы.
- Не печатать значения секретов из `.env`. Ключи — по имени.
- Миграции схемы — через Alembic новой ревизией, не правкой применённых.
- Соблюдать стиль окружающего кода.
- `docker compose down -v` уничтожает данные — только с подтверждением.
