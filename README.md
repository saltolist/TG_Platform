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
./scripts/docker-up.sh --build
# или: docker compose up -d --build
# frontend → http://localhost:3000, API → http://localhost:8000/api/v1
bash scripts/verify-phase1-docker.sh   # smoke-проверка Фазы 1
```

**Данные аккаунтов** хранятся в Docker-томе `tg_platform_postgres-data`.

| Команда | Безопасно для аккаунтов? |
|---------|--------------------------|
| `docker compose up -d --build` | да |
| `docker compose logs -f` → Ctrl+C | да (останавливает только просмотр логов) |
| `docker compose up --build` → Ctrl+C | контейнеры останавливаются, **данные обычно сохраняются** |
| `docker compose stop` | да |
| `docker compose down` | да (без `-v`) |
| `docker compose down -v` | **нет — удаляет базу** |

**Не запускайте** `docker compose up --build` в foreground, если привыкли жать Ctrl+C — используйте `-d` и смотрите логи отдельно:

```bash
docker compose up -d --build
docker compose logs -f backend   # Ctrl+C здесь безопасен
```

Удаляют регистрации также: сброс Docker/Colima (`colima delete`), случайный `down -v`.

**Важно:** `pytest` в `backend/` **не должен** ходить в dev-базу `tg` — после каждого теста conftest удаляет всех пользователей. Используйте отдельную БД `tg_test`:

```bash
./scripts/ensure-test-db.sh   # один раз (создаёт tg_test + миграции)
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://tg:tg@localhost:5432/tg_test pytest -v
```

`./scripts/docker-up.sh` пробует создать `tg_test` автоматически.

Регистрируйтесь и входите через **http://localhost:3000** (Docker).  
`npm run dev` (порт 3020) использует MSW — это отдельная «песочница», аккаунты оттуда не попадают в PostgreSQL.

Код регистрации в dev без SMTP: **`000000`** (смотрите логи backend: `[DEV] email code`).

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

