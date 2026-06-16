# Фаза 1 — Core API (замена MSW) ✅

**Цель:** фронтенд работает на реальном бэкенде вместо MSW; все три Docker-режима
(презентация / демо / реальный аккаунт) функциональны на реальном Postgres.

См. также: [Режимы работы](../../dev/runtime-modes.md), [ADR-007](../../dev/adr/007-runtime-modes-keys-overlay.md), [endpoints.md](../endpoints.md).

> **Важно:** AI в этой фазе — **заглушка в формате JSON** (`{ "text": "..." }`).
> Реальный LLM и стриминг (SSE) — это [Фаза 2](phase-2-ai.md). Чат-UI не трогаем.

---

## Исходное состояние

Каркас уже существует (Фаза 0):
- Роутеры FastAPI: `auth`, `posts`, `chats`, `notes`, `profile`, `ai` (заглушка).
- Миграция `001_initial` (users, email_codes, posts, global_chats, global_notes, profiles).
- Фронтенд `httpRepositories.ts` уже зовёт все эндпоинты.

Чего нет:
- Гостевого доступа (presentation без входа) на бэкенде.
- Предзаполненных аккаунтов в Postgres (`presentation`, `demo-full`).
- Локального overlay на фронте (правки гостя/демо не должны идти в общую БД).
- Контрактных тестов для posts/chats/notes/profile.

---

## Ключевые решения (зафиксированы)

| Решение | Значение |
|---------|----------|
| Идентификация сид-аккаунтов | **UUID везде** + булев флаг `users.is_seed`. Никакого `account_slug`. |
| Гостевой токен | `presentation:guest` (не JWT), обрабатывается до JWT-декода |
| Доступ гостя | read-only: `GET` разрешён, мутации → `403` |
| AI | JSON-заглушка (SSE откладывается в Фазу 2) |
| Данные демо/презентации | Чтение из Postgres + локальный **overlay** на запись (localStorage) |
| Источник сид-данных | JSON-фикстуры, сгенерированные из TS-сидов фронта (один источник правды) |

---

## Шаги реализации

Порядок учитывает зависимости. Шаги 3 можно частично параллелить с шагом 2.

### Шаг 1 — Identity и доступ (бэкенд) ✅

**Файлы:** `backend/alembic/versions/002_*.py`, `backend/app/db/models.py`,
`backend/app/core/deps.py`, `backend/app/api/v1/auth.py`.

1. Миграция `002`: добавить `users.is_seed BOOLEAN NOT NULL DEFAULT false`.
2. `models.py`: поле `is_seed: Mapped[bool]`.
3. `deps.py` — новая логика разрешения пользователя:
   - заголовок `Authorization: Bearer presentation:guest` → найти пользователя с
     `is_seed = true` и презентационной пометкой (см. сидер) → вернуть с флагом
     `read_only = True`;
   - иначе обычный JWT-флоу (как сейчас);
   - ввести зависимости: `CurrentUser` (любой), `CurrentWriter` (запрещает
     read-only → `403`).
4. Применить `CurrentWriter` ко всем мутациям posts/chats/notes/profile.
5. `auth.py`: логин/регистрация возвращают **UUID** в `accountId` (без изменений
   формата). Демо-логин (`demo@mail.ru`) находит сид-аккаунт `demo-full`.

**Тесты (`backend/tests/test_guest.py`):**
- гостевой токен → `GET /posts/` = 200;
- гостевой токен → `POST /posts/` = 403;
- невалидный токен → 401.

**Критерий шага:** гость читает данные, не может писать; реальный JWT работает как прежде.

---

### Шаг 2 — Сидер аккаунтов ✅

**Файлы:** `frontend/scripts/export-seed-fixtures.mjs`,
`backend/fixtures/*.json`, `backend/app/db/seed.py`, `backend/scripts/entrypoint.sh`.

