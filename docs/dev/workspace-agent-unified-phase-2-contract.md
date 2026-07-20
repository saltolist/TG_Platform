# Единый план: фаза 2 — typed obligations и evidence requirements

**Статус:** план  
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
