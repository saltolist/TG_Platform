# API-контракты

Все взаимодействия фронтенда с бэкендом описаны через интерфейсы `RepositoryBundle` и Zod-схемы.

## Базовый URL

```
/api/v1/
```

Конфигурируется через `NEXT_PUBLIC_API_BASE_URL`. Путь `/api/v1` добавляется через `apiV1Path()`.

## Аутентификация

Все защищённые эндпоинты требуют заголовок:
```
Authorization: Bearer <jwt-token>
```

Токен хранится в `sessionStorage` под ключом `api_auth_token`. При получении `401` вызывается глобальный `onUnauthorized()` → logout.

---

## Домены и схемы

### Post

```typescript
// Zod-схема: src/shared/api/schemas/post.ts

type PostStatus = "published" | "scheduled" | "draft"

type Post = {
  id: string                  // UUID
  status: PostStatus
  date?: string               // ISO-8601, дата публикации/планирования
  created?: string            // ISO-8601, дата создания
  rubric: string | null       // ID рубрики из профиля канала
  metrics?: PostMetrics
  text: string
  media?: PostMedia[]
  notes: LocalNote[]          // заметки к посту
  chats: LocalChat[]          // чаты к посту
  comments?: PostComment[]
}

type PostMetrics = {
  views: string
  reposts: number
  reactions: PostReaction[]
}

type PostMedia = {
  name: string
  url: string
  type: string
}

type LocalNote = {
  id: string
  title: string
  date: string               // ISO-8601
  ai: boolean
  body: string
  files?: NoteFile[]
}

type LocalChat = {
  id: string
  title: string
  preview: string
  date: string               // ISO-8601
  history: ChatMessage[]
  ai: boolean
}

type PostComment = {
  id: string
  author: string
  text: string
  date: string               // ISO-8601
  replyToId?: string
  media?: PostMedia[]
}
```

### GlobalChat

```typescript
// Zod-схема: src/shared/api/schemas/chat.ts

type GlobalChatKind = "default" | "omnichannel"

type GlobalChat = {
  id: string
  kind?: GlobalChatKind
  title: string
  preview: string
  date: string               // ISO-8601
  history: ChatMessage[]
}
```

### GlobalNote

```typescript
// Zod-схема: src/shared/api/schemas/note.ts

type GlobalNote = {
  id: string
  title: string
  ai: boolean
  date: string               // ISO-8601
  body: string
  files?: NoteFile[]
}
```

### ChatMessage

```typescript
type ChatMessage = {
  role: "user" | "ai"
  text?: string
  userBranches?: UserMessageBranch[]
  activeUserBranch?: number
  variants?: AiVariant[]
  selectedVariant?: number
  mode?: "single" | "multi"
  targetLabel?: string
  llmLabel?: string
  webLabel?: string
}
```

---

## Эндпоинты

### Posts

| Метод | Путь | Описание | Тело | Ответ |
|-------|------|----------|------|-------|
| `GET` | `/api/v1/posts` | Список постов | — | `Post[]` |
| `POST` | `/api/v1/posts` | Создать пост | `Post` | `Post` (201) |
| `PATCH` | `/api/v1/posts/:id` | Обновить пост | `Partial<Post>` | `Post` |
| `PUT` | `/api/v1/posts/reorder` | Переупорядочить | `{ posts: Post[] }` | `Post[]` |
| `DELETE` | `/api/v1/posts/:id` | Удалить пост | — | `204` |

### Global Chats

| Метод | Путь | Описание | Тело | Ответ |
|-------|------|----------|------|-------|
| `GET` | `/api/v1/global-chats` | Список чатов | — | `GlobalChat[]` |
| `POST` | `/api/v1/global-chats` | Создать чат | `GlobalChat` | `GlobalChat` (201) |
| `POST` | `/api/v1/global-chats/:chatId/messages` | Добавить сообщение | `{ text: string }` | `GlobalChat` |
| `PATCH` | `/api/v1/global-chats/:chatId` | Обновить чат | `Partial<GlobalChat>` | `GlobalChat` |
| `DELETE` | `/api/v1/global-chats/:chatId` | Удалить чат | — | `204` |

### Global Notes

| Метод | Путь | Описание | Тело | Ответ |
|-------|------|----------|------|-------|
| `GET` | `/api/v1/global-notes` | Список заметок | — | `GlobalNote[]` |
| `PUT` | `/api/v1/global-notes/:noteId` | Создать/обновить | `GlobalNote` | `GlobalNote` |
| `DELETE` | `/api/v1/global-notes/:noteId` | Удалить | — | `204` |

### Profile

| Метод | Путь | Описание | Тело | Ответ |
|-------|------|----------|------|-------|
| `GET` | `/api/v1/profile/channel` | Профиль канала | — | `ChannelProfileConfig` |
| `PUT` | `/api/v1/profile/channel` | Обновить профиль | `ChannelProfileConfig` | `ChannelProfileConfig` |
| `GET` | `/api/v1/profile/ai` | AI-настройки | — | `AiProfileConfig` |
| `PUT` | `/api/v1/profile/ai` | Обновить AI | `AiProfileConfig` | `AiProfileConfig` |
| `GET` | `/api/v1/profile/telegram` | Telegram-настройки | — | `TelegramProfileConfig` |
| `PUT` | `/api/v1/profile/telegram` | Обновить Telegram | `TelegramProfileConfig` | `TelegramProfileConfig` |

### AI Assistant

| Метод | Путь | Описание | Тело | Ответ |
|-------|------|----------|------|-------|
| `POST` | `/api/v1/ai/reply` | Получить ответ AI | `{ text: string, scope: "global" \| "post" }` | `{ text: string }` |

### Auth

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/v1/auth/login` | Вход |
| `POST` | `/api/v1/auth/register` | Регистрация |
| `POST` | `/api/v1/auth/logout` | Выход |

---

## Коды ошибок

| Код | Описание | Поведение фронтенда |
|-----|----------|---------------------|
| `400` | Bad Request | Показать ошибку |
| `401` | Unauthorized | Вызов `onUnauthorized()` → logout |
| `404` | Not Found | Показать 404 |
| `500` | Server Error | Показать generic ошибку |

---

## httpClient

Все запросы идут через `shared/api/httpClient.ts → apiRequest()`:

```typescript
apiRequest<T>(path: string, options?: {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
  body?: unknown
  signal?: AbortSignal
}): Promise<T>
```

- Автоматически добавляет `Authorization: Bearer` если токен есть.
- При `401` вызывает зарегистрированный `onUnauthorized`.
- При `204` возвращает `undefined`.

← [Назад к документации разработчика](README.md)