1. **Экспорт сидов с фронта.** Node-скрипт сериализует существующие TS-сиды
   (`presentation-seed.ts`, `seed-data.ts`, `demo-kanal-content.ts`) в JSON:
   - `backend/fixtures/presentation.json` — posts/chats/notes + profile (как на Pages);
   - `backend/fixtures/demo-full.json` — posts/chats/notes + profile (channel/ai/telegram).
2. **Python-сидер** `seed.py` (идемпотентный, по уникальному email/флагу):
   - `presentation`: пользователь с `is_seed=true`, без пароля для входа,
     презентационная пометка; заливка контента из `presentation.json`;
   - `demo-full`: пользователь `demo@mail.ru` / `Demo!2026`, `is_seed=true`,
     профиль + контент из `demo-full.json`;
   - повторный запуск не создаёт дублей (upsert по email).
3. **entrypoint.sh:** после `alembic upgrade head` выполнить `python -m app.db.seed`.

**Тесты (`backend/tests/test_seed.py`):**
- после сида существуют оба пользователя с `is_seed=true`;
- повторный сид не плодит дубли;
- `GET /posts/` гостем возвращает N постов из фикстуры;
- демо-логин → профиль не пустой.

**Критерий шага:** свежий `docker compose up` → в БД есть презентация и демо с данными.

> **Риск:** маппинг структуры MSW-store (`posts[]`, `globalChats[]`, `globalNotes[]`,
> `profile`) на таблицы. JSON-генерация снижает риск ручного дублирования.

---

### Шаг 3 — API и контрактные тесты ✅

**Файлы:** `backend/app/api/v1/*.py`, `backend/app/schemas/*.py`, `backend/tests/*`.

Роутеры есть — задача проверить соответствие Zod-схемам фронта и закрыть тестами.

| Модуль | Что проверить |
|--------|---------------|
| `auth` | register send-code/verify, forgot-password, `accountId` (UUID) в ответе |
| `posts` | list/create/patch/delete/reorder; trailing slash; JSONB-merge при patch |
| `chats` | create, push message, patch history, rename, delete |
| `notes` | upsert по id (PUT), delete |
| `profile` | get/put channel/ai/telegram; у `presentation` — сид-профиль (channel/ai) |
| `ai` | JSON-заглушка `{ "text": "..." }`, scope global/post |

Каждый модуль — pytest с `httpx.AsyncClient` + Postgres (как в CI). Цель —
**контрактные тесты**, не максимальное покрытие.

**Вероятные баги, которые тут всплывут:**
- PATCH принимает сырой `dict` без валидации — добавить partial-схему;
- reorder молча пропускает неизвестные id;
- расхождение ответа с Zod (поля/даты/вложенные массивы).

**Критерий шага:** все эндпоинты из [endpoints.md](../endpoints.md) проходят
контрактные тесты; ответы валидны против Zod.

---

### Шаг 4 — Фронтенд: переключение на HTTP ✅

**Файлы:** `frontend/src/shared/lib/auth/queryAccountScope.ts`,
`frontend/src/shared/api/httpClient.ts`, `frontend/src/app/providers/AuthProvider.tsx`.

1. **`getQueryAccountIdFromAuth()`** — брать `accountId` из `readSession()`
   (UUID), а не парсить `token.split(":")`. Для гостя (нет сессии) →
   `PRESENTATION_ACCOUNT_ID`.
2. **401-handler** — для гостевого токена **не** делать logout (гость и так без
   сессии). Logout только для реальной истёкшей сессии.
3. Проверить все `apiV1Path(...)` — trailing slash совпадает с бэкендом.
4. **Решить:** новый реальный аккаунт стартует пустым или с онбординг-сидом
   (см. `empty-account-state.ts`). По умолчанию — пустой.

**Критерий шага:** `docker compose up`, `NEXT_PUBLIC_USE_MSW=0` → без входа видны
данные презентации из Postgres; демо-логин открывает демо.

---

### Шаг 5 — Фронтенд: локальный overlay ✅

