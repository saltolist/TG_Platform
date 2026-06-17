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

### Шаг 2 — Предзаполнение моделей демо (обновление сидера)

**Файлы:** `backend/app/db/seed.py`, `backend/fixtures/demo-full.json`.

1. При сиде `demo-full` заполнять `AiProfileConfig.llmModels` ссылками
   `env:<NAME>` для провайдеров с ключами в env (как минимум OpenAI и DeepSeek).
2. Если в env нет ни одного ключа — заполнить заглушечные модели (паритет с
   текущим MSW-демо).
3. Идемпотентность: повторный сид обновляет модели согласно текущему env.

**Тесты:** env с ключом → демо-модель ссылается на него; env пустой → заглушки.

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

### Шаг 4 — RAG (опционально, под флагом)

**Файлы:** `backend/app/core/config.py`, `backend/alembic/versions/00X_*.py`,
`backend/app/services/ai/rag.py` (новый), `docker-compose.yml`.

1. Флаг `RAG_ENABLED` в env; при выключенном — retrieval пропускается полностью.
2. Образ БД → `pgvector/pgvector:pg16`; миграция: расширение `vector` + таблица
   эмбеддингов.
3. Индексирование **глобальных заметок и заметок постов** при upsert.
4. Retrieval top-k → дописывается к последнему `user`-сообщению (см.
   [сборку контекста](../../dev/ai-context-assembly.md#3-rag-заметки-и-веб)).
5. Активен только при наличии пригодной реальной модели (env-ключ для
   презентации/демо, BYOK для реального).

**Тесты:** флаг off → retrieval не вызывается; флаг on без модели → пропуск;
флаг on + модель → top-k попадает в промпт.

---

### Шаг 5 — Шифрование ключей at-rest

**Файлы:** `backend/app/core/security.py` (или новый `crypto.py`),
`backend/app/api/v1/profile.py`.

1. BYOK-ключи реальных аккаунтов шифруются перед записью в Postgres (Fernet/KMS).
2. Дешифровка только в момент резолва ключа на бэкенде.
3. Миграция существующих значений (если есть).

> Ссылки `env:<NAME>` шифровать не нужно — это не секрет.

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
- BYOK-ключи зашифрованы в БД.

---

← [Фаза 1](phase-1-core-api.md) · [Назад к Roadmap](../roadmap.md) · [Фаза 3 →](phase-3-telegram.md)
