# ADR-006: Глобальный обработчик 401 в httpClient

## Статус
✅ Принято

## Контекст

При истечении сессии (JWT expire) сервер возвращает `401 Unauthorized`. Без централизованной обработки каждый компонент/хук должен самостоятельно отловить `401` и вызвать logout. Это означало:
- Дублирование обработки в каждом запросе
- Риск "забыть" обработать 401 в новых местах
- Сложность тестирования

## Рассмотренные варианты

- **Обработка в каждом useMutation/useQuery** — много дублирования, ненадёжно
- **React Query `onError` глобально** — привязывает транспортный слой к React Query
- **Axios interceptors** — требует замены `fetch` на axios
- **Callback в httpClient** — минимальный, не привязан к фреймворку

## Решение

`httpClient.ts` предоставляет функцию регистрации колбэка:

```typescript
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export function clearUnauthorizedHandler(): void {
  onUnauthorized = null;
}

// Внутри apiRequest:
if (res.status === 401) {
  onUnauthorized?.();
  throw new ApiError("Unauthorized", 401);
}
```

`AuthProvider` регистрирует обработчик при монтировании:

```typescript
useEffect(() => {
  setUnauthorizedHandler(logout);
  return () => clearUnauthorizedHandler();
}, [logout]);
```

## Последствия

- Единственное место для логики logout при 401
- `httpClient` не зависит от React, Redux, Zustand или любого другого фреймворка
- Легко тестируется: подставить мок-колбэк и проверить вызов
- `clearUnauthorizedHandler()` в cleanup предотвращает вызов после размонтирования

← [К списку ADR](README.md)
