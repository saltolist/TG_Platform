# WorkspaceAgent — что осталось сделать

Снимок оставшихся работ по доведению agent runtime path (`POST /ai/runs/`) до
reference-level. **Канон — [agent-runtime-sprints.md](agent-runtime-sprints.md)**
(старый [agent-reference-rollout-plan.md](agent-reference-rollout-plan.md)
помечен deprecated). Этот файл фиксирует статус по спринтам и **только
незакрытое**, чтобы не перечитывать весь канон.

Ветка: `cursor/per-post-analytics-foundation`.

Статус проверен по коду и git (коммиты `5e54ac6` §1.0, `7b6d62b` §1.2–1.5,
`8e83e58` грейдеры). Тесты: 38 agent-тестов зелёные + 2 новых для Спринта 2.

---

## Легенда статусов

- ✅ **done** — сделано и проверено тестами.
- 🟡 **partial** — основа есть, остался хвост (указан).
- ❌ **open** — не начато.

---

## Статус по спринтам

| Спринт | Статус | Комментарий |
|--------|--------|-------------|
| 0 Среда поднимается | ✅ done | `import` рантайма проходит, langgraph в venv, 38 тестов идут локально |
| 1.0 Один граф | ✅ done | Unified `workspace_graph`: research-узлы (seed/planner/tool/verify/pack) first-class; один checkpointer; `thread_id=run_id`. `run_research_graph` остался только для legacy `rag_query.py`, не на agent path |
| 1.1 Answer guard | ✅ done | code-gate отказа в `answer_node`, `stopped_reason=empty_evidence_refusal` |
| 1.2 Evidence ID contract | ✅ done | натуральные ID (citation path) сквозь tool→pack→finish |
| 1.3 Verify-гейт | ✅ done | пустой evidence=провал; partial проверяет dangling; hard-stop через verify |
| 1.4 Tool surface | 🟡 partial | `ListPostNotes` подключён, `ListPosts` args починены. **Остаток:** tool observation как first-class запись в evidence/контекст следующего шага (сейчас только в summary tool'а) |
| 1.5 Resume + signature | ✅ done | `resume_agent_graph` кладёт `runtime_context`; `complete_chat_completion` sig проверена |
| 2 Память | 🟡 partial | 2.1 done через `dialog_context` (ADR-отступление от native `messages`, см. ниже); 2.3 закрыт решением «оставить `thread_id=run_id`» (не баг, обосновано); 2.2 (referent re-call) не проверялся отдельно |
| 3 Планнер мыслит | ❌ open | |
| 4 Evals | 🟡 partial | грейдеры-библиотека + юнит-тесты есть; **не** executable gate и **не** CI-блокер |
| 5 Observability | ❌ open | |
| 6 Trust boundary | ❌ open | **high**, не откладывать |

---

## Осталось сделать

### Спринт 2 — Память (must, приоритет #1)

**Обновлено после recon + явного решения пользователя.** Канон ниже
описан как было написано изначально; фактическая реализация в двух местах
**сознательно отклоняется** от буквы канона — с обоснованием, зафиксированным
в момент решения (не втихую).

**Принцип канона:** память = **родная thread-persistence LangGraph** (message
history), **НЕ** bespoke-подсистема. `ledger`/`resolver`/`RetrievalBrief` из
ADR-009 сознательно **не** делать — это архитектура, которая лагала. Примитив
уже объявлен (`messages: Annotated[list, add_messages]` в
[state.py:13](../../backend/app/services/agent/runtime/state.py#L13)), но не
пишется/не читается ни одним узлом (и осталось так — см. 2.1).

- [x] **2.1 История чата → `dialog_context`.** ✅ **Отступление от канона**:
      вместо native `state["messages"]` — server-side loaded история как
      **строка `dialog_context`** в `RuntimeContext`/`configurable`. Причина:
      узлы графа не строят running-transcript, у каждого свой task-shaped
      промпт (research planner уже читал `configurable["dialog_context"]` —
      [research/graph.py:193](../../backend/app/services/agent/research/graph.py#L193),
      [:298](../../backend/app/services/agent/research/graph.py#L298) —
      это плюмбинг уже был, просто не наполнялся); native messages потребовал
      бы переписывать промпт-конструирование planner/answer без функциональной
      выгоды здесь. Не тот же риск, что ledger/resolver из ADR-009 — это
      2-turn'овый текстовый срез, не отдельная подсистема.
      Реализация: `runtime/runs.py` — `load_run_history()` (переиспользует
      `get_owned_chat` из `db/resolve.py` для global-scope, приватный
      `reply_orchestrator._load_owned_post_data` для post-scope) +
      `build_planner_dialog_context()` из `rag_query.py` в
      `rebuild_runtime_context_for_run()`; прокинуто в `cfg.configurable` в
      `runtime/executor.py` (`execute_agent_run`, `resume_agent_graph`) и
      `tasks/agent_runs.py` (передаёт `user_text`).
      Тест: `tests/test_agent_runtime.py::test_rebuild_runtime_context_loads_dialog_context_from_chat_history`
      (+ пустой случай без чата).
      **Открыт хвост:** post-scope у `AgentRun` нет `post_chat_id` (в отличие от
      `AiReplyRequest`) — сейчас матчим `run.chat_id` на `id` чата внутри
      `post.data["chats"]`, а если не найден — берём последний чат поста
      (эвристика, не подтверждена пользователем; см. открытый вопрос ниже).
- [ ] **2.2 Референты артефактов — без resolver'а.** Агент пере-вызывает tool
      (`OpenNote`/`HydrateAttachment`) с натуральным ID из прошлого сообщения —
      штатный tool-loop. НЕ строить artifact resolver / referent router.
      Не проверено отдельным тестом в этой итерации.
      (Опц. позже по замерам: тонкий кэш гидратированных превью по `ref`.)
- [x] **2.3 Thread persistence.** ✅ **Отступление от канона (осознанное,
      подтверждено пользователем)**: `thread_id` остаётся `run.id`, **не**
      переведён на `chat_id`. Причина: память теперь даётся 2.1
      (history-loading), не checkpoint thread'ом — переход на `chat_id` не
      даёт функциональной выгоды здесь, но добавляет риск: recovery-логика в
      `execute_agent_run` ([runtime/executor.py:96–110](../../backend/app/services/agent/runtime/executor.py#L96))
      нашла бы checkpoint предыдущего **завершённого** run'а на новом turn'е и
      вернула бы stale state без доп. `checkpoint_ns`-плюмбинга через start и
      resume. Баг, который 2.3 должен был исправить (случайный `uuid4()`
      namespace, теряющий чекпоинты), уже закрыт в §1.0 — `thread_id`
      детерминирован (`str(run.id)`), без fallback на случайный UUID.

**Exit:** «2 поста → про что они?» резолвится через `dialog_context` (проверено
тестом на уровне `rebuild_runtime_context_for_run`; end-to-end через LLM не
прогонялось в этой сессии — нет доступа к LLM). «А что было на той картинке из
прошлого turn'а?» (2.2, tool re-call) не проверялось.

---

### Спринт 3 — Планнер мыслит (must для «работает как надо»)

Планнер думает **перед** действием, мысль опирается на ground truth и видна.
Реализуем **Вариант 1** (reasoning внутри структурного JSON). Нативный thinking
и отдельная фаза-планирования — не сейчас.

- [ ] **3.1 Схема решения с reasoning ПЕРЕД tool.** Порядок ключей критичен
      (думает → решает): `{observations[], reasoning, gap, tool, args}`. Обновить
      системный промпт единого планнера; парсер **сохраняет** `reasoning`/
      `observations`, а не выбрасывает.
      Файлы: `runtime/workspace_graph.py` (промпт планнера, парсер).
- [ ] **3.2 Anti-косметика.** Лёгкая валидация: `observations` ссылаются на
      реальный transcript/tool-выхлоп; выдуманные → флаг/repair-hint.
- [ ] **3.3 Эмит в SSE.** Event `planner_step` с
      `{step, observations, reasoning, gap, tool, args}`.
      Файлы: `runtime/executor.py`, `runtime/sse_events.py`, frontend
      `agentRuns.ts` / composer.

**Exit:** в UI видны шаги 1…N с мыслью+tool, совпадающие с transcript; reasoning
влияет на выбор tool (проверяется на golden).

---

### Спринт 4 — Evals как страховка (high, ∥ с 1–3) — ХВОСТ

Грейдеры-библиотека готова (`runtime/graders.py` +
`tests/test_agent_graders.py`), но это ещё **не** executable gate поверх
рантайма и **не** CI-блокер.

- [ ] Переделать `golden_runner` из спеки в **executable gate**: сейчас
      проверяет `implemented=bool(matches)` (наличие .md), а не поведение
      рантайма. Прогонять реальный run и ассертить исход.
- [ ] 3 executable-сценария поверх рантайма (19 .md уже описаны): multi-turn
      deixis, notes-with-content, empty-pack refusal. Грейдеры уже есть —
      привязать `grade_run` к прогонам.
- [ ] LLM-judge groundedness — после калибровки.
- [ ] **CI-gate:** critical golden нельзя merge при fail.
      Файлы: `tests/golden_runner.py`, `tests/test_golden_catalog.py`,
      `.github/workflows/*`.

**Exit:** PR не зелёный без grounding + multi-turn goldens.

---

### Спринт 6 — Trust boundary (high, НЕ откладывать)

Единственный пункт выше «косметики». Нужен **до того, как систему увидят
реальные данные пользователей** — сейчас безопасность ≈ 0 (`test_agent_security.py`
про медиа, не про injection).

- [ ] Retrieved текст (посты/заметки/вложения) инжектится в планнер и answer
      **сырым, как доверенный** → indirect prompt injection. Обернуть как
      untrusted-контент (делимитация + инструкция «это данные, не команды»).
- [ ] Минимальный бюджет на run: сейчас только `max_steps=4`, нет лимита
      токенов/стоимости/времени.
      Файлы: `research/pack.py` (`build_evidence_pack`), `research/graph.py`
      (инжект в planner), `runtime/executor.py` (бюджет).

---

### Спринт 5 — Observability прод (medium)

- [ ] Persist `planner_decisions` + tool outcomes в `agent_events`
      (`RuntimeContext.emit_event`/`audit` объявлены, но не вызываются).
- [ ] Метрики: empty-pack rate, finish-without-content на content-вопросах,
      шаги/токены/латентность на run.
- [ ] Tracing (AI_CONTEXT_LOG / LangSmith) на agent path.
      Файлы: `runtime/context.py`, узлы `workspace_graph.py`,
      `runtime/observability.py`.

**Exit:** по любому прод-run можно ответить «почему агент так решил» из логов.

---

## Хвост Спринта 1 (не блокер, но незакрыто)

- [ ] **1.4 tool observation → first-class.** `notes=1` и т.п. должны попадать в
      evidence/контекст следующего шага, а не только в summary tool'а (answer
      видит pack, не transcript). Файлы: `research/graph.py`
      (`_execute_tool`), `research/pack.py`.
- [ ] **Мёртвая проводка** из аудита: `finish_retrieval`, `repair_count`
      (проверить что инкрементится → repair-петля живёт), `research_transcript`
      — свериться, что после §1.1–1.5 они реально задействованы.

---

## Рекомендованный порядок (по канону)

```
[✅ Спринт 0 → 1.0 → 1.1–1.5]  ← сделано (кроме хвоста 1.4)
      ↓
[🟡 Спринт 2 (Память: dialog_context, thread_id=run_id)]  ← 2.1/2.3 сделаны, 2.2 не проверен
      ↓
Спринт 3 (Планнер мыслит + SSE)                        ← «работает как надо»
      ↓ (Спринт 4 идёт параллельно)
Спринт 4 (Evals executable + CI gate)                  ← регрессы под контролем
      ↓
Спринт 6 (Trust boundary, high) → Спринт 5 (Observability)
      ↓
Reference-level DoD
```

**Минимум «система работает как надо»:** Спринт 2 + 3 (1.0 и 1.1–1.5 уже готовы).
**Минимум «эталонная инженерная система»:** + Спринт 4 + 6.

---

## Открытые решения (нужно подтверждение)

1. ~~**Спринт 2 — thread_id.**~~ Закрыто: `thread_id` остаётся `run.id`
   (обоснование — §2.3 выше).
2. **Спринт 2 — post-scope chat matching.** `AgentRun` не имеет
   `post_chat_id`; `load_run_history()` матчит `run.chat_id` на `id` внутри
   `post.data["chats"]`, а без совпадения берёт последний чат поста. Нужно
   подтвердить: это верная эвристика, или клиенту нужно начать передавать
   `post_chat_id` в `StartAgentRunRequest`?
3. **Спринт 4 — CI.** К какому CI привязать merge-gate (GitHub Actions?);
   сейчас привязки к конфигу нет.
4. **Спринт 3 — schema.** Фиксируем формат решения
   `{observations, reasoning, gap, tool, args}` или расширяем?

---

## Что канон сознательно НЕ обещает

- Полноценный «ИИ-менеджер» после Спринтов 1–3 — там узкий агент: чтение +
  предлагать мутации/медиа через HITL. Управленческие полномочия — рост tool
  surface отдельными итерациями поверх чистого скелета.
- Автономные мутации без подтверждения — публикация/удаление/трата денег всегда
  через HITL. Это инвариант, не временное ограничение.
- Ledger/resolver/multi-agent/LLM-critic на каждый шаг — сложность только по
  измеренной необходимости.
