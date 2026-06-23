# Фаза 3 — Telegram Integration

**Цель:** реальная публикация и синхронизация Telegram-канала через MTProto.

См. также: тип `TelegramProfileConfig` в `frontend/src/shared/types/index.ts`,
[профиль Telegram](../endpoints.md).

> Предусловие: [Фаза 1](phase-1-core-api.md) (CRUD, профиль) и желательно
> [Фаза 2](phase-2-ai.md) (AI для генерации постов).

---

## Ключевые решения

| Аспект | Решение |
|--------|---------|
| Протокол | **MTProto** через Telethon (полный доступ: импорт истории, публикация, метрики) |
| Сессия | Telethon-сессия привязана к аккаунту (`TelegramProfileConfig`) |
| Хранение сессии | В БД (зашифровано), не в файловой системе контейнера |
| Бот | Опционально Telegram Bot API для уведомлений |
| Секреты в профиле | `apiHash`, `botApiToken`, `sessionString` — Fernet at-rest (тот же `BYOK_ENCRYPTION_KEY`, что и для AI BYOK) |

> Сид-аккаунты (презентация/демо) **не подключают реальный Telegram** — у них
> данные канала остаются имитацией (overlay). Реальная интеграция — только для
> реальных аккаунтов.

---

## Шаги реализации

### Шаг 0 — Шифрование credentials at-rest ✅ реализовано

**Файлы:**
- `backend/app/services/telegram/byok_telegram.py` — encrypt / mask / reveal
- `backend/app/api/v1/profile.py` — `PUT /profile/telegram/` шифрует, `GET` маскирует
- `POST /profile/telegram/reveal-secret/` — полное значение по полю (`apiHash`, `botApiToken`, `sessionString`)
- `backend/alembic/versions/007_encrypt_profile_secrets_at_rest.py` — миграция данных
- `frontend` — preview в полях, копирование через reveal-on-copy (`TelegramSecretCopyButton`)

**Шифруются:** `apiHash`, `botApiToken`, `sessionString`.

**Не шифруются:** `apiId`, `phone`, `channel`, статусы и метрики (не секреты).

> Общий ключ шифрования: `BYOK_ENCRYPTION_KEY` (см. [Фаза 2, шаг 5](phase-2-ai.md#шаг-5--шифрование-ключей-at-rest--реализовано)).

**Тесты:** `tests/test_byok_telegram_encryption.py`.

---

### Шаг 1 — MTProto-авторизация

**Эндпоинты:** `POST /api/v1/telegram/auth/*`.

1. Поток: `apiId` / `apiHash` / `phone` → запрос кода → `code` → (2FA при наличии)
   → сессия.
2. Состояние авторизации синхронизировать с `TelegramProfileConfig.authStatus`
   (`idle` → `code-sent` → `authorized` → `connected`).
3. Сессия шифруется и сохраняется в БД (привязка к `user_id`) — поле `sessionString`,
   шифрование через `byok_telegram` (шаг 0).

**Тесты:** мок Telethon-клиента; переходы статусов.

---

### Шаг 2 — Подключение канала

1. Указание канала (`channel`, `channelTitle`), проверка прав.
2. `channelStatus`: `idle` → `pending` → `connected`.
3. Выбор режима синхронизации (`syncMode`: `live-only` / `history-and-live` /
   `publish-only`).

---

### Шаг 3 — Импорт истории

**Эндпоинт:** `POST /api/v1/telegram/import`.

1. Импорт постов канала в `posts` (маппинг на доменную модель `Post`).
2. Идемпотентность по внешнему telegram message id.
3. Обновление `importedPosts` и `lastSync`.

---

### Шаг 4 — Публикация и планирование

**Эндпоинты:**
```
POST /api/v1/posts/:id/publish
POST /api/v1/posts/:id/schedule  { scheduledAt: ISO-8601 }
```

1. Публикация поста в канал; обновление статуса поста.
2. Планировщик отложенных публикаций (см. очередь задач — может потребовать
   элементов [Фазы 4](phase-4-scaling.md): Celery/ARQ + Redis).

---

### Шаг 5 — Синхронизация метрик

**Эндпоинты:**
```
GET /api/v1/analytics/overview
GET /api/v1/analytics/top-posts
```

1. Сбор просмотров, реакций, репостов из Telegram.
2. Маппинг на `PostMetrics` / `PostReaction`.
3. Периодическое обновление (фоновая задача).

---

### Шаг 6 — Бот для уведомлений (опционально)

1. Telegram Bot API: токен, `botStatus`, `botUsername`.
2. Уведомления о публикациях/ошибках.

---

## Дополнительные эндпоинты (сводка)

```
POST /api/v1/telegram/auth/send-code
POST /api/v1/telegram/auth/verify
POST /api/v1/telegram/import
POST /api/v1/posts/:id/publish
POST /api/v1/posts/:id/schedule   { scheduledAt: ISO-8601 }
GET  /api/v1/analytics/overview
GET  /api/v1/analytics/top-posts
```

---

## Критерий завершения фазы

- Реальный аккаунт подключает Telegram-канал через MTProto.
- История импортируется; пост публикуется и планируется.
- Метрики канала синхронизируются и отображаются в аналитике.
- Telegram-секреты (`apiHash`, `botApiToken`) зашифрованы в БД; на фронт — preview.

> CSP и продакшен-гигиена (`BYOK_ENCRYPTION_KEY`, KMS, ротация) — см.
> [Фаза 2 — Безопасность, осталось сделать](phase-2-ai.md#безопасность--осталось-сделать).

---

← [Фаза 2](phase-2-ai.md) · [Назад к Roadmap](../roadmap.md) · [Фаза 4 →](phase-4-scaling.md)
