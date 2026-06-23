# Фаза 2 — AI Integration

**Цель:** реальные AI-ответы вместо заглушки; резолв ключей по режиму аккаунта;
стриминг (SSE); опциональный RAG.

См. также: [Сборка контекста для AI-чатов](../../dev/ai-context-assembly.md),
[Режимы работы](../../dev/runtime-modes.md), [ADR-007](../../dev/adr/007-runtime-modes-keys-overlay.md),
[ADR-005 — AssistantRepository](../../dev/adr/005-assistant-repository.md).

> Предусловие: [Фаза 1](phase-1-core-api.md) завершена — есть сид-аккаунты,
> профиль с моделями, рабочий `POST /ai/reply/` (пока заглушка JSON).

---

## Ключевые решения (зафиксированы)

| Аспект | Решение |
|--------|---------|
| Источник ключа | BYOK (профиль) → `env:<NAME>` (демо) → env-fallback (презентация) → нет |
| Без ключа | Презентация/демо → заглушка; реальный аккаунт → AI **не работает** (без заглушки) |
| Предзаполнение моделей демо | По env-ключам провайдеров; если ключей нет — заглушечные модели |
| Стриминг | SSE (`text/event-stream`); меняет контракт `AssistantRepository` и чат-UI |
| RAG | По флагу `RAG_ENABLED` + наличие пригодной реальной модели |
| Безопасность ключей | Реальные ключи не уходят на фронт; BYOK шифруется at-rest |
| LLM-провайдеры (шаг 3) | **OpenAI** и **DeepSeek** — оба через OpenAI-compatible `chat/completions`; остальные (Anthropic, Perplexity, …) — шаг 6 |
| Презентация, модели в композере | Без LLM env — фиксированный stub; с LLM env — 2 топовые × провайдер; web — только при web env, иначе «Нет» |

---

## Шаги реализации

### Шаг 1 — Конфиг и резолв ключей

**Файлы:** `backend/app/core/config.py`, `backend/app/services/ai/keys.py` (новый).

1. В `config.py` добавить env-ключи провайдеров (пустые по умолчанию). На шаге 3
   обязательны: `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`; остальные (`ANTHROPIC_API_KEY`,
   …) — по мере подключения в шаге 6.
2. Сервис резолва ключа для активной модели по порядку:
   1. **реальный ключ в профиле** (BYOK — реальный аккаунт или введённый демо-юзером) → как есть;
   2. **ссылка `env:<NAME>`** (демо) → значение из env;
   3. **пусто + презентация/демо** → fallback на env-ключ по полю `provider`
      (`OpenAI` → `OPENAI_API_KEY`, `DeepSeek` → `DEEPSEEK_API_KEY`, …);
   4. **ничего**: презентация/демо → режим заглушки; реальный аккаунт → AI недоступен.
3. Резолв и вызов LLM — целиком на бэкенде; реальные ключи наружу не отдаются.

**Тесты:** все четыре ветки резолва (real / ref-env / env-fallback / none) для
каждого типа аккаунта.

---

### Шаг 2 — Предзаполнение моделей в сидере (демо и презентация)

**Файлы:** `backend/app/db/seed.py`, `backend/app/services/ai/model_catalog.py` (новый),
`backend/fixtures/demo-full.json`, `backend/fixtures/presentation.json` (stub fallback).

#### Аккаунт `demo-full`

1. При сиде заполнять `AiProfileConfig.llmModels` ссылками `env:<NAME>` для провайдеров
   с ключами в env (как минимум OpenAI и DeepSeek).
2. `webSearchModels` — только для web-провайдеров с ключами в env (при наличии LLM-ключа);
   без web-ключей — пустой список (в композере «Нет»).
3. Если в env нет ни одного LLM-ключа — заглушечные LLM-модели (паритет с MSW-демо),
   web-поиск — пустой.
4. Идемпотентность: повторный сид обновляет модели согласно текущему env.

#### Аккаунт `presentation` (отдельные правила)

