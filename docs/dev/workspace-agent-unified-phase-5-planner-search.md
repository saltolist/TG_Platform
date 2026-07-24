# Единый план: фаза 5 — plan decision, additive search и structural fast path

**Статус:** завершена 2026-07-24
**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фазы 2–4

## Цель

Исправить политику planner/search, не добавляя второй planner loop и не отключая
полноту authoritative catalog.

## Plan decision

Для каждого factual read существует traceable decision:

- `USE_FAST_PATH` для однозначного structural/exact запроса;
- action-planner call при semantic predicate, ambiguity, multi-source, depth
  choice, typed gap или `search_more`.

Planner не может ослабить `coverage`, fidelity или evidence requirements.
Повторный вызов разрешен только если появились новое evidence или новый gap.
Измеряются `planner_noop_rate`, evidence delta, выбранные actions и влияние на
итоговый pack.

## Additive semantic search

При complete source:

- catalog задает authoritative object set;
- search только добавляет fragments, ranking, related candidates и приоритеты;
- top-k не исключает object из complete discovery/assessment set;
- для чистого structural запроса search может быть пропущен явным fast-path
  решением.

## Structural path

Для `notes.has_images` planner не считает по тексту и не открывает случайную
semantic note:

```text
typed requirement
  -> complete note catalog
  -> backend aggregate
  -> matching refs + totals
  -> verifier
```

Для mixed запроса сначала применяется deterministic structural predicate, затем
Selector только к кандидатам, которым нужна semantic classification.

## Post image semantics

Не использовать неоднозначное одно поле «post has images». В contract/answer
разделять direct media, images in notes, number of notes with images и union
posts-with-any-images. Если пользовательская формулировка не уточняет область,
ответ должен явно показать разделенные показатели, а не выбрать один молча.

## Основные файлы

- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/planner_decision.py`;
- `backend/app/services/agent/research/search_ledger.py`;
- `backend/app/services/agent/research/sufficiency.py`;
- `backend/app/services/agent/runtime/observability.py`;
- `backend/app/services/agent/runtime/graders.py`;
- planner no-op, additive-search и structural fast-path tests.

## Тесты

- planner не вызывается для deterministic structural fast path;
- semantic complete search не уменьшает catalog set;
- planner gap закрывается aggregate action;
- no-op planner виден в metrics;
- `FINISH_READY` блокируется при unresolved property gap;
- direct/nested/union post image counts.

## Exit criteria

- ordinary compact flow не получает дополнительный LLM call без необходимости;
- structural count error rate равен нулю на fixtures;
- complete semantic recall не хуже baseline;
- search trace показывает additive relation к catalog.

## Откат

Выключить `planner_policy`; оставить typed gaps и aggregates в shadow mode.
Semantic search продолжает работать по старому path, но authoritative complete
catalog не отключается.

## Результат

- `workspace.plan-decision/v1` трассирует deterministic `USE_FAST_PATH`, один
  `CALL_CONTEXT_SELECTOR`, typed action-planner decision, `FINISH_READY` и
  `PLANNER_NOOP`; durable semantic/materialization state по-прежнему записывают
  только `workspace.context-selector/v2` и `workspace.material-plan/v2`;
- state signature учитывает evidence revisions, typed gaps, coverage targets,
  catalog paging/property state и terminal discovery ledger; planner повторно
  вызывается только после delta, а повтор без delta завершается deterministic
  partial/no-op и отражается в Prometheus counters;
- `FINISH_READY` принимается только при `sufficiency.status=ready` без typed gap,
  incomplete coverage и pending intent; тот же invariant добавлен в grader;
- semantic search для complete semantic/mixed source выполняется после
  authoritative enumeration, записывает
  `search_relation=additive_to_authoritative_catalog`, добавляет rank/fragments,
  но не меняет discovery refs; complete registry до 256 refs оценивается одним
  Selector call, без прежнего semantic batching loop;
- structural aggregates и filter result sets вычисляются backend-ом до paging;
  `unknown` сохраняет `None`, а не становится `false`/`0`; verified pack получает
  `workspace.structural-result/v1` с aggregates, result sets и property coverage;
- post image projection раздельно содержит direct images, images in notes и
  union `posts_with_any_images`, поэтому пост с обоими видами учитывается в union
  один раз;
- mixed flow переносит typed structural filter перед единственным Selector и
  отдельно трассирует rejected и unknown refs;
- fast/exact/mutation compatibility fixtures сохраняют ноль дополнительных
  planner calls; rollout flag `AGENT_PLANNER_POLICY_V1_ENABLED` остаётся
  default-off до фазы 6.

## Проверки

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_agent_unified_phase5_planner_search.py \
  tests/test_agent_unified_phase4_materialization.py \
  tests/test_agent_unified_phase3_selector.py \
  tests/test_agent_unified_phase2_contract.py \
  tests/test_agent_unified_phase1_catalog.py \
  tests/test_agent_unified_phase0.py tests/test_agent_phase5_planner.py \
  tests/test_agent_adaptive_evidence_depth.py tests/test_agent_phase6.py \
  tests/test_agent_phase2_contract.py tests/test_turn_contract.py \
  tests/test_message_context_manifest.py tests/test_agent_runtime.py \
  tests/test_workspace_graph.py tests/test_rag_tools.py tests/test_agent_research.py \
  tests/test_rag.py tests/test_rag_query.py tests/test_rag_retrieval_policy.py \
  tests/test_agent_phase4_retrieval.py tests/test_agent_listing.py \
  tests/test_agent_e2e.py tests/test_config.py
.venv/bin/python scripts/agent_unified_phase0_report.py --repeat 2 --check
```

Связанный regression-набор: `393 passed, 1 warning`. Warning `fastembed` о смене
pooling существовал до фазы. Phase-0 replay стабилен на двух запусках,
digest `4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`,
protected fixtures не изменились.

## Exit criteria

- [x] ordinary compact и frozen fast/exact/mutation flows не получают
  дополнительный LLM call;
- [x] structural count/filter fixtures, включая 101-member paged catalog,
  проходят с нулевой ошибкой и без LLM;
- [x] complete semantic registry сохраняет все authoritative refs, а search
  только ранжирует/обогащает; 101-member case остаётся одним Selector call;
- [x] search ledger показывает равные discovery counts до/после additive search;
- [x] typed gap, incomplete assessment/coverage и pending bounded action блокируют
  `FINISH_READY`; planner no-op и state delta покрыты focused tests/metrics;
- [x] схемы/fixtures/verified boundary фаз 0–4 проходят regression без ослабления.

## Остаточные риски

- production shadow comparison, настройка latency/token budget для редких очень
  больших complete semantic corpora, canary и default-on остаются фазой 6;
- `AGENT_PLANNER_POLICY_V1_ENABLED` и остальные unified flags остаются
  default-off до rollout gate фазы 6; legacy rollback path намеренно сохранён;
- registry сверх bounded лимита 256 не объявляется complete: coverage gap
  детерминированно блокирует ready. Настройка/rollout этого operational bound
  относится к фазе 6, а не компенсируется вторым Selector loop.
