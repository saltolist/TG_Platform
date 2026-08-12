# Единый план: фаза 4 — policy compiler, hydration и final EvidencePack

**Статус:** завершена 2026-07-24
**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фазы 1–3

## Цель

Сделать границу между semantic decision и final EvidencePack детерминированной,
дешевой и проверяемой.

## Policy compiler

Compiler получает только typed Selector decision и:

1. проверяет assessments и source dispositions;
2. исключает `irrelevant` до material plan;
3. применяет fidelity floor (`metadata < semantic_card < full_text < vision`);
4. сохраняет parent relations и canonical citation paths;
5. превращает `search_more` в bounded discovery action;
6. превращает `no_relevant_candidate` в exhausted/gap, а не в случайный selection;
7. формирует materialization queue только из direct/supporting refs;
8. записывает каждое runtime promotion/override в trace.

## Budget до hydration

До `OpenNote/OpenPost/HydrateAttachment` compiler обязан учитывать:

- max object count;
- max full-text chars;
- max card chars;
- required source priorities;
- deterministic batch order.

Для structural requests full text не нужен: в pack попадают catalog aggregate и
проверяемые matching items. Для semantic catalog до 8 объектов допустим full text
всех выбранных; большие corpora идут партиями.

## Final pack verifier

После упаковки проверяются:

- source ref, owner, status, revision;
- effective fidelity и hydration lineage;
- membership только compiled selections/structural result set;
- omissions/truncation;
- property coverage и aggregate consistency;
- `coverage_by_source`.

Если pack потерял значимый required item, он обязан стать `partial`/unresolved;
`complete` нельзя восстановить prompt-инструкцией.

## Основные файлы

- `backend/app/services/agent/research/material_plan.py`;
- `backend/app/services/agent/research/evidence_pack.py`;
- `backend/app/services/agent/research/evidence.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/runtime/message_context.py`;
- `backend/app/services/agent/research/sufficiency.py`;
- pack budget, provenance и hydration tests.

## Тесты

- selected card -> hydrated original с revision match;
- stale card promotion;
- hydration error без ложного full_text;
- pack truncation переводит coverage в partial;
- catalog link не гидратирует всех members;
- structural aggregate сохраняется при отсутствии full text;
- citation и evidence IDs остаются стабильными.

## Exit criteria

- ни один item pack не имеет необъяснимого происхождения;
- fidelity mismatch равен нулю;
- повторная проверка pack не меняет membership молча;
- DB reads не выполняются для объектов, которые заранее не помещаются в budget;
- existing answer/output schema проходит без изменений.

## Откат

Выключить `verified_pack_boundary`, оставить compiler и verifier в shadow mode.
Старый EvidencePack path остается активным только до прохождения фазы 6.

## Результат

- добавлен `workspace.material-plan/v2`: typed assessments из
  `workspace.context-selector/v2` компилируются без повторной semantic оценки в
  детерминированную `materialization_queue`;
- `irrelevant` исключается до queue, `no_relevant_candidate` создает только
  typed gap, `search_more` — не более одного bounded discovery action на source,
  а `ambiguous` и `selector_failed` не расширяют EvidencePack;
- exact target сохраняется при Selector failure отдельно от ambient/search
  candidates; parent relation остается provenance metadata;
- compiler применяет contract fidelity floor и до DB reads резервирует object,
  full-text и card budgets; legacy id lists являются compatibility projection
  queue, а каждое promotion/omission записывается в runtime trace;
- `OpenNote`, `OpenPost` и attachment hydration переносят в evidence фактическую
  revision, status и owner/scope verification lineage; vision не маркируется как
  обычный full text;
- final handoff гидратирует только compiled full-text refs и не разворачивает
  catalog members; catalog membership больше не считается автоматически
  supplied object context;
- post-pack boundary повторно проверяет membership, fidelity, hydration lineage,
  revision, owner/status provenance, omissions, truncation и per-source
  coverage; card promotion без verified original read отклоняется;
- прежние EvidencePack/output schema и catalog hydration сохранены в default-off
  rollback path под `AGENT_VERIFIED_PACK_BOUNDARY_V1_ENABLED=0`.

## Проверки

```bash
cd backend
.venv/bin/pytest -q \
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

Связанный regression-набор: `380 passed, 1 warning`, protected fixtures не
изменились; phase-0 replay дважды сохраняет digest
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`.
Единственный warning `fastembed` о смене pooling существовал до фазы.

## Exit criteria

- [x] каждый object item pack имеет compiled selection/exact/structural origin,
  source obligation, fidelity decision и provenance lineage;
- [x] fidelity mismatch отклоняется verifier-ом и равен нулю на phase-4 tests;
- [x] повторная проверка membership не добавляет catalog/ambient/irrelevant refs;
- [x] object/char budget формирует pending read queue до DB access;
- [x] truncation, hydration/revision failure и pack omission переводят coverage в
  `partial` и остаются в unresolved/coverage metadata;
- [x] существующие answer/output schema и default-off compatibility path проходят
  regression tests.

## Остаточные риски

- authoritative paging больше 100 refs, additive search для complete semantic
  source и planner policy остаются фазой 5; compiler не пытается компенсировать
  их повторной relevance оценкой;
- production telemetry, shadow comparison, budget/latency tuning, canary,
  default-on и удаление legacy catalog-hydration path остаются фазой 6;
- `AGENT_VERIFIED_PACK_BOUNDARY_V1_ENABLED` остается default-off до общего
  rollout gate; legacy path при выключенном флаге намеренно сохраняет прежнее
  раскрытие выбранного catalog для совместимости.
