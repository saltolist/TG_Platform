# TG Platform

CMS для Telegram-каналов с AI-ассистентом.  
Платформа позволяет авторам планировать, создавать и анализировать публикации, вести AI-диалоги в контексте конкретных постов и канала в целом, управлять базой знаний и отслеживать аналитику канала.

**Demo (GitHub Pages, MSW):** https://saltolist.github.io/TG_Platform/ — см. [deploy.md](./docs/dev/deploy.md).

Монорепо из двух фронтендов и бэкенда:

- **`frontends/presentation/`** — презентационный фронтенд (витрина на MSW, деплоится на GitHub Pages).
- **`frontends/product/`** — продуктовый фронтенд (подключается к реальному бэкенду, работает в Docker).
- **`backend/`** — бэкенд продукта (FastAPI + PostgreSQL + MinIO).

## Быстрый старт

**Только фронтенды (dev, MSW):**

```bash
npm install              # единый install для всех workspaces
npm run dev              # продуктовый фронтенд → http://localhost:3020
npm run dev:demo         # презентационный фронтенд → http://localhost:3021
npm run check            # typecheck + lint + test + build во всех workspaces
```

**Весь продукт (Docker):**

```bash
cp .env.example .env     # заполнить секреты
docker compose up --build
# product → http://localhost:3000, API → http://localhost:8000/api/v1
```

## Структура проекта

```
TG_Platform/
├── frontends/
│   ├── presentation/     ← витрина (GitHub Pages, MSW) — Next.js, FSD
│   └── product/          ← продуктовый клиент (Docker) — Next.js, FSD
│       └── src/
│           ├── app/      ← App Router, провайдеры, глобальные стили
│           ├── screens/  ← страницы (FSD: screen layer)
│           ├── widgets/  ← крупные составные блоки UI
│           ├── features/ ← пользовательские сценарии
│           ├── entities/ ← бизнес-сущности (Post, Channel, Chat…)
│           └── shared/   ← утилиты, UI-kit, хуки, константы
├── backend/             ← FastAPI + PostgreSQL + MinIO
├── docs/
│   ├── user/            ← документация для пользователей
│   ├── dev/             ← архитектура, ADR, деплой, тестирование
│   └── backend/         ← API эндпоинты, OpenAPI, roadmap
├── docker-compose.yml   ← весь продукт
└── package.json         ← npm workspaces
```

## Стек


| Категория    | Технология                            |
| ------------ | ------------------------------------- |
| Framework    | Next.js 16 (App Router)               |
| UI           | React 19, Tailwind CSS v4, shadcn v4  |
| Server state | TanStack Query v5                     |
| UI state     | Zustand v5                            |
| Validation   | Zod v4                                |
| Mock API     | MSW v2                                |
| Testing      | Vitest + Testing Library + Playwright |
| Language     | TypeScript 5 (strict)                 |


## Архитектура

Проект следует **Feature-Sliced Design (FSD)**:

```
app → screens → widgets → features → entities → shared
```

Каждый слой зависит только от нижележащих. Подробнее — в [docs/dev/architecture.md](./docs/dev/architecture.md).

## Документация

→ [docs/README.md](./docs/README.md)


| Раздел                           | Что внутри                                                   |
| -------------------------------- | ------------------------------------------------------------ |
| [docs/user/](./docs/user/)       | Онбординг, фичи, FAQ для пользователей                       |
| [docs/dev/](./docs/dev/)         | Старт, архитектура, ADR, API-контракты, тестирование, деплой |
| [docs/backend/](./docs/backend/) | Эндпоинты, OpenAPI, roadmap бэкенда                          |


