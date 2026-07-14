# План доведения WorkspaceAgent до эталонного уровня

Документ фиксирует согласованный план досборки agent runtime path (`POST /ai/runs/`) до production-grade agentic RAG. Основан на:

- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic — Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [LangGraph Memory](https://docs.langchain.com/oss/python/langgraph/memory), [durable execution / HITL](https://github.com/langchain-ai/langgraph)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (sessions, guardrails, tool loop)
- [LangSmith RAG groundedness / trajectory evals](https://docs.langchain.com/langsmith/evaluate-rag-tutorial)
- SoK / surveys по Agentic RAG (verification in loop, when-to-stop на evidence)

Единого «ISO эталона» нет. Эталон для нашего класса систем = **инварианты production agentic RAG** из первоисточников, а не «побольше LLM».

Связанные документы: [ADR-012](adr/012-unified-agent-runtime.md), [ADR-009](adr/009-dialog-evidence-ledger.md), [agent-baseline-metrics.md](agent-baseline-metrics.md).

---

## Текущее состояние (кратко)

| Слой | Статус |
|------|--------|
| Durable runs, LangGraph, HITL, read tools | ✅ skeleton ~70% эталона |
| Memory (history + ledger) в agent path | ❌ не подключено |
| Grounding / sufficiency gates | ❌ verifier слабый, answer на пустом pack |
| Tool surface (ListPostNotes и др.) | ❌ частично |
| Planner observability | ❌ только `step_count` в SSE |
| Evals на multi-turn / anti-hallucination | ❌ не gate |

**Провалы в чате** (например `e09639bc-…`) — не «LangGraph не работает», а разрыв wiring + enforcement.

---

## Definition of Done (эталон)

Система считается на reference-level, если одновременно:

1. **Groundedness** — любой фактический claim в ответе либо из `rag_context`, либо честный отказ. LangSmith: *response vs retrieved docs*.
2. **Multi-turn memory** — follow-up («они», «внутри») резолвится без угадывания. LangGraph: short-term (thread history) + long-term store (ledger).
3. **Tool loop с ground truth** — решение на каждом шаге опирается на tool observation. Anthropic: *ground truth from the environment* после каждого tool call.
4. **Transparency** — в UI/SSE видны реальные решения planner'а (tool + rationale), не косметика. Anthropic principle #2.
5. **Evals** — golden tasks + trajectory + groundedness graders зелёные; regressions ловятся в CI.

---

## Фаза 0 — Baseline (1–3 дня)

**Цель:** зафиксировать эталонные провалы до правок.

| Работа | Зачем |
|--------|-------|
| Сохранить traces багов (multi-turn deixis, notes content, empty pack) как golden fixtures | LangSmith checklist: review real traces first |
| Deterministic graders: `answer claims ⊆ evidence`, `empty pack ⇒ no factual claim` | Anthropic evals: prefer deterministic graders |
| Trajectory eval: must-call tools на task (notes-content → `OpenNote`) | LangSmith trajectory `superset` |

**Exit:** failing suite на текущем runtime; после фаз — зелёная.

---

## Фаза 1 — Memory (критично)

**Источники:** LangGraph Memory; OpenAI Sessions; ADR-012 (ledger).

### 1.1 Short-term memory в каждый run

- При старте `execute_agent_run`: загрузить chat history server-side (`global_chats` / post chat).
- Собрать `dialog_context` (`build_planner_dialog_context`) и передать в research + answer.
- Не полагаться на клиент (кроме overlay/MSW).

**Файлы:** `backend/app/tasks/agent_runs.py`, `backend/app/services/agent/runtime/executor.py`, опционально `StartAgentRunRequest`.

### 1.2 Semantic / episodic cross-turn memory

- `load_ledger` перед research; `append_turn` после успешного research (как в legacy `rag_query`).
- Seed hydrated attachments из ledger — уже есть; заработает после write.

**Файлы:** `agent_runs.py`, `research/graph.py`, `rag_dialog_ledger.py`.

### 1.3 Thread / checkpoint isolation

- Research checkpoints на `run_id` (или `thread_id=chat` + `ns=run`), **не** на `user_id` с пустым `checkpoint_ns`.
- Иначе run'ы одного пользователя смешиваются в checkpointer.

**Файлы:** `research/graph.py` (`checkpoint_ns`), проверка таблицы `checkpoints`.

**Exit:** «2 поста → про что они?» отвечает по содержимому постов без галлюцинации.

---

## Фаза 2 — Agent–Computer Interface (tools)

**Источник:** Anthropic *ACI / Writing tools* — poka-yoke, when-to-call, actionable errors.

| Работа | Почему |
|--------|--------|
| Подключить `ListPostNotes` в `READ_TOOLS` + описание *когда* вызывать | Полный tool surface |
| Унифицировать evidence IDs (`post:` / `note:` / record keys) end-to-end | Finish IDs = records |
| Dedup / already-visited → actionable error («already have X; next: OpenNote») | Не мёртвый loop |
| Tool outcomes → first-class observation для следующего planner step | Ground truth each step |
| Truncate больших tool outputs + hint «запроси OpenNote» | Context-efficient tools |

**Не делать:** жёсткий скрипт tool path на все вопросы (Anthropic: complexity only when measured).

**Файлы:** `research/graph.py`, `rag_tools.py`, `verifier.py`.

**Exit:** transcript `ListPosts → OpenPost/ListPostNotes → OpenNote` на notes-content; post `3` notes=0 не утверждается как «есть заметка».

---

## Фаза 3 — Control policy: when sufficient / when answer

**Источники:** Agentic RAG SoK (verification in loop); Anthropic evaluator–optimizer; LangSmith groundedness.

### 3.1 Sufficiency / Finish gate

- `FinishRetrieval(ready)` валидировать **детерминированно**:
  - все `evidence_ids` ∈ records;
  - content non-empty там, где нужен текст;
  - иначе `partial` или repair, **не** answer.
- Policy metadata vs content — в verifier, не «всегда OpenNote».

### 3.2 Answer guard

- Empty `rag_context` + factual question → отказ / re-research.
- Prompt «только по evidence» недостаточен — нужен **code gate**.

### 3.3 Evaluator–optimizer (узко)

- Repair hint конкретный; max 1–2 repair; затем честный `partial`.
- Отдельный critic agent не нужен без measured gain.

**Файлы:** `verifier.py`, `research/pack.py`, `workspace_graph.py` (`research_node`, `answer_node`).

**Exit:** run с пустым pack **никогда** не отдаёт выдуманный текст; grader groundedness = pass.

---

## Фаза 4 — Transparency (настоящие «мысли»)

**Источники:** Anthropic principle #2; LangGraph streaming/events.

Structured decision (не essay):

```json
{
  "step": 6,
  "observations": ["ListPosts: post 721 notes=1", "ListPosts: post 3 notes=0"],
  "gap": "note content missing",
  "tool": "OpenNote",
  "args": {"note_id": "...", "post_id": "721..."}
}
```

| Работа | Зачем |
|--------|-------|
| Обязательное поле decision в planner JSON | decisions = real choices |
| Append-only `planner_decisions[]` | полный план 1…N |
| `agent_events` / SSE `planner_step` | UI видит то же, что рантайм |
| Optional: validate observations ⊂ transcript | anti-cosmetic |

**Файлы:** `research/graph.py`, `executor.py`, `sse_events.py`, frontend `agentRuns.ts` / composer.

**Exit:** в UI по run видны шаги 1…N с tool+gap, совпадающие с checkpoint transcript.

---

## Фаза 5 — Separation of concerns

| Уже есть | Дособрать |
|----------|-----------|
| WorkspaceAgent → research / finish / proposals | Answer только после pack |
| HITL mutations | OK |
| | `finish` без read — только для non-factual |

Не плодить multi-agent/supervisor без метрик (Anthropic).

---

## Фаза 6 — Evaluation harness

**Источники:** Anthropic Demystifying evals; LangSmith Agent Evaluation checklist.

### Offline

1. Golden 01–19 + новые: multi-turn deixis, notes-with-content, empty-pack refusal.
2. Deterministic: evidence ⊆ answer claims; trajectory must-include tools.
3. LLM-judge groundedness — после calibration.

### Online

- Sample production traces; annotate failures; feed datasets.

### Regression gate

- CI: critical golden нельзя merge при fail.

**Exit:** PR не зелёный без grounding + multi-turn goldens.

---

## Фаза 7 — Observability production

| Работа | Приоритет |
|--------|-----------|
| Persist planner_decisions + tool outcomes в `agent_events` | обязателен |
| AI_CONTEXT_LOG / LangSmith tracing на agent path | высокий |
| Метрики: empty pack rate, finish-without-OpenNote на content Q | высокий |

---

## Порядок и зависимости

```
Phase 0 (Baseline evals)
    ↓
Phase 1 (Memory)
    ↓
Phase 2 (Tools ACI)
    ↓
Phase 3 (Sufficiency + Answer guard) ──→ Phase 6 (Expand goldens)
    ↓
Phase 4 (Planner decisions + SSE) ──→ Phase 7 (Ops metrics)
    ↓
Reference-level DoD
```

| Фаза | Оценка | Риск без неё |
|------|--------|--------------|
| 0 | 1–3 д | Не знаете, что «готово» |
| 1 Memory | 3–5 д | Multi-turn всегда ломается |
| 2 Tools ACI | 3–5 д | Planner не дочитывает notes |
| 3 Gates | 3–5 d | Галлюцинации при пустом pack |
| 4 Transparency | 3–5 д | Нет доверия / отладки |
| 6 Evals | 5–8 д (параллельно) | Откаты «улучшений» |
| 7 Ops | 2–3 д | Слепо в проде |

**Минимум для эталонного UX:** фазы **1 + 2 + 3**.  
**Минимум для эталонной инженерной системы:** + **4 + 6**.

---

## Маппинг решений → фазы

| Решение | Фаза |
|---------|------|
| `dialog_context` + `load_ledger` / `append_turn` | 1 |
| Evidence ID contract + hard verifier | 2–3 |
| Sufficiency / empty pack refuse | 3 |
| `ListPostNotes` + dedup hints | 2 |
| Checkpoint isolation | 1 |
| `PlannerDecision` + SSE | 4 |
| Golden multi-turn + anti-hallucination | 0, 6 |

---

## Что сознательно НЕ входит

| Идея | Почему нет |
|------|------------|
| Жёсткий path ListPosts→OpenNote для всех | Anthropic: flexibility + eval, не script |
| Supervisor / multi-agent | Simple compositions first |
| Post-hoc «мысли» без связи с tool | Косметика |
| LLM-critic на каждый шаг | Complexity without measured gain |
| Копировать ReAct Thought verbatim | Structured decision + gate |

---

## Итог

Эталон = закрытый контур:

**memory → tools with usable observations → decide → verify sufficiency → answer only from evidence → log decisions → eval.**

Скелет LangGraph/HITL уже на уровне индустрии. Дыры — wiring памяти, ACI tools, answer guard, decision records, evals.

---

## Следующие PR (ориентир)

1. **PR1:** Memory + checkpoint isolation (Phase 1)
2. **PR2:** Tools ACI + evidence IDs (Phase 2)
3. **PR3:** Verifier + answer guard (Phase 3)
4. **PR4:** PlannerDecision + SSE + UI (Phase 4)
5. **PR5:** Golden suite + CI gate (Phase 0/6)
