# Единый план: фаза 4 — policy compiler, hydration и final EvidencePack

**Статус:** план  
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