Сидер пересобирает AI-профиль по env; детали — в
[режимах работы](../../dev/runtime-modes.md#ai-модели-в-композере-только-презентация).

| Условие | `llmModels` | `webSearchModels` | AI-ответ |
|---------|-------------|-------------------|----------|
| Нет **LLM**-ключей в env | Фиксированный stub из `presentation.json` | Как в stub | Заглушка |
| Есть ≥1 **LLM**-ключ | 2 топовые модели × провайдер с ключом | Пусто, если нет web-ключей; иначе 2 топовые × web-провайдер | Реальный LLM |

- Учитываются только **LLM** env-переменные (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, …);
  web-ключи без LLM-ключа режим не меняют.
- Имена моделей — **первые две** из каталога провайдера (`model_catalog.py`, зеркало
  `LLM_PROVIDER_MODELS` / `WEB_SEARCH_PROVIDER_MODELS` на фронте).
- В профиле презентации ключи не хранятся — резолв **напрямую** с env по `provider` при
  запросе (см. шаг 1).
- `orchestratorModels` остаётся пустым; оркестратор для презентации не требуется.

**Тесты:**

- `demo-full`: env с ключом → модель с `env:<NAME>`; env пустой → заглушки.
- `presentation`: нет LLM-ключей → stub из JSON; только `DEEPSEEK_API_KEY` → две модели
  DeepSeek, `webSearchModels` пустой; LLM + `TAVILY_API_KEY` → LLM + две Tavily web-модели.

---

### Шаг 3 — Сборка контекста и LLM-клиент (SSE)

**Спецификация сборки:** [Сборка контекста для AI-чатов](../../dev/ai-context-assembly.md)
(system prompt, summary bundle, rolling summary, primer, окно диалога, ветки, RAG).

**Файлы:** `backend/app/services/ai/context.py` (новый),
`backend/app/services/ai/llm.py` (новый), `backend/app/services/ai/providers.py` (новый),
`backend/app/api/v1/ai.py`, фронт: `frontend/src/shared/api/httpClient.ts`,
`frontend/src/shared/api/repositories.ts`, `httpRepositories.ts`,
`seedRepositories.ts`, чат-UI.

**Бэкенд:**
1. Сервис сборки контекста: `flattenVisibleWithPaths` → primer (bundle + rolling summary) →
   окно диалога активной ветки; `scope: "post"` добавляет данные поста в bundle.
2. LLM-клиент через `httpx`: общий код для **OpenAI-compatible** `POST …/v1/chat/completions`
   (стриминг). Реестр провайдеров на шаге 3:
   | `provider` в профиле | `base_url` | env-fallback |
   |---------------------|------------|--------------|
   | `OpenAI` | `https://api.openai.com` | `OPENAI_API_KEY` |
   | `DeepSeek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

   Один HTTP-клиент, разные `base_url` + ключ; BYOK из профиля подставляется для обоих.
   Неподдерживаемый `provider` → `422` с понятной ошибкой (не заглушка).
3. `POST /ai/reply/` → `text/event-stream`; чанки `data: {"text":"..."}\n\n`.
4. Нет ключа: презентация/демо → стрим-заглушка; реальный аккаунт → `422`.

**Фронтенд:**
5. `apiStream()` в `httpClient.ts` (fetch + ReadableStream reader).
6. `AssistantRepository` — стриминговый метод (`onToken`/async-iterator);
   `getXReply` остаётся обёрткой. MSW/seed имитируют поток (чанкуют заглушку).
7. Чат-UI (глобальный + пост) — дописывание токенов по мере прихода.

**Тесты:** формат SSE; заглушка в SSE-формате; `422` для реального без ключа;
интеграционные тесты с моком HTTP для OpenAI и DeepSeek (разные `base_url`, один контракт).

---

### Шаг 4 — RAG (опционально, под флагом) ✅ реализовано

**Файлы:**
- `backend/app/core/config.py` — `rag_enabled`, `rag_top_k`, `rag_min_similarity`, `rag_max_note_chars`, `embedding_model_local`, `embedding_provider_byok`
- `backend/alembic/versions/005_pgvector_rag_tables.py` — расширение `vector`, таблицы `note_embeddings` и `embedding_jobs`
- `backend/app/services/ai/embeddings.py` — `LocalEmbeddingBackend` (fastembed/e5-small), `RemoteEmbeddingBackend` (OpenAI-compatible), `resolve_embedding_backend`
- `backend/app/services/ai/rag.py` — `markdown_to_index_text`, `content_hash`, `index_note`, `remove_note`, `retrieve_top_k`, `format_rag_context`
- `backend/app/services/ai/rag_worker.py` — durable queue + asyncio worker (SKIP LOCKED), `enqueue_note_job`, `enqueue_backfill`
- `backend/app/services/ai/providers.py` — `EmbeddingProviderSpec`, `EMBEDDING_PROVIDER_SPECS`
- `docker-compose.yml` — образ `pgvector/pgvector:pg16`
- `docs/dev/note-format.md` — спецификация markdown-формата заметок

**Архитектура:**
1. Флаг `RAG_ENABLED=1` в env; при выключенном — хуки, воркер и retrieval пропускаются полностью.
2. Образ БД: `pgvector/pgvector:pg16`; миграция создаёт расширение `vector` (soft-skip без pgvector), таблицы `note_embeddings` и `embedding_jobs`.
3. При сохранении заметки (global или в посте) — `enqueue_note_job` добавляет задачу в `embedding_jobs` в той же транзакции.
4. Воркер (asyncio task, lifespan) обрабатывает задачи с `SELECT … FOR UPDATE SKIP LOCKED`.
5. Embeddings: `intfloat/multilingual-e5-small` (384d, CPU, fastembed) по умолчанию; BYOK через OpenAI-compatible `/v1/embeddings` при `EMBEDDING_PROVIDER_BYOK`.
6. Retrieval: cosine top-k → `format_rag_context` → дописывается к последнему `user`-сообщению (`assemble_reply_messages(rag_context=...)`).
7. Активен только для реального LLM (не заглушки), только при `RAG_ENABLED=1`.

**Тесты:** `tests/test_rag.py` (38 тестов) — `markdown_to_index_text`, `content_hash`, `retrieve_top_k` (мок pgvector), дедупликация чанков, RAG-инъекция в контекст.

**Формат заметок:** тела заметок переведены на CommonMark + GFM-таблицы; вложения — через `attachment:<id>`. Миграция данных: `alembic/versions/004_notes_markdown_migration.py` + `scripts/migrate_notes_to_markdown.py`. Frontend: `NoteMarkdownRenderer` (react-markdown + remark-gfm), drag-and-drop вставка вложений.

---

### Шаг 5 — Шифрование ключей at-rest ✅ реализовано

**Файлы:**
- `backend/app/core/crypto.py` — Fernet (`enc:v1:`), `encrypt_byok` / `decrypt_byok`
- `backend/app/core/config.py` — `BYOK_ENCRYPTION_KEY`
- `backend/app/services/ai/byok_profile.py` — encrypt / mask / reveal для `profiles.ai`
- `backend/app/api/v1/profile.py` — `PUT /profile/ai/` шифрует, `GET` маскирует
- `backend/alembic/versions/006_encrypt_byok_keys.py` — первая миграция данных
- `backend/alembic/versions/007_encrypt_profile_secrets_at_rest.py` — все списки моделей + Telegram
- `frontend` — preview в поле (`abc**********xyz`), копирование через reveal-on-copy

**Поведение:**
1. BYOK-ключи реальных аккаунтов шифруются перед записью в Postgres (Fernet).
2. При `GET` и ответе `PUT` на фронт уходят только preview-токены.
3. Полный ключ — по `POST /profile/ai/reveal-key/` (только владелец аккаунта).
4. Дешифровка только при резолве ключа на бэкенде (`keys.py`, `embeddings.py`).
5. При сохранении preview-токена («не менять») значение восстанавливается из предыдущего
   профиля по `id` модели и повторно шифруется (дозашифровка legacy plaintext).
6. Пустой `BYOK_ENCRYPTION_KEY` — no-op (только dev/test).

**Списки моделей:** `llmModels`, `webSearchModels`, `orchestratorModels`,
`webReasonerModels`, `ragReasonerModels`, `visionModels`, `imageGenerationModels`,
`embeddingsModel`.

> Ссылки `env:<NAME>` и demo-фикстуры (`sk-openai-demo`, …) **не шифруются** — это не секреты.

**Тесты:** `tests/test_byok_encryption.py`, `tests/test_migration_007_encrypt_profile_secrets.py`.

---

### Шаг 6 — Расширенные возможности (по приоритету)

- [ ] Дополнительные LLM-провайдеры (Anthropic Messages API, Google Gemini, …)
- [ ] Web-search модели (Perplexity/Tavily)
- [ ] Multi-response (несколько вариантов от разных моделей)
- [ ] Vision / image-generation модели
- [ ] RAG-orchestrator / ragReasoner (расширенная логика)

---

## Поток запроса

```
Клиент → POST /ai/reply/ { text, scope, chatId, postId? }
  → резолв ключа (BYOK / env:<NAME> / env-fallback / нет)
  → сборка контекста (см. ai-context-assembly.md):
      systemPrompt → primer (bundle + rolling summary) → окно активной ветки
  → [RAG_ENABLED + модель] retrieval из заметок → к последнему user
  → запрос к LLM (+ web-search если включён)
  → стрим ответа (SSE) → data: { "text": "..." }
  ── нет ключа + реальный аккаунт → 422 (AI недоступен)
  └─ нет ключа + презентация/демо → заглушка (SSE-формат)
```

---

## Критерий завершения фазы

- Реальный AI-ответ при наличии пригодного ключа (любой режим), стриминг работает.
- Работают модели с `provider: "OpenAI"` и `provider: "DeepSeek"` (BYOK и env).
- Сборка контекста соответствует [ai-context-assembly.md](../../dev/ai-context-assembly.md)
  (primer, bundle-версии, rolling summary, активная ветка).
- Презентация/демо без env-ключей → заглушка; реальный аккаунт без ключа → `422`.
- RAG включается/выключается флагом и корректно влияет на промпт.
- BYOK-ключи зашифрованы в БД; на фронт уходят только preview; reveal-on-copy работает.

---

## Безопасность — осталось сделать

Текущая схема (шаг 5): маскирование + reveal-on-copy + Fernet at-rest. Ниже — задачи,
которые **ещё не реализованы**.

### CSP (отложено)

- [ ] Настроить **Content-Security-Policy** на фронтенде (заголовки или meta).
- Маскирование и reveal-on-copy **снижают** риск утечки ключей при XSS, но **не заменяют**
  CSP: при внедрении вредоносного скрипта злоумышленник всё ещё может вызвать
  `POST /profile/ai/reveal-key/` и `POST /profile/telegram/reveal-secret/` от имени
  залогиненного пользователя.

### Продакшен-гигиена (перед выкладкой в prod)

- [ ] **Бэкап `BYOK_ENCRYPTION_KEY`** — без него все зашифрованные BYOK и Telegram-секреты
  в БД **не расшифровать** (потеря ключа = потеря данных).
- [ ] **Ротация ключа** — сейчас не реализована; потребуется скрипт re-encrypt всех
  `enc:v1:` значений в `profiles.ai` и `profiles.telegram` новым Fernet-ключом.
- [ ] **KMS / Vault** вместо env-переменной — для prod предпочтительнее, чем хранить
  `BYOK_ENCRYPTION_KEY` в `.env` / docker-compose secrets.
- [ ] **`.env` не в git** — server-side ключи (`DEEPSEEK_API_KEY`, `JWT_SECRET`,
  `BYOK_ENCRYPTION_KEY`, …) только в локальных / CI secrets; в репозитории — только
  `.env.example` с плейсхолдерами.

---

← [Фаза 1](phase-1-core-api.md) · [Назад к Roadmap](../roadmap.md) · [Фаза 3 →](phase-3-telegram.md)
