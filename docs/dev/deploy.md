# Деплой / CI/CD

## GitHub Pages (демо)

**Live:** https://saltolist.github.io/TG_Platform/

Деплой автоматический: при пуше в `main` workflow [`.github/workflows/deploy-pages.yml`](../../.github/workflows/deploy-pages.yml) собирает статический экспорт и публикует папку `out/`.

### Настройка (один раз)

1. GitHub → **Settings → Pages → Build and deployment**
2. **Source:** GitHub Actions

После первого успешного workflow сайт доступен по ссылке выше.

### Переменные сборки для Pages

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `NEXT_PUBLIC_BASE_PATH` | `/TG_Platform` | Base path project site (имя репозитория) |
| `NEXT_PUBLIC_USE_MSW` | `1` | Мок API без бэкенда |

### Локальный preview как на Pages

```bash
NEXT_PUBLIC_BASE_PATH=/TG_Platform NEXT_PUBLIC_USE_MSW=1 npm run build
npx serve out -p 3021   # → http://localhost:3021/TG_Platform/
```

---

## Сборка

```bash
npm run build
```

Выполняет:
1. `next build` — статический экспорт в `out/` (в production)
2. `node scripts/copy-404.mjs` — копирует `index.html` → `404.html` для SPA-роутинга на GitHub Pages

## Переменные окружения для продакшна

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.your-domain.com` | URL продакшн-бэкенда |
| `NEXT_PUBLIC_USE_MSW` | `0` | Отключить моки, использовать реальный API |
| `NEXT_PUBLIC_BASE_PATH` | `/TG_Platform` или пусто | Base path для GitHub Pages / корневого домена |

> **Важно:** не устанавливайте `NEXT_PUBLIC_USE_MSW=1` в продакшне с реальным API — это включит мок.

## Развёртывание на Vercel

1. Подключите репозиторий к [Vercel](https://vercel.com).
2. Установите переменные окружения в настройках проекта.
3. Vercel автоматически запускает `npm run build` при каждом пуше в `main`.

> Для Vercel не задавайте `NEXT_PUBLIC_BASE_PATH` (или оставьте пустым).

## Развёртывание на VPS / Docker

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV NEXT_PUBLIC_USE_MSW=0
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

## CI Pipeline

Workflow [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) запускается на push/PR в `main`:

```bash
npm run check   # typecheck + lint + test + build
```

## MSW Service Worker

MSW включается через `NEXT_PUBLIC_USE_MSW=1` (используется на GitHub Pages demo).  
В продакшне с реальным API установите `NEXT_PUBLIC_USE_MSW=0`.

Обновление service worker файла после обновления MSW:

```bash
npx msw init public/
```

← [Назад к документации разработчика](README.md)
