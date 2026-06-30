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
