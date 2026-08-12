# Единый план: фаза 2 — typed obligations и evidence requirements

**Статус:** завершена 2026-07-24

**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фазы 0–1

## Цель

Разделить обязательства источника и формально описать свойства, без которых
ответ нельзя считать complete.

## Новая модель

Добавить versioned projection с:

- `discovery_obligation`;
- `evidence_obligation`;
- `selection_cardinality.min/max`;
- `coverage` как discovery coverage;
- `predicate_kind=structural|semantic|mixed`;
- `required_fidelity`;
- typed `evidence_requirements` (`subject`, `property`, `operator`, `scope`).

Пример требования `notes.has_images` должен проверять не наличие `/notes/`, а
наличие catalog property и aggregate, содержащих этот признак.

## Compiler и adapter

1. Сохранить чтение `workspace.turn/v2`.
2. Нормализовать старые `required/min_evidence/evidence_granularity` в новую
   модель только на входе.
3. Новые planner/checkpoint decisions писать с новой schema version.
4. Parent relation создавать как locator metadata, не как evidence obligation.
5. Для structural requests строить deterministic fast-path decision.
6. Для semantic requests явно создавать typed gap, если catalog есть, но
   требуемое свойство/глубина отсутствует.

## Typed gaps

Каждый gap содержит:

```json
{
  "kind": "missing_property",
  "required": "notes.has_images",
  "evidence_present": "catalog_without_property",
  "allowed_actions": ["structural_aggregate", "open_notes"],
  "blocks_ready": true
}
```

Planner не может закрыть gap словами `FINISH_READY`; его может закрыть только
новое evidence, удовлетворяющее requirement.

## Основные файлы

- `backend/app/services/agent/runtime/turn_contract.py`;
- `backend/app/services/agent/runtime/workspace_graph.py`;
- `backend/app/services/agent/research/sufficiency.py`;
- `backend/app/services/agent/runtime/state.py`;
- contract fixtures и checkpoint compatibility tests.

## Тесты

- required discovery + `min=0` допускает no relevant candidate;
- required evidence + `min=1` блокирует отсутствие selection;
- parent corpus не становится required автоматически;
- structural property missing создает gap;
- complete semantic source требует assessment coverage, но не selection всех
  объектов;
- старые checkpoints корректно нормализуются.

## Exit criteria

- ни один verifier не использует голый `required` для принудительного выбора;
- все factual read имеют plan decision: fast path или typed planner decision;
- legacy и новый contract дают одинаковую стратегию на baseline fixtures;
- gaps видны в sufficiency и trace.

## Откат

Выключить `typed_requirements`; читать только compatibility projection. Новые
fields оставить optional в checkpoint, чтобы resume старых runs не ломался.

## Результат

- добавлен `workspace.turn/v3`, в котором source requirement независимо хранит
  `discovery_obligation`, `evidence_obligation`, `selection_cardinality`,
  discovery `coverage`, `predicate_kind` и `required_fidelity`;
- новые v3 decisions не сериализуют `required`, `min_evidence` и
  `evidence_granularity`; runtime accessors читают обе версии на переходном
  пути;
- typed `workspace.evidence-requirement/v1` содержит `subject`, `property`,
  `operator` и `scope`; structural requirements проверяются одновременно по
  catalog `provided_properties` и соответствующему backend aggregate;
- pure structural request получает `deterministic_fast_path`, semantic request
  — `typed_planner`, mixed structural/semantic predicate остается отдельным
  typed planner decision;
- `workspace.evidence-gap/v1` сохраняется в `sufficiency.gaps`, дублируется в
  checkpoint `evidence_gaps` и отображается в trace; `FINISH_READY` не закрывает
  blocking gap без нового evidence;
- complete semantic coverage проверяет assessment каждого authoritative ref,
  но больше не принуждает v3 Selector выбрать или materialize весь corpus;
- v2/checkpoint adapter сохраняет исходные evidence/cardinality/fidelity
  semantics и включается для persisted contract при активном
  `AGENT_TYPED_REQUIREMENTS_V1_ENABLED`;
- parent post у note остается только `target.parent_post_id`/catalog locator и
  не создает source или evidence requirement.

## Проверки

```bash
cd backend
.venv/bin/pytest -q \
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

Результат: `357 passed, 1 warning`. Warning про смену pooling в `fastembed`
существовал до фазы. Phase-0 replay дважды вернул прежний digest
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`;
protected fixture hashes и baseline gates не изменились. Дополнительно выполнены
`py_compile` измененных Python-модулей и `git diff --check`.

## Exit criteria

- [x] verifier и Selector validation используют typed evidence obligation и
  cardinality accessors, а не голый `required` для принудительного выбора;
- [x] каждый новый v3 factual contract содержит `plan_decision`:
  deterministic structural/exact fast path либо typed semantic/mixed planner;
- [x] v2 adapter сохраняет стратегию legacy checkpoint, а default-off flag
  сохраняет baseline runtime и replay digest;
- [x] typed gaps сериализуются в sufficiency/checkpoint и видны в trace;
- [x] required discovery с `min=0`, required evidence с `min=1`, missing
  property/aggregate, assessment coverage, fidelity, parent metadata и v2
  checkpoint compatibility покрыты отдельными тестами.

## Остаточные риски

- flag остается default-off до shadow/canary фазы 6; v2 projection доступна для
  немедленного rollback;
- classifier prompt пока продолжает принимать legacy-названия полей и
  детерминированно переводит их в v3; полностью typed planner protocol относится
  к фазе 5;
- Selector assessment schema, budgeted materialization и post-pack verification
  намеренно не переделывались в этой фазе;
- typed structural requirement корректно остается gap, если phase-1 catalog не
  предоставляет нужный aggregate; отсутствие свойства не трактуется как ноль.
