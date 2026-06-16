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

**GitHub Pages** (https://saltolist.github.io/TG_Platform/) — это **витрина/демо**: тот же фронтенд, собранный как статический экспорт с MSW-моками, без бэкенда. Демо служит презентацией возможностей UI.

| Контур | Где | Данные | Назначение |
|--------|-----|--------|------------|
| **Продукт** | Docker (self-host / VPS) | реальный backend + Postgres | рабочая платформа |
| **Демо** | GitHub Pages | MSW-моки в браузере | презентация UI |

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
| AI-ключи | **BYOK** | ключи пользователя в БД (шифрование at-rest — задача фазы 2) |
| Telegram | **MTProto (Telethon)** | полный импорт истории + публикация + метрики |
| Фронтенд в Docker | **Next.js server (standalone)** | не статический экспорт |
| Оркестрация | **Docker Compose** | Kubernetes — на масштабировании |

### Изоляция данных
Мультипользовательский режим: каждая сущность принадлежит `user_id`, все запросы фильтруются по текущему пользователю из JWT.

### Совместимость с контрактами
Бэкенд обязан строго соответствовать:
- [endpoints.md](endpoints.md) — список эндпоинтов
- [openapi.md](openapi.md) — схемы
- [../dev/api-contracts.md](../dev/api-contracts.md) — Zod-схемы фронтенда

**Важно:** фронтенд использует `trailingSlash: true` — все пути приходят со слешем на конце (`/api/v1/posts/`, `/api/v1/posts/{id}/`). Бэкенд должен отвечать на такие пути без редиректов.

---

## Фаза 0 — Инфраструктура (foundation) ✅

**Цель:** запускаемый каркас продукта.

- [x] `docker-compose.yml`: postgres, minio, backend, frontend
- [x] FastAPI-скелет: config, async-БД, JWT, CORS, health-check
- [x] Dockerfile бэкенда и фронтенда (Next.js standalone)
- [x] `next.config.ts`: статический экспорт только для Pages, standalone для Docker
- [x] Alembic-миграции (`alembic upgrade head`, initial schema `001_initial`)
- [x] CI: postgres + migrations + pytest (health, auth, security)

---

## Фаза 1 — Core API (замена MSW) ◄ ТЕКУЩИЙ ФОКУС

**Цель:** фронтенд работает на реальном бэкенде вместо MSW.

### Приоритет: критический

| Задача | Эндпоинты | Статус |
|--------|-----------|--------|
| Аутентификация | `POST /auth/register`, `/auth/login`, `/auth/logout` | ⏳ |
| CRUD постов | `GET/POST /posts`, `PATCH/DELETE /posts/:id`, `PUT /posts/reorder` | ⏳ |
| CRUD чатов | `GET/POST /global-chats`, `POST /global-chats/:id/messages`, `PATCH/DELETE /global-chats/:id` | ⏳ |
| CRUD заметок | `GET /global-notes`, `PUT/DELETE /global-notes/:id` | ⏳ |
| Профиль | `GET/PUT /profile/{channel,ai,telegram}` | ⏳ |
| AI-заглушка | `POST /ai/reply` (placeholder-ответ) | ⏳ |

### Технические требования
- ID — UUID-строки, **генерируются клиентом** и приходят в теле
- Даты — ISO-8601 (UTC)
- JWT Bearer; `401` при невалидном/истёкшем токене
- Вложенные `notes[]`/`chats[]`/`comments[]` хранятся в JSONB
- Единый формат ошибок `{ "error": "..." }`

### Критерий готовности
Фронтенд, собранный с `NEXT_PUBLIC_USE_MSW=0` и `NEXT_PUBLIC_API_BASE_URL=<backend>`, полностью функционален.

---

## Фаза 2 — AI Integration

**Цель:** реальные AI-ответы вместо заглушки.

- [ ] Базовый LLM-reply через одну активную модель (BYOK из `AiProfileConfig.llmModels`)
- [ ] **Стриминг ответа** (SSE) — потребует правок фронтенда
- [ ] Системный промпт из `AiProfileConfig.systemPrompt` + контекст канала (`ChannelProfileConfig`)
- [ ] `scope: "post"` — добавление контекста поста в промпт
- [ ] **Шифрование API-ключей at-rest** (Fernet/KMS)
- [ ] Web-search модели (Perplexity/Tavily)
- [ ] Multi-response (несколько вариантов от разных моделей)
- [ ] Vision / image-generation модели
- [ ] RAG-индексирование заметок (orchestrator / ragReasoner)

### Поток запроса
```
Клиент → POST /ai/reply { text, scope }
  → читаем AiProfileConfig (активные модели, ключи)
  → читаем ChannelProfileConfig (tone, rules, rubrics)
  → [scope=post] добавляем контекст поста
  → запрос к LLM (+ web-search если включён)
  → стрим ответа (SSE) → { text }
```

---

## Фаза 3 — Telegram Integration

**Цель:** реальная публикация и синхронизация канала.

- [ ] Авторизация через MTProto (Telethon): apiId/apiHash/phone/code → session
- [ ] Хранение Telethon-сессии (привязка к `TelegramProfileConfig`)
- [ ] Импорт истории постов канала (`POST /telegram/import`)
- [ ] Публикация поста (`POST /posts/:id/publish`)
- [ ] Планировщик публикаций (`POST /posts/:id/schedule`)
- [ ] Синхронизация метрик (просмотры, реакции, репосты)
- [ ] Опционально: Telegram Bot API для уведомлений

### Дополнительные эндпоинты
```
POST /api/v1/posts/:id/publish
POST /api/v1/posts/:id/schedule  { scheduledAt: ISO-8601 }
POST /api/v1/telegram/import
GET  /api/v1/analytics/overview
GET  /api/v1/analytics/top-posts
```

---

## Фаза 4 — Масштабирование

- [ ] Refresh-токены, опциональный OAuth (Google/GitHub)
- [ ] Мультиканальность (несколько каналов на пользователя)
- [ ] Омниканальный чат — агрегация каналов
- [ ] Совместная работа (несколько пользователей на канал)
- [ ] Очередь задач (Celery/ARQ + Redis) для импорта/публикации/AI
- [ ] Вебхуки для уведомлений
- [ ] Переход на Kubernetes при необходимости

---

## Структура бэкенда

```
backend/
├── app/
│   ├── main.py            ← FastAPI, CORS, lifespan, роутеры
│   ├── core/              ← config, security (JWT/bcrypt), deps
│   ├── db/                ← engine, session, ORM-модели
│   ├── schemas/           ← Pydantic-схемы (зеркало Zod фронтенда)
│   ├── api/v1/            ← роутеры: auth, posts, chats, notes, profile, ai
│   └── services/          ← бизнес-логика (ai, telegram — позже)
├── tests/
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

## Критерии готовности к подключению фронтенда

- [ ] Все эндпоинты из [endpoints.md](endpoints.md) реализованы (с trailing-slash)
- [ ] Ответы соответствуют схемам ([openapi.md](openapi.md) / [api-contracts.md](../dev/api-contracts.md))
- [ ] `401` при истёкшем токене → фронтенд делает logout
- [ ] ID — строки (UUID), даты — ISO-8601
- [ ] CORS разрешает origin фронтенда

← [Назад к backend](README.md)
