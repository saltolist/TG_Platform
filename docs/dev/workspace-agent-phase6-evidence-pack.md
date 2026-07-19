# Workspace Agent phase 6: EvidencePack, output contracts and model separation

Phase 6 is enabled by `AGENT_ANSWER_PHASE6_ENABLED=1` (default `true`). The
flag can be disabled without changing checkpoint schemas; `rag_context` and the
planner `reasoner_*` fields remain compatibility paths.

## Implemented

- `workspace.evidence-pack/v1` is built only from selected, non-empty primary
  evidence. Discovery/search summaries are excluded, every selected object gets
  a bounded representation, and unresolved gaps/source ids are retained.
- The factual answer path receives only the typed pack rendered as fenced
  workspace data. Raw research transcript and dialog history are excluded.
- Planner and answer model bindings are separate. Planner uses the active
  `ragReasonerModels` model (with the existing orchestrator fallback); answer
  uses active `llmModels`, then orchestrator as compatibility fallback.
- `workspace.answer/v1` validates `answer` and `claims`. Citation ids must be a
  subset of the verified pack. One `answer.format_repair` is allowed, and it is
  accepted only when the original answer text is preserved exactly. Retrieval
  is never re-entered by format repair.
- Prompt modules retain the target/corpus, counting, id-hygiene and
  recommendation invariants while removing the old duplicated narrative
  prompt. Runtime metrics now expose a stable system-prompt cache key and
  cache-eligible token estimate; provider-reported cache hits remain `null`
  until the adapter exposes usage metadata.

## Fixture report

```bash
cd backend
PYTHONPATH=. .test-venv/bin/python scripts/agent_phase6_answer_report.py --check
```

The fixture is a deterministic control-flow estimate, not a production SLO.
It shows median answer input tokens falling from 1,385 to 590 (`-57.4%`), p95
from 2,200 to 960 (`-56.4%`), and estimated answer p95 from 2,200 ms to 1,300
ms (`-40.9%`). Grounded-claim rate, output schema compliance and answer-model
path rate are all `100%` in the fixture.

## Exit criteria

| Criterion | Result |
|---|---|
| selected user answer model is on answer path | Implemented and covered by `test_agent_phase6.py`; fixture 100% |
| factual claims have valid evidence | Deterministic `workspace.answer/v1` citation subset gate; fixture 100% |
| output schema compliance >=99% | Pydantic schema + one format-only repair; fixture 100% |
| answer input tokens decrease without completeness regression | Typed pack excludes summaries/transcript and bounds each item; phase-6 fixture reports -57.4% median input tokens; existing golden quality floor remains green |

## Risks and handoff to phase 7

- Provider cache hit tokens are not yet returned by the streaming adapter; only
  a stable cache key and eligible-token estimate are measured. Phase 7 should
  add usage metadata and dashboards.
- The fixture uses estimated durations. A canary must capture cold/warm p50/p95,
  answer input/output tokens, repair rate and groundedness on the held-out set.
- Empty claims remain allowed for compatibility when a model makes no explicit
  factual claim. If product policy requires claim-per-sentence coverage, add a
  profile-specific completeness gate in phase 7 rather than forcing it globally.
- The phase-6 flag preserves legacy rendering but should be removed after the
  phase-7 rollout and trace replay prove the typed pack is stable.
