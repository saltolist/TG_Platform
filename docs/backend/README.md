# Backend — спецификация и реализация

Документация бэкенда **TG Platform** (FastAPI + PostgreSQL + MinIO).

## Разделы

- [Roadmap](roadmap.md) — фазы, технологические решения, план реализации
- [Эндпоинты](endpoints.md) — полный список API с методами и схемами данных
- [OpenAPI](openapi.md) — OpenAPI 3.1 спецификация

## Архитектура продукта

TG Platform разворачивается через **Docker Compose**:

```
web (Next.js server) → backend (FastAPI) → postgres
                                          → minio (S3)
                                          → Telegram / LLM API
```

Код бэкенда — в папке [`../../backend/`](../../backend/). Запуск всего продукта:

```bash
cp .env.example .env      # заполнить секреты
docker compose up --build
# web → http://localhost:3000, API → http://localhost:8000/api/v1
```

> **GitHub Pages** (https://saltolist.github.io/TG_Platform/) — это демо с MSW-моками, без бэкенда. Подробнее — в [roadmap.md](roadmap.md).

## Совместимость с фронтендом

Фронтенд **полностью готов к подключению бэкенда**:
- Repository Pattern изолирует все запросы
- Zod-схемы описывают ожидаемые форматы данных
- Типы ID — string (UUID), даты — ISO-8601
- `trailingSlash: true` — все пути со слешем на конце

← [Вернуться к главной](../README.md)
