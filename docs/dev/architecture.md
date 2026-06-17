# Архитектура

## Методология: Feature-Sliced Design (FSD)

Проект строго следует [Feature-Sliced Design](https://feature-sliced.design/) — слоистой архитектурной методологии для frontend-приложений.

### Слои (сверху вниз)

```
app        ← глобальные провайдеры, роутер, глобальный стейт
screens    ← страницы / экраны приложения
widgets    ← сложные составные блоки (sidebar, composer, post-workspace)
features   ← изолированные пользовательские действия (delete-chat, rename-note)
entities   ← доменные сущности с UI и моделями (post, chat, message)
shared     ← переиспользуемые утилиты, API, конфиги, типы
```

**Правило зависимостей:** каждый слой может импортировать только из нижележащих. Нарушение этого правила контролируется `eslint-plugin-boundaries`.

### Сегменты внутри слоя

Каждый модуль (слайс) может содержать:
- `ui/` — React-компоненты
- `model/` — хуки, стор, бизнес-логика
- `lib/` — вспомогательные функции
- `api/` — работа с данными (в `shared`)

---

## Управление данными

### Серверный стейт — TanStack Query v5

Все данные из API управляются через `@tanstack/react-query`:
- `useQuery` — получение данных
- `useMutation` — изменения
- Автоматические инвалидация кэша после мутаций

Ключи запросов централизованы в `shared/api/queryKeys.ts`.

### UI-стейт — Zustand v5

Переходные UI-состояния (текущий пост, навигация, composer):
- `navigation-store` — текущий экран / пост
- `post-navigation-store` — активная вкладка поста
- `composer-store` — состояние редактора

---

## Repository Pattern

Доступ к данным абстрагирован через интерфейс `RepositoryBundle`:

```typescript
type RepositoryBundle = {
  posts: PostsRepository;
  chats: ChatsRepository;
  notes: NotesRepository;
  profile: ProfileRepository;
  assistant: AssistantRepository;
};
```

Существует две реализации:
- **`createSeedRepositories()`** — in-memory данные, используется для онбординга и тестирования
- **`createHttpRepositories()`** — реальные HTTP-запросы через `apiRequest`

В dev-режиме (и в Pages-демо) HTTP-запросы перехватываются **MSW**, что позволяет использовать `createHttpRepositories()` и в моке.

Переключение реализации — флаг в `shared/config/dataSource.ts`:
```typescript
export const USE_MSW =
  process.env.NEXT_PUBLIC_USE_MSW === "1" ||
  (process.env.NEXT_PUBLIC_USE_MSW !== "0" && process.env.NODE_ENV === "development");
```

- `NEXT_PUBLIC_USE_MSW=1` — моки (по умолчанию в dev и в Pages-демо)
- `NEXT_PUBLIC_USE_MSW=0` + `NEXT_PUBLIC_API_BASE_URL` — реальный бэкенд (Docker-продукт)

---

## Режимы работы (презентация / демо / реальный)

Один фронтенд обслуживает три режима, определяемых **типом аккаунта**:

- **Презентация** — без входа, гостевой токен → `presentation`-аккаунт; нет профиля.
- **Демо** — вход по демо-кредам → `demo-full`; профиль/канал-имитация, ключи —
  замаскированные ссылки-переменные.
- **Реальный** — обычный пользователь, свои данные и ключи (BYOK).

Ключевые принципы:
- В Docker всё идёт через Postgres; правки презентации/демо — в **локальный overlay**
  (localStorage), в общую БД пишут только реальные аккаунты.
- Реальный AI включается env-ключами провайдеров; резолв ключей и вызов LLM —
  только на бэкенде, реальные ключи не уходят на фронтенд.
- Ответы стримятся (SSE); RAG — по флагу `RAG_ENABLED` и наличию реальной модели.
- Сборка промпта (bundle, rolling summary, ветки) — [Сборка контекста для AI-чатов](ai-context-assembly.md).

Подробнее: [Режимы работы](runtime-modes.md), [ADR-007](adr/007-runtime-modes-keys-overlay.md).

---

## Zod как единый источник типов

Все доменные типы выводятся из Zod-схем:

```typescript
// shared/api/schemas/post.ts
export const postSchema = z.object({ id: z.string(), ... });
export type Post = z.infer<typeof postSchema>;
```

`shared/types/index.ts` только реэкспортирует типы из схем. Дублирования нет.

HTTP-репозиторий парсит каждый ответ через схему:
```typescript
list: () => apiRequest<unknown>(apiV1Path("posts"))
  .then((data) => postsListSchema.parse(data)),
```

---

## Идентификаторы

Все сущности используют `id: string` (UUID-совместимый формат).  
ID генерируются на клиенте через `randomId()` (`crypto.randomUUID()`) до отправки на сервер.  
После получения ответа от сервера клиентский ID замещается серверным.

Подробнее: [ADR-003 — String IDs](adr/003-string-ids-uuid.md)

---

## Даты

Все даты в модели хранятся в формате **ISO-8601** (`2026-04-28T14:22:00.000Z`).  
Для отображения используется хелпер `formatStoredDate(raw)` из `shared/lib/helpers.ts`, который форматирует дату в читаемый вид с учётом UTC.

Подробнее: [ADR-004 — ISO-8601 Dates](adr/004-iso8601-dates.md)

---

## Глобальный обработчик 401

`httpClient.ts` предоставляет `setUnauthorizedHandler(fn)` — колбэк, вызываемый при любом 401-ответе. `AuthProvider` регистрирует в нём `logout()` при монтировании.

Подробнее: [ADR-006 — Global 401 Handler](adr/006-global-401-handler.md)

---

## Навигация

Роутинг построен на **Next.js App Router**.  
Все URL-паттерны описаны в `shared/lib/routes.ts`.  
Синхронизация между URL и UI-стором — `widgets/app-shell/lib/syncRoute.ts`.

Поддерживаемые URL-паттерны:
```
/                     → Home (AI-чат)
/gchat/:chatId        → Глобальный чат
/feed                 → Лента
/feed/:postId         → Пост
/feed/:postId/note/:noteId  → Заметка к посту
/chats                → Все чаты
/notes                → Все заметки
/notes/:noteId        → Глобальная заметка
/analytics            → Аналитика
/profile              → Настройки
```

---

## Контракт на бэкенд-интеграцию

Для подключения реального бэкенда требуется:
1. Реализовать эндпоинты из [backend/endpoints.md](../backend/endpoints.md).
2. Вернуть данные в формате, совместимом с Zod-схемами из `shared/api/schemas/`.
3. Выдавать `401` при истечении сессии.
4. Поддерживать JWT в заголовке `Authorization: Bearer <token>`.

← [Назад к документации разработчика](README.md)
