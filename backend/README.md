# TG Platform — Backend

FastAPI + PostgreSQL + MinIO. Реализует API для фронтенда (`frontend/`).

## Стек

- **FastAPI** (async), **SQLAlchemy 2.0** (async, asyncpg)
- **PostgreSQL** — данные (вложенные объекты в JSONB)
- **JWT** (access-токен), пароли — bcrypt
- **MinIO/S3** — медиа (с Фазы 2)

## Запуск через docker-compose (рекомендуется)

Из корня репозитория:

```bash
cp .env.example .env
docker compose up --build
# API → http://localhost:8000/api/v1   (Swagger UI → http://localhost:8000/docs)
```

## Локальный запуск (без Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # укажите DATABASE_URL до запущенного Postgres
alembic upgrade head          # применить миграции
uvicorn app.main:app --reload --port 8000
```

## Миграции (Alembic)

```bash
cd backend
alembic upgrade head              # применить все миграции
alembic revision --autogenerate -m "описание"   # новая миграция после изменения models.py
alembic downgrade -1              # откат на одну миграцию
```

В Docker миграции применяются автоматически через `scripts/entrypoint.sh` перед стартом uvicorn.

## Тесты

Тесты используют **отдельную** базу `tg_test`, не dev-базу `tg` (иначе pytest удалит ваши регистрации).

```bash
# из корня репозитория, при запущенном docker compose
./scripts/ensure-test-db.sh

cd backend
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://tg:tg@localhost:5432/tg_test pytest -v
```

## Структура

```
app/
├── main.py            FastAPI, CORS, lifespan, обработчики ошибок
├── core/              config, security (JWT/bcrypt), deps (auth)
├── db/                engine/session, ORM-модели
├── schemas/           Pydantic-схемы (зеркало Zod фронтенда)
├── api/v1/            роутеры: auth, posts, chats, notes, profile, ai
└── services/          email (коды), ai (заглушка Фазы 1)
```

## Соответствие контракту

- Все пути — со слешем на конце (`trailingSlash: true` во фронтенде).
- Ошибки — в формате `{ "error": "..." }`.
- `401` при невалидном/просроченном токене.
- ID — UUID-строки (генерируются клиентом), даты — ISO-8601.

Подробности: [../docs/backend/](../docs/backend/).

## Дев-режим кодов подтверждения

Если `SMTP_HOST` пуст, коды регистрации/восстановления **пишутся в логи бэкенда**
(`[DEV] email code for ...`). Для прод-режима задайте SMTP-переменные в `.env`.
