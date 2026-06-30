# API Эндпоинты

Полный список HTTP-эндпоинтов, которые должен реализовать бэкенд.

**Base URL:** `/api/v1`  
**Auth:** `Authorization: Bearer <jwt>`  
**Content-Type:** `application/json`

---

## Аутентификация

Реальные пользователи: JWT в **httpOnly cookie** `access_token` (см. [security-auth-cookies.md](../dev/security-auth-cookies.md)).  
Гостевой/presentation-режим: `Authorization: Bearer guest:<uuid>`.

Защищённые эндпоинты принимают cookie **или** заголовок `Authorization: Bearer <token>`.

Объект сессии (`AuthSession`), возвращается при успешном входе/регистрации и из `GET /auth/me/`:
```json
{
  "accountId": "uuid",
  "email": "user@example.com",
  "createdAt": "2026-06-16T19:00:00.000Z"
}
```

> Поле `token` в JSON **не возвращается** для реального API — JWT только в httpOnly cookie.

> Если на бэкенде не настроен SMTP, код подтверждения пишется в логи (dev-режим).

### `GET /api/v1/auth/me`
Текущая сессия (cookie или Bearer).

**Response `200`:** `AuthSession`  
**Response `401`:** `{ "error": "Unauthorized" }`

---

### `POST /api/v1/auth/login`
Вход по email и паролю.

**Body:** `{ "email": "user@example.com", "password": "string" }`  
**Response `200`:** `AuthSession` + `Set-Cookie: access_token=...; HttpOnly`  
**Response `401`:** `{ "error": "Неверный email или пароль" }`

---

### `POST /api/v1/auth/logout`
Завершение сессии — удаляет httpOnly cookie.

**Response `204`:** No Content

---

### `POST /api/v1/auth/register/send-code`
Запрос кода подтверждения на email.

**Body:** `{ "email": "user@example.com", "password": "string" }`  
**Response `204`:** No Content  
**Response `400`:** `{ "error": "Пользователь с таким email уже существует" }`

---

### `POST /api/v1/auth/register/verify`
Подтверждение кода и создание пользователя.

**Body:** `{ "email": "user@example.com", "code": "123456" }`  
**Response `200`:** `AuthSession`  
**Response `400`:** `{ "error": "Неверный код" }`

---

### `POST /api/v1/auth/forgot-password/send-code`
Запрос кода для сброса пароля. Возвращает `204` независимо от существования email (не раскрывает наличие пользователя).

**Body:** `{ "email": "user@example.com" }`  
**Response `204`:** No Content

---

### `POST /api/v1/auth/forgot-password/reset`
Сброс пароля по коду.

**Body:** `{ "email": "user@example.com", "code": "123456", "password": "new-password" }`  
**Response `204`:** No Content  
**Response `400`:** `{ "error": "Неверный код" }`

---

## Посты

### `GET /api/v1/posts`
Список всех постов текущего пользователя.

**Response `200`:** `Post[]`

> Посты возвращаются со вложенными `notes[]`, `chats[]` и `comments[]`.

---

### `POST /api/v1/posts`
Создать пост.

**Body:** `Post` (клиент передаёт ID, сгенерированный через `crypto.randomUUID()`)  
**Response `201`:** `Post`

---

### `PATCH /api/v1/posts/:id`
Обновить поля поста.

**Params:** `id: string (UUID)`  
**Body:** `Partial<Post>`  
**Response `200`:** `Post` (полный объект)  
**Response `404`:** `{ "error": "Post not found" }`

---

### `PUT /api/v1/posts/reorder`
Сохранить новый порядок постов (drag-and-drop в черновиках).

**Body:**
```json
{
  "posts": [Post, Post, ...]
}
```
**Response `200`:** `Post[]`

---

### `DELETE /api/v1/posts/:id`
Удалить пост.

**Params:** `id: string (UUID)`  
**Response `204`:** No Content  
**Response `404`:** `{ "error": "Post not found" }`

---

## Глобальные чаты

### `GET /api/v1/global-chats`
Список чатов пользователя.

**Response `200`:** `GlobalChat[]`

---

### `POST /api/v1/global-chats`
Создать чат.

**Body:** `GlobalChat`  
**Response `201`:** `GlobalChat`

---

### `POST /api/v1/global-chats/:chatId/messages`
Добавить сообщение в чат (фронтенд отправляет только пользовательский текст, бэкенд сам обращается к AI и возвращает обновлённый чат).

