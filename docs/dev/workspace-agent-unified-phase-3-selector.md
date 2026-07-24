# Единый план: фаза 3 — один полный Context Selector

**Статус:** завершена 2026-07-24
**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фаза 2

## Цель

Убрать смешение visibility и relevance и оставить один проверяемый semantic
decision между discovery и materialization.

## Реализация

1. Расширить selector schema до assessments всех visible refs и source
   dispositions.
2. Превратить candidate registry в typed `CandidateEnvelope` с `origin`,
   nullable `semantic_score`, parent, source IDs и available fidelity.
3. Сохранить ambient candidates в registry отдельным inclusion rule.
4. Удалить второй semantic assessment path: action planner не переоценивает
   те же candidates после Selector.
5. Детерминированно проверить:
   - каждый visible ref оценен ровно один раз;
   - неизвестные и duplicate refs отклонены;
   - `irrelevant` не materialize-ится;
   - role/resolution согласованы;
   - source disposition согласуется с assessments;
   - cardinality соблюдена.
6. Заменить select-all fallback на exact-only + bounded retry + explicit gap.
7. Для complete semantic source не менять `irrelevant` на `direct`: complete
   относится к исследованию и assessment корпуса.
8. Для structural source Selector не вызывается.

## Безопасный fallback

При timeout/schema error:

- сохранить authoritative exact targets;
- не добавлять ambient/semantic candidates без положительного assessment;
- разрешить один bounded retry;
- после retry вернуть `selector_failed`/partial gap;
- не выбирать слабый hit ради source representation.

## Основные файлы

- `backend/app/services/agent/research/planner_decision.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/material_plan.py`;
- `backend/app/services/agent/research/prefetch.py`;
- `backend/app/services/ai/rag_tools.py`;
- selector schema, replay и fallback tests.

## Тесты

- relevant/irrelevant ambient note;
- no_relevant_candidate для required discovery с `min=0`;
- optional source не блокирует ready;
- invalid JSON и duplicate refs;
- parent post виден, но не materialize-ится автоматически;
- semantic complete оценивает весь corpus batch-ами;
- exact target сохраняется при Selector failure.

## Exit criteria

- `fallback_select_all_rate=0`;
- `required_source_forced_selection_rate=0`;
- один semantic LLM call на registry pass;
- assessment completeness проверяется без semantic эвристик в Python;
- baseline relevant recall не ухудшился.

## Откат

Выключить `unified_selector`; вернуть предыдущий selector projection только для
shadow comparison. Не смешивать новый assessment schema со старым select-all
fallback в одном enabled path.

## Результат

- добавлен canonical `workspace.context-selector/v2`: Selector возвращает
  assessment каждого visible ref и ровно один disposition каждого видимого
  semantic source;
- schema запрещает duplicate refs/source dispositions, unknown refs проверяет
  deterministic runtime validation, а `irrelevant` допускает только
  `role=none`/`resolution=none`;
- candidate registry использует `workspace.candidate-envelope/v1` с отдельными
  `origin`, `inclusion_priority`, nullable `semantic_score`, множественными
  `source_requirement_ids`, parent metadata и `available_fidelity`;
- exact, ambient и authoritative-catalog candidates включаются независимо от
  semantic score; query-specific score остается только у
  `origin=semantic_search`;
- enabled path не вызывает Selector для exact targets и pure structural
  sources; parent relation остается metadata и не создает selection;
- complete semantic registry хранит до 100 refs и оценивается Selector-партиями
  до 16 refs без повторной semantic оценки action planner-ом;
- invalid JSON, schema error и provider timeout допускают не больше одного
  retry; hard run deadline не ретраится; после отказа сохраняются exact targets,
  discovery refs не materialize-ятся и создается typed `selector_failed` gap;
- `_required_source_fallback_decision` и select-all projection недоступны при
  включенном unified Selector; `no_relevant_candidate` не повышает слабый hit до
  evidence;
- legacy positive-selection schema остается только в default-off rollback path.

## Проверки

```bash
cd backend
.venv/bin/pytest -q \
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

Расширенный набор: `368 passed, 1 warning`; warning `fastembed` про смену pooling
существовал до фазы. Phase-0 replay дважды вернул прежний digest
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`,
protected fixture hashes не изменились.

На phase-3 replay/failure fixtures:

- `fallback_select_all_rate=0`;
- `required_source_forced_selection_rate=0`;
- `selector_relevant_precision=1.0`, `selector_relevant_recall=1.0` для
  размеченных phase-3 replay decisions;
- один semantic Selector call на успешный registry pass; invalid/timeout path
  делает ровно один дополнительный bounded retry;
- structural/exact bypass не добавляет Selector call.

Phase-0 report намеренно продолжает показывать исторические near-miss значения
старого default-off path; он является safety freeze, а не phase-3 shadow
telemetry. Production/shadow метрики enabled path относятся к фазе 6.

## Exit criteria

- [x] `fallback_select_all_rate=0` на enabled-path failure fixtures;
- [x] `required_source_forced_selection_rate=0` и truthful
  `no_relevant_candidate` не создает materialization action;
- [x] один semantic LLM call на registry pass, кроме одного явно ограниченного
  schema/timeout retry;
- [x] assessment completeness, duplicate/unknown refs, dispositions и
  cardinality проверяются детерминированно без Python relevance heuristics;
- [x] baseline replay digest, protected fixtures и relevant regression suite не
  ухудшились.

## Остаточные риски

- fidelity floor, budget до hydration, `search_more` compilation и final
  EvidencePack membership остаются фазой 4; фаза 3 сохраняет requested
  resolution/disposition только в минимальной совместимой projection;
- authoritative registry больше 100 refs, paging и additive search для complete
  semantic source относятся к фазе 5; текущие Selector batches не заменяют
  authoritative paging;
- production precision/recall, latency/token telemetry, shadow comparison,
  canary/default-on и удаление legacy rollback projection относятся к фазе 6;
- flag `AGENT_UNIFIED_SELECTOR_V1_ENABLED` остается default-off и включается
  только вместе с typed v3 contract и phase-5 runtime до rollout фазы 6;
- post-pack fidelity/coverage и hydration failures намеренно не исправлялись и
  остаются риском фазы 4.
