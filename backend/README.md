# TG Platform — Backend

FastAPI + PostgreSQL + MinIO. Реализует API для продуктового фронтенда (`apps/web`).

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
pip install -r requirements.txt
cp .env.example .env          # укажите DATABASE_URL до запущенного Postgres
uvicorn app.main:app --reload --port 8000
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
