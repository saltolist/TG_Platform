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

### Шаг 2 — Подключение канала ✅ backend + frontend реализованы (без импорта истории)

**Эндпоинт:** `POST /api/v1/telegram/channel/connect/` (`CurrentWriter` — сид/демо → `403`).

**Файлы:**
- `backend/app/services/telegram/net.py` — общие хелперы, вынесенные из
  `auth_flow.py` (Шаг 1), чтобы их переиспользовал и канальный flow:
  `TelegramAuthError`, `with_timeout`, `disconnect_safely`,
  `require_api_credentials`, `decrypt_field`. `auth_flow.py` реэкспортирует
  `TelegramAuthError` для обратной совместимости импортов.
- `backend/app/api/v1/_telegram_shared.py` — общая роутинговая обвязка
  (`get_or_create_profile`, `apply_telegram_flow`), вынесенная из
  `telegram_auth.py` и переиспользуемая новым роутером.
- `backend/app/services/telegram/channel_flow.py` — `connect_channel()`:
  нормализация ввода (`@`/`t.me/`/полная ссылка), проверка существования
  канала и прав на публикацию через Telethon.
- `backend/app/api/v1/telegram_channel.py` — роутер.

**Особый случай `@demochannel`** (триальный фид, см. `is_demo_channel_handle()` в
`backend/app/services/demo_channel.py`) обрабатывается на фронтенде **до**
вызова этого эндпоинта и продолжает идти через старый `PUT /profile/telegram/`
(бэкенд уже умеет импортировать демо-посты на этом пути) — реальная
Telethon-проверка нужна только для настоящих каналов.

**Техническое ограничение (v1):** каждый HTTP-запрос пересоздаёт Telethon-клиент
из `StringSession` (см. `mtproto_client.py`), которая не хранит кэш сущностей
между процессами — только auth key. Поэтому:
- **`@username`** (публичный или приватный с username) — резолвится через
  `get_entity`, если аккаунт уже состоит в канале;
- **invite-ссылка** (`t.me/+…`, `t.me/joinchat/…`) — резолвится через
  `get_entity(full_link)`, если аккаунт уже вступил по этой ссылке;
- **числовой `-100…` id** — ищется среди диалогов авторизованного аккаунта
  (`iter_dialogs`), потому что голый id без access_hash на свежем клиенте не
  резолвится. Канал должен быть в списке чатов Telegram этого аккаунта.

Автоматическое вступление по invite-ссылке **не выполняется** — если аккаунт
ещё не в канале, нужно сначала вступить в Telegram-клиенте.

**Поток:**
1. Разбор ввода: `@username` / `t.me/username`, invite-ссылка или `-100…` id.
2. Проверка, что аккаунт авторизован (`authStatus ∈ {authorized, connected}`,
   есть `sessionString`).
3. Резолв сущности:
   - username / invite → `get_entity(...)`;
   - numeric id → поиск среди `iter_dialogs()`;
   - `UsernameNotOccupiedError`/`UsernameInvalidError` → `404` «Канал не найден»;
   - id не найден в диалогах → `404` «Канал не найден среди ваших диалогов…»;
   - `ChannelPrivateError` / `UserNotParticipantError` → `403` с подсказкой
     вступить по invite-ссылке;
   - не похоже на канал → `400`.
4. Проверка прав: сначала атрибуты на entity (для тестов), иначе
   `GetParticipantRequest` → `creator` или `admin_rights.post_messages`.
5. Успех → `channel`, `channelTitle`, `channelId` (peer id `-100…`), `connected`.

**Тесты:** `backend/tests/test_telegram_channel.py` — фейковый `get_entity()`,
сценарии: успех (creator / admin с `post_messages`), `t.me/`-ссылка, канал не
найден, приватный канал, не канал, нет прав, не авторизован, числовой ID
(без сетевого вызова), пустой ввод, сид-аккаунт → `403`.

