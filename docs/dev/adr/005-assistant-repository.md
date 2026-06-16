# ADR-005: AssistantRepository для изоляции AI-логики

## Статус
✅ Принято

## Контекст

Логика получения AI-ответов находилась непосредственно в `composer-store.tsx`:
- Прямые вызовы функций `getGlobalReply()` / `getPostReply()` из `replies.ts`
- `window.setTimeout` с задержками для имитации "думающего" AI
- Невозможность заменить мок-реализацию на HTTP без изменения кода стора

```typescript
// Было в composer-store.tsx
window.setTimeout(() => {
  const replyText = getGlobalReply(text);
  // ... создание сообщения
}, 900);
```

Это нарушало принцип Repository Pattern и делало слой данных нетестируемым в изоляции.

## Рассмотренные варианты

- **Оставить логику в сторе** — просто, но несовместимо с реальным API
- **Вынести в отдельный сервис** — добавляет ещё один слой абстракции
- **Добавить в RepositoryBundle как AssistantRepository** — согласованно с остальными репозиториями

## Решение

Добавлен `AssistantRepository` в `RepositoryBundle`:

```typescript
interface AssistantRepository {
  getGlobalChatReply(text: string): Promise<string>;
  getPostChatReply(text: string): Promise<string>;
}
```

Реализации:
- **`seedRepositories`** — вызывает `getGlobalReply(text)` / `getPostReply(text)` из `assistantReplies.ts`
- **`httpRepositories`** — `POST /api/v1/ai/reply` с полем `scope: "global" | "post"`

`setTimeout` перенесён в MSW-handler (`handlers.ts`), который имитирует сетевую задержку в 300мс — это единственное место, где задержка оправдана.

`replies.ts` удалён, его содержимое перемещено в `shared/api/assistantReplies.ts`.

## Последствия

- `composer-store` полностью декуплен от источника AI-ответов
- Переключение на реальный AI API — без изменения кода стора
- MSW-задержка реалистична и изолирована в слое мока
- `assistantReplies.ts` тестируется независимо

← [К списку ADR](README.md)
