# P2P Doliv Panel

Веб-панель учёта P2P-операций: трейдеры, доливщики, администратор.

## Стек

- **Backend:** FastAPI, SQLAlchemy, PostgreSQL
- **Frontend:** React, Vite, TypeScript, Tailwind CSS
- **Docker Compose** для локальной разработки

## Быстрый старт

### Docker (рекомендуется)

```bash
cd doliv
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

После первого запуска выполните seed:

```bash
docker compose exec backend python seed.py
```

### Локально без Docker

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# PostgreSQL должен быть запущен (см. docker-compose.yml для credentials)
export DATABASE_URL=postgresql+asyncpg://doliv:doliv@localhost:5432/doliv
uvicorn app.main:app --reload
python seed.py
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

## Демо-аккаунты

| Логин    | Пароль     | Роль        |
|----------|------------|-------------|
| admin    | admin123   | Админ       |
| trader1  | trader123  | Трейдер     |
| doliv1   | doliv123   | Доливщик    |

## Функционал

### Трейдер
- Создание реквизитов (сумма, целевой курс)
- Добавление заливов с чеками (сумма, курс, % прибыли)
- Автоматический расчёт остатка и среднего курса
- Отправка на долив

### Доливщик
- Очередь заявок на долив
- Указание суммы, курса, загрузка чека
- Закрытие сделки

### Админ
- Общая статистика и метрики
- Мониторинг всех реквизитов
- Управление пользователями
- Скачивание объединённого PDF чеков
- Экспорт статистики в Excel

## Статусы реквизита

`active` → `in_work` → `awaiting_doliv` → `doliv_in_progress` → `closed` → `archive`

## Структура

```
doliv/
├── backend/     # FastAPI приложение
├── frontend/    # React SPA
├── docker-compose.yml
└── README.md
```
