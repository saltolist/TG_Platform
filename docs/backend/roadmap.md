# Backend Roadmap

## Что такое TG Platform

**TG Platform — это самостоятельный продукт, разворачиваемый через Docker:**

```
┌─────────────────────────── docker-compose ───────────────────────────┐
│  frontend (Next.js server) ──►  backend (FastAPI)  ──►  postgres          │
│                                     │              └► minio (S3)       │
│                                     └────────────►  Telegram / LLM API │
└───────────────────────────────────────────────────────────────────────┘
```

Фронтенд из этого репозитория — **полноценный клиент продукта** (Next.js в server-режиме внутри контейнера).

**GitHub Pages** (https://saltolist.github.io/TG_Platform/) — это **витрина**: тот же фронтенд, собранный как статический экспорт с MSW-моками, без бэкенда.

В **Docker-продукте** три режима работы определяются типом аккаунта. Подробнее — в [docs/dev/runtime-modes.md](../dev/runtime-modes.md).

| Контур / режим | Где | Данные | AI | Назначение |
|----------------|-----|--------|----|------------|
| **GitHub Pages** | Статический экспорт | MSW-моки | Заглушки | Витрина UI |
| **Docker — презентация** | Docker, без входа | Postgres (сид `presentation`) | env-ключи / заглушка | Живое демо без регистрации |
| **Docker — демо-аккаунт** | Docker, `demo@mail.ru` | Postgres (сид `demo-full`) | env-ключи или свой BYOK | Демо с профилем и каналом |
| **Docker — реальный аккаунт** | Docker | Postgres | Ключи из профиля (BYOK) | Рабочая платформа |

---

## Технологические решения

| Компонент | Выбор | Примечание |
|-----------|-------|-----------|
| Backend runtime | **Python + FastAPI** | лучшая экосистема для LLM и Telethon |
| База данных | **PostgreSQL** | вложенные `notes[]`/`chats[]`/`comments[]` в JSONB |
| ORM | **SQLAlchemy 2.0 (async)** | + asyncpg |
| Миграции | **Alembic** | `alembic upgrade head` при старте контейнера |
| Хранилище медиа | **MinIO** (S3-совместимое) | миграция на AWS S3 без изменений кода |
| Аутентификация | **JWT access-токен** | email + пароль, bcrypt; refresh — позже |
| Идентификация аккаунтов | **UUID везде** | сид-аккаунты помечаются флагом `users.is_seed` |
| AI-ключи | **BYOK + env** | профиль (реальные), `env:<NAME>` (демо), env-fallback (презентация) |
| Telegram | **MTProto (Telethon)** | полный импорт истории + публикация + метрики |
| Фронтенд в Docker | **Next.js server (standalone)** | не статический экспорт |
| Оркестрация | **Docker Compose** | Kubernetes — на масштабировании |

### Изоляция данных
Мультипользовательский режим: каждая сущность принадлежит `user_id`, все запросы фильтруются по текущему пользователю из JWT. Сид-аккаунты (`presentation`, `demo-full`) помечены `is_seed=true`; их правки не пишутся в общую БД, а живут в локальном overlay на фронте.

### Совместимость с контрактами
Бэкенд обязан строго соответствовать:
- [endpoints.md](endpoints.md) — список эндпоинтов
- [openapi.md](openapi.md) — схемы
- [../dev/api-contracts.md](../dev/api-contracts.md) — Zod-схемы фронтенда

**Важно:** фронтенд использует `trailingSlash: true` — все пути приходят со слешем на конце (`/api/v1/posts/`, `/api/v1/posts/{id}/`). Бэкенд должен отвечать на такие пути без редиректов.

---

## Фазы

Каждая фаза описана в отдельном подробном файле в [phases/](phases/).

| Фаза | Статус | Описание |
|------|--------|----------|
| [Фаза 0 — Инфраструктура](phases/phase-0-foundation.md) | ✅ Завершено | Запускаемый каркас: Docker, FastAPI, миграции, CI |
| [Фаза 1 — Core API (замена MSW)](phases/phase-1-core-api.md) | ✅ Завершено | Реальный бэкенд вместо MSW; три Docker-режима, сидер, overlay |
| [Фаза 2 — AI Integration](phases/phase-2-ai.md) | ◄ **Текущий фокус** | Реальный LLM, резолв ключей, стриминг (SSE), RAG; [сборка контекста](../dev/ai-context-assembly.md) |
| [Фаза 3 — Telegram Integration](phases/phase-3-telegram.md) | ⏳ План | MTProto: импорт, публикация, метрики |
| [Фаза 4 — Масштабирование](phases/phase-4-scaling.md) | ⏳ План | Refresh-токены, мультиканальность, очереди, K8s |

---

## Текущий фокус: Фаза 2

**Цель:** реальный LLM, резолв ключей, стриминг (SSE). Подробнее —
[phases/phase-2-ai.md](phases/phase-2-ai.md); сборка промпта —
[ai-context-assembly.md](../dev/ai-context-assembly.md).

Фаза 1 завершена: фронтенд в Docker работает на реальном API, сид-аккаунты в Postgres, overlay для гостя/демо. Smoke-проверка: `bash scripts/verify-phase1-docker.sh`.

### Итог Фазы 1

- [x] Все эндпоинты из [endpoints.md](endpoints.md) реализованы (с trailing-slash)
- [x] Ответы соответствуют схемам ([openapi.md](openapi.md) / [api-contracts.md](../dev/api-contracts.md))
- [x] `401` при истёкшем токене → logout (но не для гостевого токена)
- [x] ID — строки (UUID), даты — ISO-8601
- [x] CORS разрешает origin фронтенда
- [x] Гостевой токен (`presentation:guest`) принимается и маппится на `presentation`-аккаунт
- [x] Сидер запускается при старте и идемпотентно создаёт `presentation` и `demo-full`
- [x] Правки гостя/демо блокируются на уровне бэкенда (403); запись — через overlay на фронте

---

## Структура бэкенда

```
backend/
├── app/
│   ├── main.py            ← FastAPI, CORS, lifespan, роутеры
│   ├── core/              ← config, security (JWT/bcrypt), deps
│   ├── db/                ← engine, session, ORM-модели, seed (Фаза 1)
│   ├── schemas/           ← Pydantic-схемы (зеркало Zod фронтенда)
│   ├── api/v1/            ← роутеры: auth, posts, chats, notes, profile, ai
│   └── services/          ← бизнес-логика (ai, telegram — позже)
├── fixtures/              ← JSON-сиды presentation / demo-full (Фаза 1)
├── tests/
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

← [Назад к backend](README.md)
