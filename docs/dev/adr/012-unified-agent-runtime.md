# ADR-012: Unified LangGraph Agent Runtime

## Статус
✅ **Принято** — единый durable runtime для research, post actions и media jobs.

> Supersedes orchestration/routing части [ADR-009](009-dialog-evidence-ledger.md) (resolvers,
> referent router) и расширяет [ADR-011](011-langgraph-rag.md) до полного workspace agent.
> Сохраняет: L0/L1, indexing, dialog evidence ledger, graph read tools, Tier A fast-path.

## Контекст

Платформе нужен один предсказуемый agent runtime вместо:
- legacy L2 (`rag_agent.py` + brief/router/plan/stop evaluator);
- монолитного reply SSE без durable runs;
- прямых post PATCH из будущих agent tools;
- отсутствующего media job слоя.

## Решение

### Единый WorkspaceAgent

```
CreateAgentRun → BootstrapContext → WorkspaceAgent
  ⟷ ReadToolNode (research subgraph)
  → VerifyEvidence → BuildEvidencePack → AnswerModel → PersistLedger
  → ActionProposal → interrupt → DeterministicExecutor
  → MediaProposal → cost interrupt → Celery job → attach interrupt
```

- **Один** автономный LLM-компонент — `WorkspaceAgent`.
- Research, actions, media — subgraphs/workflows с отдельными State-контрактами.
- Conditional edges смотрят только на **тип валидированного tool call** (`read`, `finish`, `post_proposal`, `media_proposal`).
- Модель видит read/propose tools; никогда не получает raw DB patch, API keys или storage paths.

### Durable execution

| Слой | Роль |
|------|------|
| LangGraph PostgreSQL checkpointer | execution state, interrupt/resume |
| `agent_runs` | продуктовый status/snapshot |
| `agent_events` | monotonic SSE + audit |
| `dialog_evidence_turns` | semantic cross-turn memory (ADR-009) |

`AsyncSession`, provider clients и secrets живут в `RuntimeContext`, не в graph state.

### HITL policy

| Действие | Approval |
|----------|----------|
| Любая post mutation | Обязательный `ActionProposal` + hash + resource version |
| Media generation | Cost approval → job → attach approval |
| Research / draft rewrite | Без HITL (transient state) |

### Feature flags

| Flag | Значения | Default |
|------|----------|---------|
| `AGENT_RUNTIME_ENGINE` | `legacy` \| `langgraph` | `langgraph` |
| `RAG_L2_ENGINE` | `legacy` \| `langgraph` | `langgraph` |
| `AGENT_ACTIONS_ENABLED` | bool | `false` |
| `AGENT_MEDIA_ENABLED` | bool | `false` |

## Модульные границы

```
backend/app/services/agent/
  runtime/     — graph factory, State, runs, events, SSE
  research/    — prefetch, read tools, verifier, evidence pack
  actions/     — proposals, policy, executors
  media/       — jobs, assets, providers
backend/app/services/posts/commands/  — typed mutations (REST + agent)
```

## Запреты

- Supervisor / multi-agent hierarchy без измеримого bottleneck.
- `lane_router`, referent types, keyword intent flags, plan alignment.
- DB session / secrets / bytes в graph checkpoint.
- Post mutations без proposal boundary.
- Polling media job внутри graph process.
- Generated assets в JSONB / data URL.

## Baseline metrics (legacy L2, pre-migration)

| Метрика | Типичное значение |
|---------|-------------------|
| L2 LLM calls / request | 4–11 |
| L2 latency p50 | ~3–8 s |
| Retrieval coverage (golden 03/04/13/16) | partial — planner gaps |
| Error rate (agentic mode) | elevated on multi-evidence |

Целевые пороги после миграции: ≤4 agent calls, parity или лучше на golden 01–16, zero cross-tenant leaks.

## Последствия

- `backend/app/api/v1/ai.py` — transport/facade; orchestration в `agent/runtime`.
- Новые таблицы: `agent_runs`, `agent_events`, `action_proposals`, `media_jobs`, `media_assets`, `agent_audit_events`.
- Frontend: agent-run store, `AgentProposalCard`, `MediaJobCard`, typed SSE rehydration.
- Legacy L2 modules удаляются после canary (фаза 3).

← [ADR-011](011-langgraph-rag.md) · [Каталог RAG](../rag-pipeline/README.md)
