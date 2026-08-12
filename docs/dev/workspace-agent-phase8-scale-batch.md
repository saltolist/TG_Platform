# Workspace Agent phase 8: scale and batch path

Phase 8 implements the last phase of
`workspace-agent-intelligence-performance-plan.md`. The source of truth is that
plan and the measured phase-8 report, not older ADRs.

## Implemented

- Migration `022_agent_batch_scale` adds transactional batch tables. Migration
  `023_retrieval_scale_indexes` separately adds a GIN discovery index over
  title, summary/context and keywords, plus a multi-model metadata index over
  user/tenant/model/scope/type/status/revision. Separating the migration makes
  both `CONCURRENTLY` builds restart-safe without partially committing tables.
- `agent_phase8_scale_report.py` creates an isolated tenant-like corpus with
  1000 posts, 1000 notes and two embedding models, checks recall and EXPLAIN,
  runs an 80% interactive / 20% batch DB mix, and removes the corpus.
- Exhaustive requests receive `task_profile=exhaustive_inventory` and
  `execution_mode=batch`. `AGENT_BATCH_PATH_V1_ENABLED=0` rolls routing back.
- `agent_batch_jobs` owns budgets, cursor and checkpoint;
  `agent_batch_items` materializes idempotent results. Each Celery invocation
  processes one keyset page and commits items with the cursor atomically.
- `agent-batch` has a dedicated route, worker service, concurrency 1 and
  prefetch 1. Batch workers skip interactive embedding warmup.
- Run APIs expose job progress and paginated items. Failed/paused jobs resume
  from the persisted cursor; cancelling a run also cancels its batch job.

## Profile limits

`runtime/profile_limits.py` is the versioned operational policy used by the
benchmark and batch budget enforcement.

| Profile | DB p95 | Max DB calls | Max LLM calls | Time-to-final p95 |
|---|---:|---:|---:|---:|
| exact lookup | 100 ms | 6 | 1 | 15 s |
| topical answer | 150 ms | 18 | 4 | 25 s |
| synthesis/recommendation/comparison | 200 ms | 24 | 4 | 25 s |
| artifact/profile/mutation | 150 ms | 16 | 4 | 25 s |
| exhaustive inventory | 250 ms/page | 256/job | 0 | offline |

Batch v1 is deliberately deterministic and spends zero LLM calls. It
materializes source metadata, revisions and bounded excerpts for later reads.

## Quality and latency

Command:

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  backend/scripts/agent_phase8_scale_report.py --check
```

Local PostgreSQL 16 result on the required 1000+1000 corpus:

| Metric | Seq-scan baseline | Phase 8 | Change |
|---|---:|---:|---:|
| recall@5 | 1.000 | 1.000 | 0 |
| FTS p50 | 10.536 ms | 0.889 ms | -91.6% |
| FTS p95 | 14.245 ms | 2.467 ms | -82.7% |

EXPLAIN used `ix_note_embeddings_discovery_fts` and
`ix_note_embeddings_retrieval_metadata`. In the 80/20 mix, interactive DB p95
was 14.236 ms, batch page p95 was 3.402 ms and errors were zero. The absolute
interactive p95 remains far inside the 150 ms topical DB budget; queue
isolation prevents batch jobs from consuming interactive worker slots.

HNSW was not added. Current embeddings are mixed-dimension `TEXT` values cast
to vector at query time, while lexical and metadata queries already meet the
DB SLO. Adding HNSW without a typed per-model vector layout and recall proof
would violate the phase criterion.

## Exit criteria

| Criterion | Result |
|---|---|
| Interactive SLO holds on benchmark corpus | Met: indexed p95 2.467 ms; mixed p95 14.236 ms vs 150 ms DB budget |
| Query plans use expected indexes | Met: both new index names appear in EXPLAIN ANALYZE |
| Batch does not consume interactive error budget | Met locally: separate queue/worker; mixed-load p95 inside budget, zero errors |
| HNSW only with proven advantage | Met: not added; current storage cannot support a valid index without redesign |

## Remaining risks and post-phase handoff

- Measurements are local PostgreSQL/DB load, not a production Celery/provider
  soak. Rollout must rebuild the worker image, start `celery-batch-worker`, and
  repeat the 80/20 mix against production-like CPU, pool and broker limits.
- The latest local 80/20 run measured 4.468x relative interactive p95 inflation
  against a 3.186 ms single-load baseline, while the mixed absolute p95 stayed
  at 14.236 ms versus the 150 ms budget. Production soak should gate on both
  absolute SLO and sustained error-budget impact, not this noisy local ratio alone.
- The index build is concurrent but still consumes I/O and leaves an invalid
  index if PostgreSQL terminates it. Deployment automation must inspect
  `pg_index.indisvalid` before enabling the flag.
- Batch v1 inventories primary user-owned posts and global notes. Presentation
  tenant overlays are not persisted on `AgentRun`; carrying tenant identity
  into durable runs is required before overlay-backed exhaustive jobs can be
  enabled.
- Materialized excerpts are bounded at 4000 characters. A later synthesis job
  must page the materialized rows and deep-read exact source revisions instead
  of treating excerpts as final evidence.
- HNSW reconsideration requires a per-model typed vector column/table, a stable
  dimension, EXPLAIN evidence, recall comparison and a measured vector-query
  bottleneck. The current result is an explicit defer, not blanket rejection.

The next work item after this plan is rollout validation: protected production
corpus replay, broker/Celery soak, canary error-budget observation and only then
removal of temporary phase flags/legacy planner paths. No rollout or later-phase
code is included here.