**Params:** `chatId: string (UUID)`  
**Body:**
```json
{
  "text": "string"
}
```
**Response `200`:** `GlobalChat` (с обновлённой историей)

---

### `PATCH /api/v1/global-chats/:chatId`
Обновить метаданные чата (переименование, изменение preview).

**Params:** `chatId: string (UUID)`  
**Body:** `Partial<GlobalChat>`  
**Response `200`:** `GlobalChat`

---

### `DELETE /api/v1/global-chats/:chatId`
Удалить чат.

**Response `204`:** No Content

---

## Глобальные заметки

### `GET /api/v1/global-notes`
Список заметок пользователя.

**Response `200`:** `GlobalNote[]`

---

### `PUT /api/v1/global-notes/:noteId`
Создать или обновить заметку (upsert).

**Params:** `noteId: string (UUID)`  
**Body:** `GlobalNote`  
**Constraint:** `body.id === params.noteId`  
**Response `200`:** `GlobalNote`

---

### `DELETE /api/v1/global-notes/:noteId`
Удалить заметку.

**Response `204`:** No Content

---

## Профиль

### `GET /api/v1/profile/channel`
Профиль канала пользователя.

**Response `200`:** `ChannelProfileConfig`

---

### `PUT /api/v1/profile/channel`
Обновить профиль канала.

**Body:** `ChannelProfileConfig`  
**Response `200`:** `ChannelProfileConfig`

---

### `GET /api/v1/profile/ai`
AI-настройки пользователя.

**Response `200`:** `AiProfileConfig`

---

### `PUT /api/v1/profile/ai`
Обновить AI-настройки.

**Body:** `AiProfileConfig`  
**Response `200`:** `AiProfileConfig`

---

### `GET /api/v1/profile/telegram`
Telegram-настройки пользователя.

**Response `200`:** `TelegramProfileConfig`

---

### `PUT /api/v1/profile/telegram`
Обновить Telegram-настройки (подключение канала, бота, авторизация).

**Body:** `TelegramProfileConfig`  
**Response `200`:** `TelegramProfileConfig`

> При переходе `channelStatus` с `"idle"` на `"connected"` — импорт истории постов.

---

### `POST /api/v1/telegram/auth/send-code`
Начать (или повторить) MTProto-авторизацию: отправить код подтверждения на телефон
через Telethon. Требует уже сохранённых `apiId`/`apiHash` (`PUT /profile/telegram`).

**Auth:** `CurrentWriter` (сид/демо-аккаунты → `403`).
**Body:** `{ "phone": "+79001234567" }`
**Response `200`:** `TelegramProfileConfig` (`authStatus: "code-sent"`, `authStep: "code"`)
**Errors:** `400` — нет `apiId`/`apiHash`, неверный номер; `429` — `FloodWaitError`.

---

### `POST /api/v1/telegram/auth/verify`
Подтвердить код из Telegram.

**Auth:** `CurrentWriter`
**Body:** `{ "code": "12345" }`
**Response `200`:** `TelegramProfileConfig` — один из:
- `authStatus: "authorized"`, `authStep: "channel"` — успех, `sessionString` сохранён;
- `authStatus: "code-sent"`, `authStep: "password"` — у аккаунта включена 2FA,
  далее вызвать `verify-2fa`.

**Errors:** `400` — неверный или истёкший код (при истёкшем — `authStatus` сбрасывается
в `"idle"`, нужно заново вызвать `send-code`).

---

### `POST /api/v1/telegram/auth/verify-2fa`
Подтвердить облачный пароль (двухфакторная аутентификация Telegram). Вызывается только
после `verify` с ответом `authStep: "password"`.

**Auth:** `CurrentWriter`
**Body:** `{ "password": "string" }`
**Response `200`:** `TelegramProfileConfig` (`authStatus: "authorized"`, `authStep: "channel"`)
**Errors:** `400` — неверный пароль или вызов вне шага `password`.

---

### `POST /api/v1/telegram/auth/reset`
Сбросить MTProto-авторизацию: best-effort выход из текущей Telegram-сессии
(`log_out`) + очистка `sessionString` и состояния на бэкенде.

**Auth:** `CurrentWriter`
**Response `200`:** `TelegramProfileConfig` (`authStatus: "idle"`, `authStep: "credentials"`)

