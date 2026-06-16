# TG Platform

CMS для Telegram-каналов с AI-ассистентом.  
Платформа позволяет авторам планировать, создавать и анализировать публикации, вести AI-диалоги в контексте конкретных постов и канала в целом, управлять базой знаний и отслеживать аналитику канала.

**Demo (GitHub Pages, MSW):** https://saltolist.github.io/TG_Platform/ — см. [deploy.md](./docs/dev/deploy.md).

## Быстрый старт

```bash
npm install
npm run dev        # http://localhost:3020 (в сети: http://<ваш-LAN-IP>:3020)
npm run check      # typecheck + lint + test + build
```

> В dev-режиме используется MSW (Mock Service Worker) — бэкенд не нужен.

**Preview как на GitHub Pages** (basePath `/TG_Platform`, MSW):

```bash
NEXT_PUBLIC_BASE_PATH=/TG_Platform NEXT_PUBLIC_USE_MSW=1 npm run build
npx serve out -p 3021   # → http://localhost:3021/TG_Platform/
```

## Структура проекта

```
TG_Platform/
├── src/
│   ├── app/          ← Next.js App Router, провайдеры, глобальные стили
│   ├── screens/      ← страницы (FSD: screen layer)
│   ├── widgets/      ← крупные составные блоки UI
│   ├── features/     ← пользовательские сценарии
│   ├── entities/     ← бизнес-сущности (Post, Channel, Chat…)
│   ├── shared/       ← утилиты, UI-kit, хуки, константы
│   └── test/         ← тестовые фикстуры и helpers
├── docs/
│   ├── user/         ← документация для пользователей
│   ├── dev/          ← архитектура, ADR, деплой, тестирование
│   └── backend/      ← API эндпоинты, OpenAPI, roadmap
├── e2e/              ← Playwright smoke-тесты
└── scripts/          ← вспомогательные скрипты сборки
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


