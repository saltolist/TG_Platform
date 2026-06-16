# Деплой / CI/CD

## Сборка

```bash
npm run build
```

Выполняет:
1. `next build` — создаёт оптимизированную продакшн-сборку
2. `node scripts/copy-404.mjs` — копирует кастомную 404-страницу для статического экспорта

Артефакты сборки — в папке `.next/`.

## Переменные окружения для продакшна

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.your-domain.com` | URL продакшн-бэкенда |
| `NEXT_PUBLIC_DATA_SOURCE` | `http` | Использовать реальный API |

> **Важно:** не устанавливайте `NEXT_PUBLIC_DATA_SOURCE=msw` в продакшне — это включит мок API.

## Запуск продакшн-сборки

```bash
npm run start
# → http://localhost:3000
```

## Развёртывание на Vercel (рекомендуется)

1. Подключите репозиторий к [Vercel](https://vercel.com).
2. Установите переменные окружения в настройках проекта.
3. Vercel автоматически запускает `npm run build` при каждом пуше в `main`.

Настройки Vercel:
```json
{
  "framework": "nextjs",
  "buildCommand": "npm run build",
  "outputDirectory": ".next"
}
```

## Развёртывание на VPS / Docker

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV NEXT_PUBLIC_DATA_SOURCE=http
ENV NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
RUN npm ci --only=production
EXPOSE 3000
CMD ["npm", "start"]
```

## CI Pipeline (рекомендуемый)

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: web/package-lock.json
      - working-directory: web
        run: npm ci
      - working-directory: web
        run: npm run check   # typecheck + lint + test + build
```

## MSW Service Worker

В продакшн-режиме MSW не загружается. Public-файл `mockServiceWorker.js` присутствует в сборке, но не активируется при `NEXT_PUBLIC_DATA_SOURCE=http`.

Обновление service worker файла после обновления MSW:
```bash
npx msw init public/
```

← [Назад к документации разработчика](README.md)
