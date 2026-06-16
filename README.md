# TG Platform

CMS для Telegram-каналов с AI-ассистентом.  
Платформа позволяет авторам планировать, создавать и анализировать публикации, вести AI-диалоги в контексте конкретных постов и канала в целом, управлять базой знаний и отслеживать аналитику канала.

**Demo (GitHub Pages, MSW):** https://saltolist.github.io/TG_Platform/ — см. [deploy.md](./docs/dev/deploy.md).

Монорепо: один фронтенд и бэкенд:

- **`frontend/`** — Next.js (FSD). Один код, два контура: демо на GitHub Pages (MSW) и продукт в Docker (реальный API).
- **`backend/`** — бэкенд продукта (FastAPI + PostgreSQL + MinIO).

## Быстрый старт

**Фронтенд (dev, MSW):**

```bash
npm install              # единый install для workspace
npm run dev              # → http://localhost:3020
npm run check            # typecheck + lint + test + build
```

**Весь продукт (Docker):**

```bash
cp .env.example .env     # заполнить секреты
docker compose up --build
# frontend → http://localhost:3000, API → http://localhost:8000/api/v1
bash scripts/verify-phase1-docker.sh   # smoke-проверка Фазы 1
```

## Структура проекта

```
TG_Platform/
├── frontend/            ← Next.js (FSD) — демо (Pages) и продукт (Docker)
│   └── src/
│       ├── app/         ← App Router, провайдеры, глобальные стили
│       ├── screens/     ← страницы (FSD: screen layer)
│       ├── widgets/     ← крупные составные блоки UI
│       ├── features/    ← пользовательские сценарии
│       ├── entities/    ← бизнес-сущности (Post, Channel, Chat…)
│       └── shared/      ← утилиты, UI-kit, хуки, константы
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

