# Деплой / CI/CD

Два контура развёртывания — **один фронтенд**, разные env при сборке:

| Контур | Сборка | Куда | Данные |
|--------|--------|------|--------|
| **Демо** | `npm run build:demo` | GitHub Pages | MSW-моки |
| **Продукт** | `npm run build` (в Docker) | Docker (VPS / self-host) | реальный backend |

---

## Демо → GitHub Pages

**Live:** https://saltolist.github.io/TG_Platform/

Деплой автоматический: при пуше в `main` workflow [`.github/workflows/deploy-pages.yml`](../../.github/workflows/deploy-pages.yml) собирает `frontend/` как статический экспорт и публикует `frontend/out`.

### Настройка (один раз)

1. GitHub → **Settings → Pages → Build and deployment**
2. **Source:** GitHub Actions

### Переменные сборки демо

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `GITHUB_PAGES` | `true` | Включает `output: "export"` в `next.config.ts` |
| `NEXT_PUBLIC_BASE_PATH` | `/TG_Platform` | Base path project site (имя репозитория) |
| `NEXT_PUBLIC_USE_MSW` | `1` | Мок API без бэкенда |

### Локальный preview как на Pages

```bash
npm run build:demo
npx serve frontend/out -p 3022   # → http://localhost:3022/TG_Platform/
```

> Без `GITHUB_PAGES=true` production-сборка использует `output: "standalone"` (Docker), а не статический экспорт.

---

## Продукт → Docker

Весь продукт поднимается одним `docker compose`:

```bash
cp .env.example .env       # секреты: JWT_SECRET, пароли БД и т.д.
docker compose up --build
# frontend → http://localhost:3000, API → http://localhost:8000/api/v1
```

Сервисы: `postgres`, `minio`, `backend` (FastAPI), `frontend` (Next.js standalone). См. [`docker-compose.yml`](../../docker-compose.yml).

### Переменные окружения продукта

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `NEXT_PUBLIC_USE_MSW` | `0` | Реальный API вместо моков |
| `NEXT_PUBLIC_API_BASE_URL` | напр. `http://localhost:8000` | Browser-reachable URL бэкенда (build-time) |
| `JWT_SECRET` | секрет | Подпись JWT (backend) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Подключение к Postgres |

> **Важно:** `NEXT_PUBLIC_*` инлайнятся на этапе сборки фронтенда, поэтому `NEXT_PUBLIC_API_BASE_URL` задаётся как build-arg (см. compose).

---

## CI Pipeline

Workflow [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) на push/PR в `main`:

- **frontend:** `npm run check --workspaces --if-present` (typecheck + lint + test + build)
- **backend:** установка зависимостей + `pytest`

## MSW Service Worker

MSW включается через `NEXT_PUBLIC_USE_MSW=1` (демо). В продукте — `0`.

Обновление service worker файла после обновления MSW:

```bash
cd frontend && npx msw init public/
```

← [Назад к документации разработчика](README.md)
