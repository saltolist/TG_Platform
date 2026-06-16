# Backend Roadmap

## Обзор

Бэкенд реализуется поэтапно. Каждая фаза полностью совместима с уже готовым фронтендом — переключение происходит через переменную `NEXT_PUBLIC_DATA_SOURCE=http`.

---

## Фаза 1 — Core API (MVP)

**Цель:** минимальный рабочий бэкенд, достаточный для замены MSW.

### Приоритет: Критический

| Задача | Эндпоинты | Зависимости |
|--------|-----------|-------------|
| Аутентификация | `POST /auth/login`, `POST /auth/register`, `POST /auth/logout` | JWT, хранилище пользователей |
| CRUD постов | `GET/POST /posts`, `PATCH/DELETE /posts/:id`, `PUT /posts/reorder` | БД постов |
| CRUD чатов | `GET/POST /global-chats`, `POST /global-chats/:id/messages`, `PATCH/DELETE /global-chats/:id` | БД чатов |
| CRUD заметок | `GET /global-notes`, `PUT /global-notes/:id`, `DELETE /global-notes/:id` | БД заметок |
| Профиль | `GET/PUT /profile/channel`, `GET/PUT /profile/ai`, `GET/PUT /profile/telegram` | БД профилей |

### Технические требования Фазы 1

- Все ID — UUID v4 (строки)
- Все даты — ISO-8601 в UTC
- JWT авторизация, Bearer-токен
- `401` при истёкшем/невалидном токене
- Пост хранит `notes[]` и `chats[]` как вложенные объекты (либо отдельные таблицы с join)

---

## Фаза 2 — AI Integration

**Цель:** подключить реальные AI-модели вместо мок-ответов.

### Эндпоинты

```
POST /api/v1/ai/reply
  Body: { text: string, scope: "global" | "post" }
  Response: { text: string }
```

### Задачи

- [ ] Интеграция с OpenAI / Anthropic API (LLM)
- [ ] Интеграция с Perplexity / Tavily (веб-поиск)
- [ ] Поддержка `scope: "post"` — передача контекста поста в промпт
- [ ] Multi-response — несколько вариантов от разных моделей
- [ ] Системный промпт из `AiProfileConfig.systemPrompt`
- [ ] Учёт профиля канала (`ChannelProfileConfig`) в системном промпте

### Поток запроса (Фаза 2)

```
Клиент → POST /ai/reply { text, scope }
  → Сервер читает AiProfileConfig пользователя
  → Сервер читает ChannelProfileConfig (если scope=post, добавляет контекст)
  → Запрос к LLM API
  → Если включён WebSearch → запрос к Search API → добавить в промпт
  → Response { text }
```

---

## Фаза 3 — Telegram Integration

**Цель:** реальная публикация и синхронизация.

### Задачи

- [ ] Авторизация через Telegram API (MTProto / Telethon)
- [ ] Синхронизация истории постов из канала
- [ ] Webhook/polling для новых постов
- [ ] Публикация поста в канал (`POST /posts/:id/publish`)
- [ ] Планировщик публикаций
- [ ] Синхронизация метрик (просмотры, реакции, репосты)
- [ ] Интеграция с Telegram Bot API

### Дополнительные эндпоинты (Фаза 3)

```
POST /api/v1/posts/:id/publish
POST /api/v1/posts/:id/schedule  { scheduledAt: string (ISO-8601) }
GET  /api/v1/analytics/top-posts
GET  /api/v1/analytics/overview
POST /api/v1/telegram/import
```

---

## Фаза 4 — Улучшения и масштабирование

- [ ] Поддержка нескольких каналов (мультиканальность)
- [ ] Омниканальный чат — агрегация всех каналов
- [ ] RAG-индексирование заметок
- [ ] Совместная работа (несколько пользователей на один канал)
- [ ] Медиа-хранилище (S3 / объектное хранилище)
- [ ] Вебхуки для уведомлений

---

## Рекомендуемый стек бэкенда

| Компонент | Варианты |
|-----------|----------|
| Runtime | Python (FastAPI) / Node.js (Fastify) / Go |
| База данных | PostgreSQL (рекомендуется) |
| ORM | SQLAlchemy / Prisma / GORM |
| Очередь задач | Redis + Celery / BullMQ |
| AI | OpenAI SDK / LangChain |
| Хранилище медиа | S3-совместимое (MinIO, AWS S3) |
| Деплой | Docker Compose / Kubernetes |

---

## Критерии готовности бэкенда к подключению

- [ ] Все эндпоинты из [endpoints.md](endpoints.md) реализованы
- [ ] Ответы соответствуют Zod-схемам (см. [api-contracts.md](../dev/api-contracts.md))
- [ ] `401` возвращается при истёкшем токене
- [ ] ID — строки (UUID)
- [ ] Даты — ISO-8601 строки

← [Назад к backend](README.md)