---

### `POST /api/v1/telegram/channel/connect`
Проверить через Telethon, что канал существует и у авторизованного аккаунта есть
права на публикацию (создатель или админ с `post_messages`), затем пометить канал
подключённым. Требует предварительной авторизации (`authStatus` ∈
`{"authorized", "connected"}` и сохранённый `sessionString`).

После успешного connect (если `syncMode != "publish-only"`) в фоне
(`asyncio.create_task`) запускается импорт до **200** последних постов канала
(текст + фото/документы). HTTP-ответ возвращается сразу с
`importStatus: "importing"`. Статус и результат — через поля
`importStatus`, `importError`, `importedPosts`, `lastSync` в
`GET /api/v1/profile/telegram`.

Принимает:
- публичный `@username` / `t.me/username` (в т.ч. у приватного канала с username);
- invite-ссылку `t.me/+…` / `t.me/joinchat/…` — аккаунт должен **уже состоять**
  в канале (автовступление не выполняется);
- числовой peer id `-100…` — канал ищется среди диалогов авторизованного
  аккаунта (`iter_dialogs`), потому что свежий `StringSession`-клиент не
  резолвит голый id без access_hash.

**Auth:** `CurrentWriter` (сид/демо-аккаунты → `403`).
**Body:** `{ "channel": "@mychannel" }` (или invite/id — см. выше)
**Response `200`:** `TelegramProfileConfig` (`channelStatus: "connected"`,
`authStatus: "connected"`, `authStep: "connected"`, заполнены `channelTitle`/`channelId`;
при `syncMode != "publish-only"` — `importStatus: "importing"`, иначе
`importStatus: "idle"`)
**Errors:**
- `400` — пустой ввод, истёкшая/неверная invite-ссылка, ресурс не является каналом;
- `403` — не состоите в канале / нет прав администратора;
- `404` — канал не найден или id отсутствует в ваших диалогах;
- `504` — Telegram не ответил за `TELEGRAM_RPC_TIMEOUT_SECONDS`.

---

### `GET /media/{user_id}/{filename}`
Статическая раздача медиафайлов, скачанных при импорте истории канала
(фото/документы). URL в поле `media[].url` поста — абсолютный
(`MEDIA_PUBLIC_BASE_URL/media/...`). **Auth:** не требуется (публичные URL).

---

### Live-sync (Telegram events)

После импорта истории (Шаг 3) backend поднимает фоновый Telethon-слушатель
(`NewMessage` / `MessageEdited` / `MessageDeleted`) для каналов с
`syncMode != "publish-only"`. Новые и изменённые посты попадают в `posts`
инкрементально; удаления — удаляют соответствующие telegram-посты.

**Статус в `TelegramProfileConfig`:** `syncStatus` (`idle` | `listening` | `error`),
`syncError`, `lastSync` (обновляется при каждом событии). Поле `lastTelegramMessageId`
хранится только на backend (internal, не в API).

**Env (backend):**
- `TELEGRAM_LIVE_SYNC_ENABLED=1` — включить воркер (на secondary-репликах → `0`)
- `TELEGRAM_LIVE_SYNC_REGISTRY_REFRESH_SECONDS=30`
- `TELEGRAM_LIVE_SYNC_RECONNECT_SECONDS=15`
- `TELEGRAM_ALBUM_DEBOUNCE_SECONDS=2`

---

## AI Ассистент

### `POST /api/v1/ai/reply`
Получить ответ AI-ассистента.

**Body:**
```json
{
  "text": "string",
  "scope": "global" | "post"
}
```
**Response `200`:**
```json
{
  "text": "string"
}
```

> `scope: "post"` означает, что запрос привязан к конкретному посту. Контекст канала,
> поста, истории чата и RAG собирается на бэкенде — см.
> [Сборка контекста для AI-чатов](../dev/ai-context-assembly.md).

---

## Формат ошибок

Все ошибки возвращаются в едином формате:

```json
{
  "error": "описание ошибки"
}
```

| Код | Ситуация |
|-----|----------|
| `400` | Невалидное тело запроса |
| `401` | Токен отсутствует, истёк или невалидный |
| `404` | Сущность не найдена |
| `422` | Бизнес-логика: например, id в body ≠ id в path |
| `500` | Внутренняя ошибка сервера |

← [Назад к backend](README.md)
