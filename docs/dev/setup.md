# Старт проекта

## Требования

- **Node.js** ≥ 20
- **npm** ≥ 10

## Установка и запуск (фронтенды, dev)

```bash
# Из корня репозитория — единый install для всех workspaces
npm install

# Продуктовый фронтенд (apps/web)
npm run dev          # → http://localhost:3020

# Презентационный фронтенд (apps/presentation, витрина)
npm run dev:demo     # → http://localhost:3021
```

В dev-режиме используется **MSW (Mock Service Worker)** — все API-запросы перехватываются и обрабатываются локально. Бэкенд не нужен.

> `apps/presentation/` — витрина на MSW (деплой на GitHub Pages).  
> `apps/web/` — продуктовый клиент, подключается к реальному бэкенду в Docker.

## Запуск всего продукта (Docker)

```bash
cp .env.example .env       # заполнить секреты (JWT_SECRET и т.д.)
docker compose up --build
# web → http://localhost:3000, API → http://localhost:8000/api/v1
```

См. [deploy.md](deploy.md) и [backend/roadmap.md](../backend/roadmap.md).

## Переменные окружения (фронтенд)

Создайте `.env.local` в корне:

```env
# Моки в dev (по умолчанию on)
NEXT_PUBLIC_USE_MSW=1

# URL бэкенда (когда MSW выключен)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `NEXT_PUBLIC_USE_MSW` | `1` (по умолчанию в dev) | `1` — моки, `0` — реальный API |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | База URL для HTTP-запросов |

> При `NEXT_PUBLIC_USE_MSW=1` переменная `NEXT_PUBLIC_API_BASE_URL` игнорируется.

## Доступные скрипты

| Команда | Описание |
|---------|----------|
| `npm run dev` | Dev-сервер на порту 3020 |
| `npm run build` | Продакшн-сборка |
| `npm run start` | Запуск продакшн-сборки |
| `npm run typecheck` | Проверка типов TypeScript |
| `npm run lint` | ESLint по всем `.ts` / `.tsx` |
| `npm run test` | Юнит-тесты (Vitest) |
| `npm run test:watch` | Тесты в режиме наблюдения |
| `npm run test:e2e` | E2E-тесты (Playwright) |
| `npm run check` | typecheck + lint + test + build |

## Переключение на реальный бэкенд

1. Поднимите бэкенд-сервис (см. [backend/roadmap.md](../backend/roadmap.md) или `docker compose up`).
2. Установите переменные:
   ```env
   NEXT_PUBLIC_USE_MSW=0
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
   ```
3. Перезапустите dev-сервер.

Никакой другой правки фронтенда не требуется — Repository Pattern обеспечивает полную замену источника данных.

## Структура репозитория

```
TG_Platform/
├── docs/                  ← документация (вы здесь)
├── apps/
│   ├── presentation/      ← витрина (GitHub Pages, MSW)
│   └── web/               ← продуктовый фронтенд (Docker)
│       ├── public/        ← статика, MSW service worker
│       ├── scripts/       ← build-скрипты
│       ├── src/           ← Next.js (FSD)
│       │   ├── app/       ← App Router, провайдеры, глобальный стейт
│       │   ├── entities/  ← доменные сущности (post, chat, message)
│       │   ├── features/  ← пользовательские действия
│       │   ├── screens/   ← экраны/страницы приложения
│       │   ├── shared/    ← утилиты, API, конфиги, типы
│       │   └── widgets/   ← композитные виджеты (sidebar, composer...)
│       ├── next.config.ts
│       └── package.json
├── backend/               ← бэкенд (FastAPI, Postgres, MinIO)
├── docker-compose.yml     ← весь продукт
└── package.json           ← npm workspaces
```

← [Назад к документации разработчика](README.md)
