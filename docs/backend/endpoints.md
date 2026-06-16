# API Эндпоинты

Полный список HTTP-эндпоинтов, которые должен реализовать бэкенд.

**Base URL:** `/api/v1`  
**Auth:** `Authorization: Bearer <jwt>`  
**Content-Type:** `application/json`

---

## Аутентификация

### `POST /api/v1/auth/register`
Регистрация нового пользователя.

**Body:**
```json
{
  "email": "user@example.com",
  "password": "string"
}
```
**Response `200`:**
```json
{
  "token": "jwt-string",
  "userId": "uuid"
}
```

---

### `POST /api/v1/auth/login`
Вход по email и паролю.

**Body:**
```json
{
  "email": "user@example.com",
  "password": "string"
}
```
**Response `200`:**
```json
{
  "token": "jwt-string",
  "userId": "uuid"
}
```

---

### `POST /api/v1/auth/logout`
Инвалидация токена.

**Response `204`:** No Content

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

> `scope: "post"` означает, что запрос привязан к конкретному посту. Бэкенд может использовать это для добавления контекста канала/рубрики в промпт.

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
