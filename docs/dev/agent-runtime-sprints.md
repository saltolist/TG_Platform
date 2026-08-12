# План-спринты: довести WorkspaceAgent до рабочего состояния и к эталону

Заменяет [agent-reference-rollout-plan.md](agent-reference-rollout-plan.md). Отличие: спринты вместо фаз, приоритет — **сначала среда поднимается и система перестаёт врать/ломаться на multi-turn, потом растёт к эталону**. Опирается на фактический аудит кода (июль 2026): состояние подтверждено запуском (langgraph не стоит в venv, контейнер backend `Exited 255`, `golden_runner` проверяет наличие файла, а не поведение).

Источники эталона (инварианты, не «ISO»):
- Anthropic — [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents), [Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents), [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- LangGraph Memory / durable execution / HITL
- LangSmith RAG groundedness + trajectory evals
- Agentic RAG SoK (verification-in-loop, when-to-stop на evidence)

Связано: [ADR-012](adr/012-unified-agent-runtime.md), [ADR-009](adr/009-dialog-evidence-ledger.md).

---

## Что реально сейчас (факт-аудит)

| Слой | Состояние по коду |
|------|-------------------|
| Durable runs, LangGraph, HITL, checkpointer | ✅ рабочий скелет (StateGraph, Postgres-checkpointer, `interrupt()` + `idempotency_key`/`payload_hash`, advisory-lock sequence) |
| **Локальная среда** | ❌ **langgraph не установлен ни в `.venv`, ни в `.test-venv` → `import` падает; контейнер backend `Exited (255)`. Агент нельзя запустить/протестировать локально** |
| **Архитектура графа** | ⚠️ **два графа + два планнера**: внешний workspace (`bootstrap→workspace_agent→research/answer/proposals`) с планнером-классификатором (`WORKSPACE_SYSTEM`, один выстрел `read\|finish\|post_proposal\|media_proposal`) и внутренний research (`seed→planner→tool→verify→pack`) с **отдельным** планнером (`AGENT_SYSTEM`), **своим** checkpointer'ом и `thread_id`. Внешний слой почти ничего не решает; шов порождает баги (см. ниже) |
| **Answer guard** | ❌ **нет code-gate; `finish→answer` минует research; ответ на пустом pack** |
| **Memory (history)** | ❌ родная thread-память LangGraph не подключена: `messages: Annotated[list, add_messages]` ([state.py:13](../../backend/app/services/agent/runtime/state.py#L13)) объявлен, но **не пишется/не читается** ни одним узлом; история чата не грузится. (Bespoke `dialog_context`/`dialog_ledger` в `configurable` — тоже пустые, но их и не используем: см. Спринт 2) |
| **Checkpoint continuity** | ⚠️ `thread_id = run_id` (новый UUID на запуск) → нет cross-turn; но и не смешивается. Возможен тихий фолбэк на `MemorySaver` = потеря durability |
| **Планнер** | ⚠️ чистый JSON, `temperature=0.0`, reasoning выбрасывается парсером |
| **Tool surface** | ⚠️ `ListPostNotes` реализован (`tool_list_post_notes`), но не в `READ_TOOLS`/диспетчере/промпте = мёртвый код; `ListPosts` рассинхрон args (`status` vs обещанные `query/limit`) |
| **Verify / sufficiency** | ⚠️ есть детерминированная проверка, но: пустые `evidence_ids` авто-заполняются **всеми** записями (обход выбора цитат моделью); `partial` не проверяет пустой контент; hard-stop по `max_steps` обходит verify |
| **Мёртвая проводка** | ⚠️ `messages`, `finish_retrieval`, `research_transcript`, `repair_count` (не инкрементится → repair-петли нет), `RuntimeContext.emit_event/.audit`, `build_runtime_context` — объявлены, не используются. `resume_agent_graph` собирает `cfg` **без** `runtime_context` → `KeyError` при resume в research/answer |
| **Баги двухграфового шва** | ❌ (1) `research_node` переупаковывает результат в records с `"content": ""` ([workspace_graph.py:103](../../backend/app/services/agent/runtime/workspace_graph.py#L103)) → контент выживает только в `rag_context`-строке, `evidence_records` приходят пустыми; (2) checkpoint-ключи рассинхронены (внешний по `run_id`, внутренний по `user_id`); (3) HITL `interrupt()` во внешнем графе + вложенный `astream` research со своим checkpointer = два несогласованных домена durability |
| **Transparency (SSE)** | ❌ только `step_count/status/stopped_reason`; решения планнера (`tool_call`) в state, но не эмитятся |
| **Evals multi-turn / anti-hallucination** | ❌ 19 golden-сценариев есть, но `golden_runner` проверяет лишь `implemented=bool(matches)` (файл существует), **не поведение рантайма** → это спека, не executable gate |
| **Prompt-injection retrieved content** | ❌ текст постов/заметок инжектится в планнер и answer сырым, как доверенный; `test_agent_security.py` валидирует медиа, а не безопасность; входных guardrails и бюджета на run (кроме `max_steps=4`) нет |

Вывод: **скелет на уровне индустрии, но контур разомкнут — среда не поднята, граф раздвоен, answer guard, память и прозрачность планнера не подключены.** Провалы в чате — это wiring + enforcement + лишний шов, не «LangGraph не работает». Целевая архитектура — **один tool-loop**: один планнер, одна память, один checkpoint; read-tools, proposal-tools и finish — это инструменты, между которыми выбирает **один** планнер. Слияние делаем **до** памяти и мышления, иначе чиним их дважды.

---

## Definition of Done (эталон)

1. **Groundedness** — любой фактический claim из `rag_context` либо честный отказ. Пустой pack ⇒ **никогда** не выдуманный текст.
2. **Multi-turn memory** — «они», «внутри», «а второй?» резолвятся без угадывания.
3. **Планнер мыслит перед действием** — `reasoning`/`observations` **до** выбора tool, опираются на ground truth (transcript), сохраняются и видны в UI.
4. **Tool loop с наблюдениями** — каждый шаг опирается на реальный tool observation; полный tool surface.
5. **Evals** — golden (multi-turn deixis, empty-pack refusal, trajectory must-call) зелёные, ломают CI при регрессе.

**Приоритет пользователя: п.1 + п.2 + п.3 = «система работает». п.4 + п.5 = «эталон».**

---

## Спринт 0 — Среда поднимается (блокер №0, 0.5–1 день)

Цель: агент вообще запускается и тестируется локально. Без этого ни одну правку из Спринтов 1–3 нельзя проверить.

- Установить `langgraph` (+ `langgraph-checkpoint-postgres`) в `.venv` и `.test-venv` (через `requirements.txt`, как в CI).
- Поднять контейнер backend (сейчас `Exited 255`), убедиться, что импорт рантайма проходит.
- Убедиться, что Postgres-checkpointer реально инициализируется, а не тихо падает в `MemorySaver` (лог-строчка при фолбэке).
- Файлы: `backend/requirements.txt`, docker-compose, `runtime/checkpoint.py`.

**Exit:** `import app.services.agent.runtime.workspace_graph` проходит; агент-тесты запускаются локально; один smoke-run доходит до answer.

---

## Спринт 1 — Система перестаёт врать (must, 3–5 дней)

Цель: убрать галлюцинации на пустом контексте и починить tool surface. Это то, что делает систему **пригодной к использованию**. **Делается на едином графе из 1.0** — не в двух планнерах.

### 1.0 Collapse двух графов в один tool-loop (архитектурный корень, делать ПЕРВЫМ)
- **Факт:** сейчас два графа с двумя планнерами и двумя checkpoint-доменами. Внешний (`workspace_agent_node`, `WORKSPACE_SYSTEM`) — это intent-**классификатор** (`read|finish|post_proposal|media_proposal`, один выстрел), внутренний (`research/graph.py`, `AGENT_SYSTEM`) — настоящий tool-loop со своим checkpointer'ом/`thread_id`.
- **Три бага порождены именно швом:** (а) `research_node` переупаковывает records с `content=""` ([workspace_graph.py:103-113](../../backend/app/services/agent/runtime/workspace_graph.py#L103)) → answer видит пустой контент; (б) рассинхрон checkpoint-ключей (workspace `run_id` vs research `user_id`+`uuid4`); (в) `interrupt()` и вложенный `astream` research — два несогласованных домена персистентности/прерывания.
- **Решение:** один `StateGraph`, один планнер, один checkpointer. Read-tools, proposal-tools и `finish` — это **инструменты, между которыми выбирает единый планнер**, а не отдельные графы. Verify/repair остаётся как узлы одного графа. Внешний intent-классификатор схлопывается в первое решение того же планнера.
- **Критерий отмены (оставить два):** только если назовёшь конкретную причину изоляции research — отдельный бюджет/модель/переиспользование из другой точки входа. Единственный вызов из `research_node` тем же reasoner'ом — это случайная сложность, не изоляция.
- **Почему первым:** память (Спринт 2) и reasoning (Спринт 3) иначе чинятся дважды, в двух планнерах, и слияние всё равно их перетрясёт. Спринт 1 и так лезет в шов (контракт ID пересекает границу).
- Файлы: `runtime/workspace_graph.py` (единый граф), `research/graph.py` (узлы вместо отдельного графа), `runtime/executor.py` (один checkpoint-домен).

### 1.1 Answer guard (code-gate, не промпт)
- В `answer_node`: если `evidence_ids` пуст **или** весь `rag_context` пуст → **отказ / re-research**, не ответ.
- Роутинг планнера: `finish` разрешать только для явно не-фактических запросов; фактический вопрос без собранного evidence → назад в tool-loop, не в answer.
- Файлы: `runtime/workspace_graph.py` (`answer_node`, роутинг единого графа).

### 1.2 Evidence ID contract (КОРЕНЬ пустого pack — #3)
- **Причина:** `records` ключуются хешем `uuid5(path+content)` ([evidence.py:62](../../backend/app/services/agent/research/evidence.py#L62)), а планнер в `FinishRetrieval` шлёт **ID постов** (`3`, `721c63fe`). Проверка `eid not in records` → **всё missing**, pack пуст, answer всё равно отвечает.
- **Чистое решение — убрать индирекцию, а не строить резолвер поверх неё.** Evidence адресуется **натуральными стабильными ID** (`post:3`, `note:721/abc`, `attachment:<file>`) от tool'а до цитаты. Тогда рассинхрона нет и резолвить нечего.
- Планнер видит те же натуральные ID, что цитирует → `FinishRetrieval` их и возвращает.
- Файлы: `research/evidence.py` (ключ = натуральный ID, не хеш), `research/graph.py`, `research/verifier.py`, `research/pack.py`.

### 1.3 Verify-гейт: закрыть три дыры
- **Не авто-заполнять** `evidence_ids` всеми записями в `verify_node`/`pack_node` — пустой список = провал/repair, а не «цитируй всё». (Делать **после** 1.2, иначе пустой pack всегда fail.)
- `status == "partial"` тоже проверяет dangling (пустой контент цитируемых id) — сейчас `partial` проходит при `not missing` даже с пустым контентом ([verifier.py:64](../../backend/app/services/agent/research/verifier.py#L64)).
- Hard-stop по `max_steps` роутить **через** `verify`, а не сразу в `pack`.
- Файлы: `research/verifier.py`, `research/graph.py` (`verify_node`, `route_plan`, `route_after_tool`).

### 1.4 Tool surface
- Подключить `ListPostNotes`/`OpenNote` в `READ_TOOLS` + dispatch + описание «когда вызывать» в `AGENT_SYSTEM` (сейчас `tool_list_post_notes` реализован, но не в графе → планнер не дочитывает заметки, #4).
- Починить `ListPosts`: привести args к тому, что обещает промпт (`query/limit`), убрать «скрытый» `status` (#12 signature mismatch).
- Tool observation (`notes=1` и т.п.) → first-class запись в evidence/контекст следующего шага, а не только в summary tool'а (#5: answer видит pack, не transcript).
- Файлы: `research/graph.py` (`READ_TOOLS`, `_execute_tool`, `AGENT_SYSTEM`), `research/rag_tools.py`.

### 1.5 Починить resume + signature mismatch (иначе HITL-resume падает)
- `resume_agent_graph` собирает `cfg` **без** `runtime_context` → `KeyError` при resume в research/answer/workspace_agent. Класть `runtime_context` в `configurable`.
- `complete_chat_completion(temperature=…)` signature mismatch (#12) — проверить сигнатуру.
- Файлы: `runtime/executor.py`, `services/ai/llm.py`.

**Exit:** run с пустым pack никогда не отдаёт факт; `FinishRetrieval` цитирует реальные record-ключи (pack не пуст); вопрос про содержимое заметки доходит до `OpenNote`; пост с `notes=0` не описывается как «есть заметка»; resume после HITL не падает.

---

## Спринт 2 — Память (must, 3–5 дней)

Цель: multi-turn перестаёт ломаться. **Принцип: память = родная thread-persistence LangGraph (message history), НЕ bespoke-подсистема (ledger/resolver/router из ADR-009).** ADR-009 существовал как компенсация за лоссовую переупаковку контекста в «retrieval brief» — в чистом agent-loop этой потери нет, поэтому и чинить нечего. Примитив уже есть: `messages: Annotated[list, add_messages]` ([state.py:13](../../backend/app/services/agent/runtime/state.py#L13)) объявлен и **не используется** — включаем его.

### 2.1 Родная short-term память (message history)
- Грузить прошлые turn'ы чата в `state["messages"]` при старте run (`_execute_agent_run`), thread keyed by `chat_id`.
- Планнер и answer видят прошлые user/assistant сообщения **напрямую** → дейксис («они», «та картинка», «а второй?») резолвит **сама модель из контекста**, без отдельного router'а.
- Убрать самодельную string-сборку `dialog_context` — она дублирует то, что даёт message history.
- Файлы: `tasks/agent_runs.py`, `runtime/executor.py`, узлы единого графа (читать `messages`). После 1.0 — одно место, не два.

### 2.2 Референты артефактов — без resolver'а
Прямой ответ на «учитывает ли планнер объекты/артефакты из прошлых обсуждений»: **да — потому что он видит прошлые turn'ы напрямую, а не через ledger.**
- Агент **пере-вызывает tool** (`OpenNote`/`HydrateAttachment`) с натуральным ID, который видит в прошлом сообщении. Это штатный tool-loop, не подсистема.
- **НЕ** строим `artifact resolver`/`referent router`/`RetrievalBrief.referent_type` — это архитектура, которая лагала.
- Опционально **позже и только по замерам:** тонкий кэш гидратированных превью по `ref` (чтобы не гонять vision дважды). Это оптимизация-кэш, не столп памяти. Вводить, если re-hydration измеренно дорог.
- Файлы: `research/graph.py` (tool re-call работает из коробки, если ID видны в контексте).

### 2.3 Thread persistence + детерминированный namespace (#9)
- **Факт (до 1.0):** research subgraph — `thread_id = ctx.user_id`, `checkpoint_ns = research:{checkpoint_id or uuid4()}` ([graph.py:423](../../backend/app/services/agent/research/graph.py#L423)). `uuid4()`-fallback при пустом `checkpoint_id` → случайный ns → **resume не находит чекпоинт, durability теряется молча** (корень #9).
- После 1.0 checkpoint-домен **один**: `thread_id = chat_id` (continuity across turns), `checkpoint_ns` детерминирован от `run_id`; `uuid4()`-fallback убран (нет `run_id` → явная ошибка). Рассинхрона двух графов больше нет по построению.
- Проверить, что Postgres saver реально инициализируется (иначе `MemorySaver` = не durable).
- Файлы: `runtime/executor.py`, `runtime/checkpoint.py` (единый граф из 1.0).

**Exit:** «2 поста → про что они?» и «а что было на той картинке из прошлого turn'а?» резолвятся из message history + tool re-call, без ledger; resume находит чекпоинт детерминированно.

---

## Спринт 3 — Планнер мыслит (must для «работает как надо», 3–5 дней)

Цель: планнер думает **перед** действием, мысль опирается на ground truth и видна. Реализуем **Вариант 1** (reasoning внутри структурного JSON) как прод-фундамент. Нативный thinking (Вариант 2) — опционально позже, поверх этого контракта. Отдельная фаза-планирования (Вариант 3) — не делаем.

### 3.1 Схема решения с reasoning ПЕРЕД tool
Порядок ключей критичен (авторегрессия: думает → решает, не оправдывает пост-фактум):
```json
{
  "observations": ["ListPosts: пост 721 notes=1", "пост 3 notes=0"],
  "reasoning": "нужен текст заметки 721, метаданных мало",
  "gap": "note content missing",
  "tool": "OpenNote",
  "args": {"note_id": "...", "post_id": "721"}
}
```
- Обновить системный промпт **единого планнера**: требовать `observations`/`reasoning`/`gap` до `tool` (после 1.0 — один промпт, не `AGENT_SYSTEM` + `WORKSPACE_SYSTEM` порознь).
- Парсер решения: **сохранять** `reasoning`/`observations`, а не выбрасывать.
- Файлы: `runtime/workspace_graph.py` (промпт единого планнера, парсер решения).

### 3.2 Anti-косметика (ground truth)
- Лёгкая валидация: `observations` ссылаются на реальный transcript/tool-выхлоп; выдуманные — флаг/repair-hint.
- Anthropic principle #2: мысль определяет решение, а не описывает принятое.

### 3.3 Эмит в SSE
- Новый event `planner_step` с `{step, observations, reasoning, gap, tool, args}`.
- Файлы: `runtime/executor.py`, `runtime/sse_events.py`, frontend `agentRuns.ts` / composer.

**Exit:** в UI по run видны шаги 1…N с мыслью+tool, совпадающие с transcript; reasoning влияет на выбор tool (проверяется на golden).

---

## Спринт 4 — Evals как страховка (high, 5–8 дней, можно параллельно с 1–3)

Цель: регрессы ловятся автоматически, «улучшения» не откатывают систему.

- **Переделать `golden_runner` из спеки в executable gate**: сейчас он проверяет `implemented=bool(matches)` (наличие .md-файла), а не поведение рантайма. Нужно прогонять реальный run и ассертить исход.
- Начать с 3 executable-сценариев поверх рантайма (19 .md уже описаны): multi-turn deixis, notes-with-content, empty-pack refusal.
- Детерминированные грейдеры: `claims ⊆ evidence`; `empty pack ⇒ no factual claim`; trajectory must-call (`notes-content → OpenNote/ListPostNotes`).
- LLM-judge groundedness — после калибровки.
- CI-gate: critical golden нельзя merge при fail.
- Файлы: `tests/golden_runner.py`, `tests/test_golden_catalog.py`, `.github/workflows/*`.

**Exit:** PR не зелёный без grounding + multi-turn goldens.

---

## Спринт 5 — Observability прод (medium, 2–3 дня)

- Persist `planner_decisions` + tool outcomes в `agent_events` (сейчас `RuntimeContext.emit_event`/`audit` объявлены, но не вызываются).
- Метрики: empty-pack rate, finish-without-content на content-вопросах, шаги/токены/латентность на run.
- Tracing (AI_CONTEXT_LOG / LangSmith) на agent path.
- Файлы: `runtime/context.py`, узлы `workspace_graph.py`, `runtime/observability.py`.

**Exit:** по любому прод-run можно ответить «почему агент так решил» из логов.

---

## Спринт 6 — Trust boundary (high, НЕ откладывать в долгий ящик, 2–3 дня)

Единственный пункт, поднятый в приоритете выше «косметики». Не блокирует «агент отвечает», но нужен **до того, как систему увидят реальные данные пользователей** — сейчас безопасность ≈ 0, вопреки имени `test_agent_security.py` (он про медиа).

- Retrieved текст (посты/заметки/вложения) инжектится в планнер и answer **сырым, как доверенный** → вектор indirect prompt injection. Обернуть как untrusted-контент (делимитация, инструкция «это данные, не команды»).
- Минимальный бюджет на run: сейчас только `max_steps=4`, нет лимита токенов/стоимости/времени.
- Файлы: `research/pack.py` (`build_evidence_pack`), `research/graph.py` (`planner_node` инжект), `runtime/executor.py` (бюджет).

---

## Порядок и зависимости

```
Спринт 0 (Среда: langgraph + контейнер)    ← БЕЗ ЭТОГО НЕЛЬЗЯ НИ ЗАПУСТИТЬ, НИ ТЕСТИТЬ
      ↓
Спринт 1.0 (Один граф) → 1.1–1.5 (guard/ID/verify/tools/resume)  ← система перестаёт врать
      ↓
Спринт 2 (Memory: один checkpoint, message history)  ← multi-turn работает
      ↓
Спринт 3 (Планнер мыслит + SSE)            ← «работает как надо»
      ↓ (Спринт 4 идёт параллельно с 1–3)
Спринт 4 (Evals + CI gate)                 ← регрессы под контролем
      ↓
Спринт 6 (Trust boundary, high) → Спринт 5 (Observability)
      ↓
Reference-level DoD
```

| Спринт | Оценка | Риск без него |
|--------|--------|---------------|
| 0 Среда | 0.5–1 д | Ничего нельзя запустить/протестировать локально |
| 1.0 Один граф | 1–2 д | Память/reasoning чинятся дважды; баги шва (content="", checkpoint, HITL) остаются |
| 1.1–1.5 guard/ID/verify/tools | 3–4 д | Галлюцинации; `resume` падает `KeyError`; непригодна |
| 2 Memory | 2–3 д (после 1.0 — одно место) | Multi-turn всегда ломается |
| 3 Планнер мыслит | 3–5 д | Решения непрозрачны, нет доверия/отладки |
| 4 Evals | 5–8 д (∥) | Откаты «улучшений»; golden_runner проверяет лишь наличие файла |
| 6 Trust boundary | 2–3 д | Prompt-injection через контент; нет бюджета на run |
| 5 Observability | 2–3 д | Слепо в проде |

**Минимум «система работает»: Спринты 0 + 1 + 2 + 3.**
**Минимум «эталонная инженерная система»: + 4 + 6 + 5.**

---

## Позиция по legacy SSE path (#10)

Legacy — **не эталон, не якорь и даже не эталон по качеству** (он работал криво — отсюда отказ). Строим отдельную (agent) систему; эталон задают инварианты (Anthropic/LangGraph/groundedness), а не «догнать legacy».

- **Не** тянем legacy-архитектуру в agent path и **не** держим два контура в паритете.
- После того как Спринты 1–3 закрывают grounding + память + дочитывание, agent path — единственный для composer.
- Legacy держим как **аварийный fallback до зелёных executable-golden'ов** (Спринт 4), затем flag → удаление.
- Из legacy **ничего структурного не портируем**. Ledger/artifact-resolver/referent-router (ADR-009) **не переносим** — это компенсация за лоссовый retrieval-brief, которой в чистом agent-loop нет. Берём максимум отдельные чистые функции (например конкретный запрос к БД), не подсистемы.

---

## Что сознательно НЕ делаем

| Идея | Почему нет |
|------|------------|
| Два графа / вложенный research-subgraph | Один tool-loop: один планнер, память, checkpoint. Шов давал content=""/checkpoint-рассинхрон/HITL-домены. Два — только при доказанной изоляции research (Спринт 1.0) |
| Нативный thinking (Вариант 2) сейчас | Прод-фундамент — структурный reasoning (В1). Thinking — усилитель качества позже, когда стабильно |
| Отдельная фаза-планирования (Вариант 3) | x2 латентность/стоимость; не оправдано без measured gain |
| Жёсткий path ListPosts→OpenNote для всех | Anthropic: flexibility + eval, не script |
| Supervisor / multi-agent | Simple compositions first |
| LLM-critic на каждый шаг | Complexity without measured gain |

---

## Итог

Архитектура — **один чистый tool-loop**: один планнер мыслит перед действием, одна память (родная thread-persistence), один checkpoint-домен, натуральные evidence ID сквозь весь путь. Никаких вложенных графов, ledger-подсистем и хеш-индирекции — сложность добавляется только по измеренной необходимости.

Эталон = замкнутый контур на этом графе:
**память → tools с наблюдениями → планнер мыслит перед действием → verify sufficiency → ответ только из evidence → HITL на мутациях → log решений → eval.**

Скелет LangGraph/HITL и реальные руки (мутации постов, генерация медиа) готовы. Разрывы — в мыслящей части: слить два графа в один (1.0), заземлить (1.1–1.5), включить память (2), заставить планнер мыслить (3). Спринты 4–6 доводят до инженерного эталона.

---

## Риски реализации (дизайн чист — беречь при исполнении)

План описывает чистую архитектуру. Оставшийся риск — **исполнительный**: собрать грязную реализацию из чистого плана. Три границы и как страхуем:

| Риск | Почему | Страховка |
|------|--------|-----------|
| **Слияние графов (1.0) внесёт регресс** | Рефактор durable-графа с HITL/checkpoint — самая опасная правка плана | Отдельный PR только под 1.0; golden-прогон (Спринт 4) **до и после** слияния; поведение answer/HITL не меняется, меняется только структура графа |
| **«Чистый план → грязный код»** | Без запуска и без gate дизайн деградирует в реализации | Спринт 0 (среда) — жёстко первым; executable-evals (Спринт 4) как **merge-gate** до того, как трогать 1–3; никакого «почищу потом» |
| **Единый планнер: промпт растёт** | Он теперь и классифицирует intent (read/mutate/media), и ведёт research в одном промпте | Держать инструменты как tools одного планнера, не как ветки; если промпт распухнет — развести на tool'ы **внутри** одного графа (не назад в два графа). Критерий — в 1.0 |

**Что план сознательно НЕ обещает:**
- «Полноценный ИИ-менеджер» после Спринтов 1–3. Там будет чистый, но **узкий** агент: чтение + предлагать мутации/медиа через HITL. Управленческие полномочия (аналитика→решение, автономное планирование контента, редактирование по цели) — это рост **tool surface** отдельными итерациями поверх чистого скелета, за рамками первых спринтов.
- Автономные мутации без подтверждения. Публикация/удаление/трата денег на генерацию — всегда через HITL. Это инвариант, не временное ограничение.

**Правило исполнения:** каждый спринт мерджится только с зелёным executable-golden'ом по своей цели. Порядок (0 → 1.0 → 1.1–1.5 → 2 → 3) не переставлять — он и есть защита от грязной реализации.