**Файлы:** `frontend/src/shared/api/overlayRepositories.ts` (новый),
`frontend/src/shared/api/createRepositories.ts`,
`frontend/src/shared/lib/auth/*`.

1. `isOverlayAccount(accountId)` → true для `presentation` и `demo-full`.
2. `createOverlayRepositories(httpRepos)` — декоратор:
   - **read** = merge(ответ API, overlay из localStorage); учитывать удаления и
     частичные patch;
   - **write** = только overlay;
   - ключ хранилища: `tg-overlay:{accountId}`.
3. Подключить в `createRepositories()` при `API_MODE && isOverlayAccount(...)`.
4. Профиль демо в overlay (локальное переключение моделей).
5. Очистка localStorage → возврат к сиду с бэкенда.

**Тесты:**
- overlay переживает перезагрузку;
- удаление сид-сущности отражается в чтении;
- очистка overlay → исходный сид.

**Критерий шага:** правка поста гостем/демо не меняет общую БД; у каждого
посетителя свой набор изменений.

> **Главный риск фазы.** Merge на чтении — источник тонких багов (удаления,
> конфликты id, инвалидация TanStack Query). Закладывать буфер.

---

### Шаг 6 — Сквозная проверка и Docker ✅

**Автоматическая проверка API** (при поднятом `docker compose up`):

```bash
bash scripts/verify-phase1-docker.sh
```

Проверяет: health, посты/модели презентации, `403` на запись гостя, демо-логин, AI-заглушку.

**Чеклист критериев готовности:**

- [x] `NEXT_PUBLIC_USE_MSW=0`, фронт+API в Docker — приложение открывается
- [x] Без входа — презентация с предзаполненными данными из Postgres
- [x] `demo@mail.ru` / `Demo!2026` — демо с профилем и каналом
- [x] Правка поста гостем → в другом браузере сид не изменился (overlay в localStorage)
- [ ] Регистрация нового пользователя → данные в Postgres, overlay не используется *(ручная проверка)*
- [x] AI в чате отвечает заглушкой (JSON)
- [x] `npm run check` (178 тестов) + `pytest` (33 теста) зелёные
- [x] GitHub Pages (MSW) не сломан — контур MSW не менялся

---

## Технические требования (контракт)

- ID — UUID-строки, **генерируются клиентом** и приходят в теле
- Даты — ISO-8601 (UTC)
- JWT Bearer; `401` при невалидном/истёкшем токене (но не для гостевого токена)
- Гостевой токен `presentation:guest` — не JWT, обрабатывается отдельно
- Вложенные `notes[]`/`chats[]`/`comments[]` — в JSONB
- Единый формат ошибок `{ "error": "..." }`
- Мутации для read-only (гость) → `403`

---

## Зависимости шагов

```
Шаг 1 (guest + is_seed) ──→ Шаг 4 (фронт HTTP)
    ↓                           ↓
Шаг 2 (сидер) ────────────→ Шаг 5 (overlay)
    ↓                           ↓
Шаг 3 (API + тесты) ──────→ Шаг 6 (сквозная проверка)
```

Шаг 3 можно параллелить с шагом 2 после готовности шага 1.
Шаг 5 — только после шагов 1, 2 и 4.

---

## Оценка

| Блок | Оценка |
|------|--------|
| Бэкенд (шаги 1–3) | ~5–7 дней |
| Фронтенд (шаги 4–5) | ~3–4 дня |
| Сквозная проверка (шаг 6) | ~1 день |
| **Итого** | **~2–2.5 недели** одному разработчику |

Самые рискованные: **сидер** (шаг 2) и **overlay** (шаг 5).

---

## Критерий завершения фазы

Фронтенд, собранный с `NEXT_PUBLIC_USE_MSW=0` и `NEXT_PUBLIC_API_BASE_URL=<backend>`,
полностью функционален во всех трёх режимах; правки презентации/демо не попадают в
общую БД; CI зелёный; Pages-демо не затронут.

---

← [Назад к Roadmap](../roadmap.md) · [Фаза 2 →](phase-2-ai.md)
