# Единый план: фаза 5 — plan decision, additive search и structural fast path

**Статус:** план  
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
