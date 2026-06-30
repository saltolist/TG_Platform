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

### Шаг 1 — MTProto-авторизация ✅ backend реализован

**Эндпоинты:** `POST /api/v1/telegram/auth/{send-code,verify,verify-2fa,reset}/`
(`CurrentWriter` — сид/демо-аккаунты получают 403, как и на `PUT /profile/telegram/`).

**Файлы:**
- `backend/app/services/telegram/mtproto_client.py` — фабрика Telethon `TelegramClient`
  через `StringSession` (модульный импорт класса, чтобы тесты могли подменить его
  через `monkeypatch`).
- `backend/app/services/telegram/auth_flow.py` — `send_code` / `verify_code` /
  `verify_password` / `reset_auth`, свой `TelegramAuthError`.
- `backend/app/api/v1/telegram_auth.py` — роутер, переиспользует
  `mask_telegram_secrets` для ответов (тот же формат, что у `GET/PUT /profile/telegram/`).

**Поток (stateless reconnect через `StringSession`):** каждый HTTP-запрос — новый
процесс/клиент Telethon, поэтому промежуточное состояние между шагами
(`phone_code_hash`, промежуточная `StringSession`, телефон) сохраняется как
**внутренние зашифрованные поля** в `profiles.telegram` — `_pendingSessionString`,
`_pendingPhoneCodeHash`, `_pendingPhone`. Они шифруются тем же `BYOK_ENCRYPTION_KEY`,
что и `apiHash`/`sessionString`, но **никогда** не попадают в ответ клиенту —
`mask_telegram_secrets()` всегда их вырезает (`strip_internal_fields()`).

1. `send-code/` — `apiId`/`apiHash` из профиля (расшифровка) → Telethon
   `send_code_request(phone)` → `authStatus=code-sent`, `authStep=code`.
2. `verify/` — восстановление клиента из `_pendingSessionString`, `sign_in(phone, code,
   phone_code_hash=...)`:
   - успех → `authStatus=authorized`, `authStep=channel`, `sessionString` сохранён,
     internal-поля очищены;
   - неверный код (`PhoneCodeInvalidError`) → 400, состояние не меняется;
   - истёкший код (`PhoneCodeExpiredError`) → 400 + сброс в `idle`/`credentials`;
   - 2FA включена (`SessionPasswordNeededError`) → 200, `authStep=password`
     (та же промежуточная сессия валидна и для пароля).
3. `verify-2fa/` — `sign_in(password=...)` на той же промежуточной сессии → `authorized`.
4. `reset/` — best-effort `log_out()` в Telegram (если есть активная сессия) +
   локальный сброс в `idle`/`credentials`, `sessionString` очищается.

**Таймауты на сетевые вызовы:** все обращения к Telethon (`connect`,
`send_code_request`, `sign_in`, `log_out`) обёрнуты в `asyncio.wait_for`
(`Settings.telegram_rpc_timeout_seconds`, по умолчанию 25 с). Найдено при ручной
проверке: при невалидном/устаревшем `apiId` сервер Telegram иногда не возвращает
чистую `ApiIdInvalidError`, а просто не отвечает (см.
[LonamiWebs/Telethon#1056](https://github.com/LonamiWebs/Telethon/issues/1056)) —
без таймаута это подвешивало бы запрос (и воркер) навечно. При истечении таймаута
возвращается `504` с понятным сообщением. Покрыто тестом
`test_send_code_times_out_instead_of_hanging`.

**Тесты:** `backend/tests/test_telegram_auth.py` — фейковый Telethon-клиент
(`monkeypatch` на `app.services.telegram.mtproto_client`), все ветки выше + 2FA +
регрессия на отсутствие internal-полей в любом JSON-ответе.

**Frontend подключён к реальным эндпоинтам** (`useTelegramBlock.ts` —
`startAuth`/`resendCode`/`confirmCode`/`confirmPassword`/`reset` вызывают
`profile.sendTelegramCode/verifyTelegramCode/verifyTelegram2fa/resetTelegramAuth`
из `ProfileRepository`). 2FA-шаг — отдельный `TelegramPasswordInput`, появляется
когда `authStep === "password"`. Guest/demo overlay-аккаунты и MSW dev-режим
(`shouldPersistLocally()`) продолжают использовать локальную instant-success
симуляцию в `overlayRepositories.ts` — на них реальный Telethon не дёргается
(сид-аккаунты не подключают реальный Telegram), только реальные API-аккаунты идут
в `httpRepositories.ts` → backend.

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
POST /api/v1/telegram/auth/send-code/    ✅ реализован
POST /api/v1/telegram/auth/verify/       ✅ реализован
POST /api/v1/telegram/auth/verify-2fa/   ✅ реализован
POST /api/v1/telegram/auth/reset/        ✅ реализован
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
