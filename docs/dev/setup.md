# Старт проекта

## Требования

- **Node.js** ≥ 20
- **npm** ≥ 10

## Установка и запуск

```bash
# Клонируйте репозиторий и перейдите в папку проекта
cd web

# Установите зависимости
npm install

# Запустите dev-сервер
npm run dev
# → http://localhost:3020
```

В dev-режиме используется **MSW (Mock Service Worker)** — все API-запросы перехватываются и обрабатываются локально. Бэкенд не нужен.

## Переменные окружения

Создайте `.env.local` в корне `web/`:

```env
# URL бэкенда (если не используется MSW)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080

# Источник данных: "msw" | "http"
NEXT_PUBLIC_DATA_SOURCE=msw
```

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8080` | База URL для HTTP-запросов |
| `NEXT_PUBLIC_DATA_SOURCE` | `msw` (по умолчанию) | `msw` — моки, `http` — реальный API |

> При `NEXT_PUBLIC_DATA_SOURCE=msw` переменная `NEXT_PUBLIC_API_BASE_URL` игнорируется.

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

1. Поднимите бэкенд-сервис (см. [backend/roadmap.md](../backend/roadmap.md)).
2. Установите переменные:
   ```env
   NEXT_PUBLIC_DATA_SOURCE=http
   NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com
   ```
3. Перезапустите dev-сервер.

Никакой другой правки фронтенда не требуется — Repository Pattern обеспечивает полную замену источника данных.

## Структура папок

```
web/
├── docs/               ← документация (вы здесь)
├── public/             ← статика, MSW service worker
├── scripts/            ← build-скрипты
├── src/
│   ├── app/            ← Next.js App Router, провайдеры, глобальный стейт
│   ├── entities/       ← доменные сущности (post, chat, message)
│   ├── features/       ← пользовательские действия (delete-chat, rename-note...)
│   ├── screens/        ← экраны/страницы приложения
│   ├── shared/         ← утилиты, API, конфиги, типы
│   ├── test/           ← setup тестов
│   └── widgets/        ← композитные виджеты (sidebar, composer...)
├── package.json
├── tsconfig.json
└── next.config.ts
```

← [Назад к документации разработчика](README.md)
