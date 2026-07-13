# Baseline metrics — legacy L2 (pre Unified LangGraph)

Зафиксировано на фазе 0 миграции ([ADR-012](adr/012-unified-agent-runtime.md)).

## Методология

- Источник: production-like traces + `test_rag_*` suite (219 tests).
- Сравнение после миграции: citations/evidence IDs, tool constraints, tenant isolation — **не** точная формулировка LLM.

## Legacy L2 orchestration

| Метрика | Baseline | Target (LangGraph) |
|---------|----------|-------------------|
| LLM calls до answer model | 4–11 | 1–4 |
| Deterministic pre-phases | brief + router + resolvers + plan + alignment + stop | prefetch + verifier |
| Multi-turn artifact (golden 13) | flaky — referent router | ledger in context pack |
| Combined content+analytics (16) | plan rejected loops | agent multi-tool |
| p50 L2 latency | ~3–8 s | ≤5 s |
| p95 L2 latency | ~12–25 s | ≤12 s |

## Runtime (pre-migration)

| Capability | Status |
|------------|--------|
| Durable agent runs | ❌ |
| Interrupt/resume SSE | ❌ (`{text}`/`{meta}` only) |
| Post HITL proposals | ❌ |
| Media jobs | ❌ |
| Private asset storage | config only |

## Canary gates (фаза 7)

- Golden 01–19 green on `RAG_L2_ENGINE=langgraph`
- No regression: retrieval coverage, cite paths, ledger entities
- Security: cross-tenant asset/post access = 0
- SSE reconnect with `Last-Event-ID` within 1 s of snapshot

### Rollout flags (docker-compose / env)

| Flag | Default | Enable for |
|------|---------|------------|
| `AGENT_RUNTIME_ENGINE=langgraph` | on | durable WorkspaceAgent runs |
| `RAG_L2_ENGINE=langgraph` | on | research subgraph in RAG |
| `AGENT_ACTIONS_ENABLED=1` | off | post mutation HITL proposals |
| `AGENT_MEDIA_ENABLED=1` | off | image/video generation jobs |

After enabling actions/media, restart `backend`, `celery-worker`, and ensure `minio` is up for private asset storage.
