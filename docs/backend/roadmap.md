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

**Цель:** фронтенд работает на реальном бэкенде вместо MSW, все три Docker-режима функциональны.

### Приоритет: критический

| Задача | Эндпоинты / компонент | Статус |
|--------|-----------------------|--------|
| Аутентификация | `POST /auth/register`, `/auth/login`, `/auth/logout` | ⏳ |
| CRUD постов | `GET/POST /posts`, `PATCH/DELETE /posts/:id`, `PUT /posts/reorder` | ⏳ |
| CRUD чатов | `GET/POST /global-chats`, `POST /global-chats/:id/messages`, `PATCH/DELETE /global-chats/:id` | ⏳ |
| CRUD заметок | `GET /global-notes`, `PUT/DELETE /global-notes/:id` | ⏳ |
| Профиль | `GET/PUT /profile/{channel,ai,telegram}` | ⏳ |
| AI-заглушка | `POST /ai/reply` (placeholder-ответ в потоковом формате SSE) | ⏳ |
| **Гостевой токен** | `PRESENTATION_GUEST_TOKEN` → маппинг на `presentation`-аккаунт в `deps.py` | ⏳ |
| **Сидер аккаунтов** | Идемпотентный скрипт при старте: создаёт `presentation` и `demo-full` с постами/чатами/заметками/профилем | ⏳ |
| **Локальный overlay (фронтенд)** | Декоратор репозитория: чтения = Postgres + overlay, записи = localStorage (для `presentation` и `demo-full`) | ⏳ |

### Технические требования
- ID — UUID-строки, **генерируются клиентом** и приходят в теле
- Даты — ISO-8601 (UTC)
- JWT Bearer; `401` при невалидном/истёкшем токене
- Вложенные `notes[]`/`chats[]`/`comments[]` хранятся в JSONB
- Единый формат ошибок `{ "error": "..." }`
- Гостевой токен не является валидным JWT — обрабатывается отдельно до JWT-декода

### Критерий готовности
- Фронтенд с `NEXT_PUBLIC_USE_MSW=0` и `NEXT_PUBLIC_API_BASE_URL=<backend>` полностью функционален.
- Без входа открывается презентационный режим с предзаполненными данными.
- Вход `demo@mail.ru` / `Demo!2026` открывает демо-аккаунт с профилем и каналом.
- Правки в презентации/демо не затрагивают общую БД.

---

## Фаза 2 — AI Integration

**Цель:** реальные AI-ответы вместо заглушки; резолв ключей по режиму аккаунта.

### Резолв ключей и модели

- [ ] **Резолв ключа** по порядку: реальный ключ в профиле (BYOK) → ссылка `env:<NAME>` (демо) → env-fallback по `provider` (презентация/демо) → нет ключа (реальный аккаунт — AI не работает; презентация/демо — заглушка)
- [ ] **Предзаполнение моделей демо-аккаунта:** в сидере — ссылки `env:<NAME>` для провайдеров, ключи которых заданы в env; если env-ключей нет — заглушечные модели (паритет с MSW-демо сейчас)
- [ ] Конфиг ключей провайдеров в `core/config.py` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` и др.)
- [ ] **Шифрование ключей at-rest** в Postgres (Fernet/KMS) — для BYOK реальных аккаунтов

### LLM-интеграция

- [ ] Базовый LLM-reply через одну активную модель
- [ ] **Стриминг ответа (SSE)** — `POST /ai/reply/` → `text/event-stream`; правки фронтенда (`AssistantRepository` + чат-UI)
- [ ] Системный промпт из `AiProfileConfig.systemPrompt` + контекст канала (`ChannelProfileConfig`)
- [ ] `scope: "post"` — контекст поста в промпт
- [ ] Web-search модели (Perplexity/Tavily)
- [ ] Multi-response (несколько вариантов от разных моделей)
- [ ] Vision / image-generation модели

### RAG

- [ ] Флаг `RAG_ENABLED` в env; при выключенном флаге retrieval пропускается
- [ ] Миграция Alembic: расширение `pgvector`, таблица эмбеддингов (образ `pgvector/pgvector:pg16`)
- [ ] Индексирование глобальных заметок и заметок постов при upsert
- [ ] Retrieval top-k → добавляется в промпт
- [ ] Активен только при наличии пригодной реальной LLM-модели (env-ключ или BYOK)
- [ ] RAG-orchestrator / ragReasoner (расширенная логика)

### Поток запроса
```
Клиент → POST /ai/reply { text, scope }
  → резолв ключа (BYOK / env:<NAME> / env-fallback / нет)
  → читаем AiProfileConfig (активные модели)
  → читаем ChannelProfileConfig (tone, rules, rubrics)
  → [scope=post] добавляем контекст поста
  → [RAG_ENABLED + модель] retrieval из заметок
  → запрос к LLM (+ web-search если включён)
  → стрим ответа (SSE) → { text }
  → нет ключа + реальный аккаунт → 422 (AI недоступен)
  → нет ключа + презентация/демо → заглушка (SSE-формат)
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

## Критерии готовности к подключению фронтенда (Фаза 1)

- [ ] Все эндпоинты из [endpoints.md](endpoints.md) реализованы (с trailing-slash)
- [ ] Ответы соответствуют схемам ([openapi.md](openapi.md) / [api-contracts.md](../dev/api-contracts.md))
- [ ] `401` при истёкшем токене → фронтенд делает logout
- [ ] ID — строки (UUID), даты — ISO-8601
- [ ] CORS разрешает origin фронтенда
- [ ] Гостевой токен (`PRESENTATION_GUEST_TOKEN`) принимается и маппится на `presentation`-аккаунт
- [ ] Сидер запускается при старте и идемпотентно создаёт `presentation` и `demo-full`
- [ ] Правки гостя/демо блокируются на уровне бэкенда (403); запись — через overlay на фронте

Подробнее о режимах: [docs/dev/runtime-modes.md](../dev/runtime-modes.md)

← [Назад к backend](README.md)
