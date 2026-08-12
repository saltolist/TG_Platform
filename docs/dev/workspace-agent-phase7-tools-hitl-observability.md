# Workspace Agent phase 7: tools, HITL resume and observability

Phase 7 adds production-facing contracts on top of the phase-6 checkpoint and
EvidencePack. Legacy tool names remain accepted for rollout compatibility, but
task-oriented batch tools now share one typed outcome envelope.

## Implemented

- Consolidated adapters: `ResolveObjects`, `SearchObjects`, `OpenObjects`,
  `SearchObjectChunks`, `HydrateAttachments`, `ReadAnalytics` and
  `ProposeAction`. Independent objects can be opened/hydrated in one planner
  decision; response mode is `compact` or `detailed`.
- `ToolOutcome` retains the legacy `error` string and adds stable
  `error_code`, `retryable`, `next_action`, `result_count`, `cache_hit`,
  `response_mode` and `duration_ms`. Ledger cache hits are observable and do
  not call an external provider.
- HITL interrupts persist a `resume_state` reference containing contract
  revision, target IDs, evidence IDs and a short fingerprint. Resume rebuilds
  the runtime context from the interrupted snapshot instead of creating a new
  target contract from dialog history.
- `workspace.run-metrics/v1` includes execution mode, warm/cold worker state,
  queue/approval wait and phase timings. Durable traces render these metrics and
  typed tool errors without exposing private prompts or chain-of-thought.
- `runtime/replay.py` compares exported old/new event chains. Grafana panels
  and Prometheus alerts cover mode/warm p95, phase p95, typed tool errors and
  cold-run tail.

## Quality and latency fixture

```bash
cd backend
PYTHONPATH=. .test-venv/bin/python scripts/agent_phase7_trace_report.py --check
```

The deterministic fixture keeps quality, targets and evidence at `100%`. It
reports consolidated-tool reductions and latency reductions against the
phase-6 control-flow baseline; it is a replay/control-flow estimate, not a
production SLO. Production rollout must replace it with anonymized trace export
and cold/warm canary data.

## Exit criteria

| Criterion | Result |
|---|---|
| approval/resume keeps targets and evidence | `resume_state` fingerprint, persisted snapshot contract and resume tests |
| slow run decomposes into phase timings | `run_metrics` schema, phase histogram and trace renderer |
| tool errors give a valid next step | typed error map and consolidated adapters |
| dashboards separate cold/warm and execution mode | Grafana `workspace-agent-runtime` dashboard and Prometheus alert rules |
| trace replay and old/new comparison | `runtime/replay.py`, phase-7 report script and fixture tests |

## Risks and handoff to phase 8

- Phase timings are reconstructed at graph update boundaries and include event
  persistence overhead; provider-native spans should refine them before strict
  SLO enforcement.
- Provider cache-hit token metadata is still unavailable from the text adapter.
- Batch adapters currently execute sequentially inside a single tool state;
  phase 8 can add bounded parallelism after benchmark corpus and DB indexes are
  measured.
- Grafana/Prometheus assets are provisioned but require a running ops stack and
  real series before alert thresholds can be tuned.
- Existing `test_agent_listing.py` remains a pre-phase-7 quality gap: its
  legacy listing-as-primary expectation conflicts with the enabled typed
  phase-5/6 evidence contract. It should be resolved before rollout, without
  weakening the primary-evidence rule.
- The phase-7 fixture is synthetic. Phase 8 handoff is a 1000+ object corpus,
  query-plan/index benchmark, and interactive-vs-batch load test.
