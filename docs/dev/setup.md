# Старт проекта

## Требования

- **Node.js** ≥ 20
- **npm** ≥ 10

## Установка и запуск (фронтенд, dev)

```bash
# Из корня репозитория
npm install

# Dev-сервер с MSW-моками
npm run dev          # → http://localhost:3020
```

В dev-режиме используется **MSW (Mock Service Worker)** — все API-запросы перехватываются и обрабатываются локально. Бэкенд не нужен.

> Один фронтенд (`frontend/`), два контура сборки: демо на GitHub Pages (MSW) и продукт в Docker (реальный API). См. [deploy.md](deploy.md).

## Запуск всего продукта (Docker)

```bash
cp .env.example .env       # заполнить секреты (JWT_SECRET и т.д.)
docker compose up --build
# frontend → http://localhost:3000, API → http://localhost:8000/api/v1
```

См. [deploy.md](deploy.md) и [backend/roadmap.md](../backend/roadmap.md).

## Переменные окружения (фронтенд)

Создайте `.env.local` в `frontend/`:

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
| `NEXT_PUBLIC_BASE_PATH` | пусто / `/TG_Platform` | Base path для GitHub Pages |

> При `NEXT_PUBLIC_USE_MSW=1` переменная `NEXT_PUBLIC_API_BASE_URL` игнорируется.

## Доступные скрипты

| Команда | Описание |
|---------|----------|
| `npm run dev` | Dev-сервер на порту 3020 |
| `npm run build` | Продакшн-сборка (standalone, Docker) |
| `npm run build:demo` | Статический экспорт для GitHub Pages |
| `npm run start` | Запуск продакшн-сборки |
| `npm run typecheck` | Проверка типов TypeScript |
| `npm run lint` | ESLint по всем `.ts` / `.tsx` |
| `npm run test` | Юнит-тесты (Vitest) |
| `npm run test:watch` | Тесты в режиме наблюдения |
| `npm run test:e2e` | E2E-тесты (Playwright) |
| `npm run check` | typecheck + lint + test + build |

## Переключение на реальный бэкенд

1. Поднимите бэкенд-сервис (см. [backend/roadmap.md](../backend/roadmap.md) или `docker compose up`).
2. Установите переменные в `frontend/.env.local`:
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
├── frontend/              ← Next.js (FSD) — демо и продукт
│   ├── public/            ← статика, MSW service worker
│   ├── scripts/           ← build-скрипты
│   ├── src/
│   │   ├── app/           ← App Router, провайдеры, глобальный стейт
│   │   ├── entities/      ← доменные сущности (post, chat, message)
│   │   ├── features/      ← пользовательские действия
│   │   ├── screens/       ← экраны/страницы приложения
│   │   ├── shared/        ← утилиты, API, конфиги, типы
│   │   └── widgets/       ← композитные виджеты (sidebar, composer...)
│   ├── next.config.ts
│   └── package.json
├── backend/               ← бэкенд (FastAPI, Postgres, MinIO)
├── docker-compose.yml     ← весь продукт
└── package.json           ← npm workspaces
```

← [Назад к документации разработчика](README.md)
