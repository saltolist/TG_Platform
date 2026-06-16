# Тестирование

## Стек

| Инструмент | Назначение |
|-----------|-----------|
| **Vitest** | Тест-раннер, юнит и интеграционные тесты |
| **@testing-library/react** | Тестирование React-компонентов |
| **@vitest/coverage-v8** | Покрытие кода |
| **Playwright** | E2E-тесты |
| **MSW v2** | Мок API для интеграционных тестов |

## Запуск тестов

```bash
# Все юнит-тесты (однократно)
npm run test

# Режим наблюдения
npm run test:watch

# E2E тесты
npm run test:e2e

# Полная проверка (typecheck + lint + test + build)
npm run check
```

## Структура тестов

Тесты располагаются **рядом с тестируемым кодом** по соглашению `*.test.ts(x)`:

```
src/
├── shared/
│   ├── lib/
│   │   ├── helpers.ts
│   │   ├── lib.test.ts           ← тесты helpers
│   │   ├── feed/
│   │   │   ├── filterPosts.ts
│   │   │   └── filterPosts.test.ts
│   │   └── nav/
│   │       ├── breadcrumbTrails.ts
│   │       └── breadcrumbTrails.test.ts
│   ├── api/
│   │   ├── schemas/
│   │   │   └── schemas.test.ts   ← тесты Zod-схем
│   │   └── seedRepositories.test.ts
│   └── data/
│       ├── presentation-seed.test.ts
│       └── channel-pools/
│           └── demo-kanal-posts.test.ts
├── entities/
│   ├── chat/
│   │   └── lib/chatList.test.ts
│   └── post/
│       └── lib/getCachedPost.test.ts
├── app/
│   └── model/store/
│       ├── navigation-store.test.ts
│       └── post-navigation-store.test.ts
└── widgets/
    ├── app-shell/lib/syncRoute.test.ts
    └── sidebar/lib/sidebarPostRowState.test.ts
```

## Что тестируем

### 1. Чистые функции — обязательно

Все трансформации данных, фильтрация, форматирование, построение моделей:
```typescript
// filterPosts.test.ts — пример
it("должен возвращать только черновики", () => {
  const result = buildFeedPostSections(posts);
  expect(result.drafts).toHaveLength(2);
});
```

### 2. Zod-схемы — обязательно

Валидация корректных и некорректных данных:
```typescript
// schemas.test.ts
it("должен парсить валидный пост", () => {
  expect(() => postSchema.parse(validPost)).not.toThrow();
});

it("должен отклонять числовой id", () => {
  expect(() => postSchema.parse({ ...validPost, id: 123 })).toThrow();
});
```

### 3. Zustand-сторы — обязательно

Состояние и переходы:
```typescript
// navigation-store.test.ts
it("должен обновлять currentPostId", () => {
  const { applyNavigationPatch } = useNavigationStore.getState();
  applyNavigationPatch({ currentPostId: "abc" });
  expect(useNavigationStore.getState().currentPostId).toBe("abc");
});
```

### 4. Seed/mock-данные — обязательно

Гарантируют целостность моковых данных:
```typescript
// seedRepositories.test.ts
it("должен создавать пост и возвращать его", async () => {
  const repo = createSeedRepositories();
  const created = await repo.posts.create(newPost);
  expect(created.id).toBe(newPost.id);
});
```

### 5. Компоненты — по необходимости

Для компонентов со сложной логикой отображения используется `@testing-library/react`.

## Правила написания тестов

1. **Описания на русском** — `it("должен..."` для читаемости.
2. **Arrange / Act / Assert** — чёткое разделение подготовки, действия и проверки.
3. **Никакого `any`** — тесты проходят через TypeScript strict.
4. **Тест на поведение, не на реализацию** — проверяем результат, а не внутренние детали.
5. **Тест падает при регрессии** — добавляй тест для каждого найденного бага.

## Конфигурация Vitest

```typescript
// vitest.config.ts
{
  environment: "jsdom",
  setupFiles: ["src/test/setup.ts"],
  globals: true
}
```

`src/test/setup.ts` подключает `@testing-library/jest-dom` матчеры.

## E2E (Playwright)

E2E-тесты покрывают критические пути:
- Регистрация и вход
- Создание и редактирование поста
- Отправка сообщения в чат
- Создание заметки

Запуск требует запущенного dev-сервера (`npm run dev`).

← [Назад к документации разработчика](README.md)
