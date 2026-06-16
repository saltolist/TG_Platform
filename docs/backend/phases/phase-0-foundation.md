# Фаза 0 — Инфраструктура (foundation) ✅

**Цель:** запускаемый каркас продукта.

Статус: **завершено**.

---

## Сделано

- [x] `docker-compose.yml`: postgres, minio, backend, frontend
- [x] FastAPI-скелет: config, async-БД, JWT, CORS, health-check
- [x] Dockerfile бэкенда и фронтенда (Next.js standalone)
- [x] `next.config.ts`: статический экспорт только для Pages, standalone для Docker
- [x] Alembic-миграции (`alembic upgrade head`, initial schema `001_initial`)
- [x] CI: postgres + migrations + pytest (health, auth, security)

---

## Артефакты

| Компонент | Где |
|-----------|-----|
| Оркестрация | `docker-compose.yml` |
| Точка входа API | `backend/app/main.py` |
| Конфиг | `backend/app/core/config.py` |
| Модели БД | `backend/app/db/models.py` |
| Первая миграция | `backend/alembic/versions/001_initial.py` |
| Роутеры (скелет) | `backend/app/api/v1/{auth,posts,chats,notes,profile,ai}.py` |
| Запуск контейнера | `backend/scripts/entrypoint.sh` |
| CI | `.github/workflows/ci.yml` |

---

## Что осталось каркасом (дорабатывается в Фазе 1)

- Роутеры реализованы, но почти без тестов (кроме auth/health/security).
- Нет гостевого доступа, сидера аккаунтов, overlay — это [Фаза 1](phase-1-core-api.md).

---

← [Назад к Roadmap](../roadmap.md) · [Фаза 1 →](phase-1-core-api.md)