**Frontend подключён к реальному эндпоинту:** `useTelegramBlock.ts` —
`connectChannel()` разделён на `connectDemoChannel()` (без изменений, локальная
instant-success симуляция + `PUT`, как раньше) и `connectRealChannel()` (вызывает
`profile.connectTelegramChannel(channel)`, ошибки — через `showToast` +
`getApiErrorMessage`, как в `confirmCode`/`confirmPassword`). Новое состояние
`connectingChannel` отображается в `TelegramChannelSection` (дизейблит
инпут/кнопку, меняет текст кнопки на «Проверяем…»). Guest/demo overlay-аккаунты
и MSW dev-режим (`shouldPersistLocally()`) используют локальную симуляцию в
`overlayRepositories.ts`/`msw/handlers.ts` — реальный Telethon не дёргается.

**Явно вне рамок этого шага:** автоматическое вступление в канал по invite-ссылке;
бэкенд-логика для `syncMode` live-sync (остаётся чисто метаданными до отдельной
задачи).

---

### Шаг 3 — Импорт истории ✅

**Запуск:** автоматически в фоне сразу после успешного
`POST /api/v1/telegram/channel/connect/` (если `syncMode != "publish-only"`).
HTTP-ответ connect возвращается мгновенно с `importStatus: "importing"`;
фронт поллит `GET /api/v1/profile/telegram` каждые ~3 с до
`importStatus ∈ {"done", "error"}`.

**Реализация:**
- `backend/app/services/telegram/import_flow.py` — `run_channel_import()`:
  повторный резолв канала через `parse_channel_input` / `resolve_channel_entity`
  из `channel_flow.py`; `iter_messages` с группировкой альбомов (`grouped_id`);
  лимит **200 постов** (служебные сообщения не считаются); общий таймаут
  `telegram_import_timeout_seconds` (600 с).
- `backend/app/services/telegram/media_storage.py` — скачивание фото/документов
  через Telethon на диск (`media_storage_root`), лимит `telegram_import_max_media_mb`
  (20 МБ); раздача через статический mount `/media`.
- **Идемпотентность:** импортированные посты помечаются `data.source = "telegram"`
  (внутренний маркер, не часть `postSchema` на фронте). Повторный импорт удаляет
  только посты с этим маркером; черновики пользователя не трогаются.
- **Статусы в `TelegramProfileConfig`:** `importStatus` (`idle` | `importing` |
  `done` | `error`), `importError`, `importedPosts`, `lastSync`.
- **`syncMode: "publish-only"`** — импорт не запускается (`importStatus: "idle"`).

**Настройки** (`backend/app/core/config.py`):
`media_storage_root`, `media_public_base_url`, `telegram_import_post_limit`,
`telegram_import_max_media_mb`, `telegram_import_timeout_seconds`.

**Frontend:** `useTelegramBlock.ts` — поллинг `importStatus`, toast по завершении,
`refreshPostsAfterChannelImport`; `TelegramChannelSection` — статус импорта,
дизейбл «Подключить канал» при `importing`; `TelegramStatusHeader` — шаг 3
активен при импорте. Seed/overlay/MSW — мгновенный `importStatus: "done"`.

**Известное ограничение v1:** повторное нажатие «Подключить канал» во время
импорта может запустить вторую параллельную задачу (нет блокировки на уровне
процесса); на фронте кнопка дизейблится при `importStatus === "importing"`.

**Явно вне рамок:** комментарии к постам; ручная ресинхронизация; live-sync
новых постов; персистентная очередь задач (используется `asyncio.create_task`).

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
POST /api/v1/telegram/auth/send-code/      ✅ реализован
POST /api/v1/telegram/auth/verify/         ✅ реализован
POST /api/v1/telegram/auth/verify-2fa/     ✅ реализован
POST /api/v1/telegram/auth/reset/          ✅ реализован
POST /api/v1/telegram/channel/connect/     ✅ реализован (+ фоновый импорт истории)
POST /api/v1/media/                        ✅ статическая раздача (mount /media)
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
