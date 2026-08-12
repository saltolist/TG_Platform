# Workspace Agent: единый план целостности контекста и структурных подсчётов

**Дата:** 2026-07-20  
**Статус:** план реализации; runtime до прохождения фазы 0 не изменяется  
**Источники:**

- [workspace-agent-planner-search-and-counting-notes.md](workspace-agent-planner-search-and-counting-notes.md)
- [workspace-agent-context-selection-integrity-plan.md](workspace-agent-context-selection-integrity-plan.md)
- текущие `TurnContract`, `SearchIntentLedger`, `material_plan`, semantic cards,
  deterministic batches, `EvidencePack`, `message_context_manifest` и replay
  fixtures

После согласования этот документ является единственным источником порядка
реализации. Два исходных документа сохраняются как история диагностики и набор
примеров, но не задают параллельные rollout-последовательности.

### Приоритет источников

Старые ADR, roadmap, sprint/phase plans, limitation notes и прочие документы по
Workspace Agent могут описывать уже удаленные, частично мигрированные или
противоречащие текущему runtime решения. Они не являются требованиями для этой
работы, если на конкретный документ или invariant нет явной ссылки из этого
master-плана или соответствующего фазового файла.

При реализации используется следующий приоритет:

1. фактический текущий код, schema, migrations, tests и replay fixtures;
2. этот master-план;
3. фазовый документ активной фазы;
4. явно перечисленные действующие ADR/invariants;
5. остальные старые документы только как исторический контекст.

При конфликте старого документа с этим планом действует этот план. При конфликте
плана с фактическим runtime расхождение сначала фиксируется и разбирается: нельзя
молча восстанавливать старую архитектуру только потому, что она описана в ADR.
При этом tenant isolation, authorization, ownership/status checks, checkpoint
integrity и прочие действующие safety-инварианты сохраняются, пока новый план не
заменит их явно более строгим правилом.

## 1. Цель

Устранить корневые причины двух классов ошибок:

1. структурные факты (например, число заметок с изображениями) вычисляются
   моделью по неполному текстовому каталогу;
2. discovery, semantic relevance, materialization и финальный EvidencePack имеют
   размытые границы, из-за чего нерелевантный кандидат может попасть в контекст
   или обязательный источник может принудить выбрать слабый hit.

Результат должен улучшить систему монотонно: текущие корректные ответы, latency,
checkpoint/resume, citations, tenant/status guards и существующие fast paths не
должны ухудшиться.

## 2. Главный принцип

В системе остается один семантический LLM-фильтр между discovery и финальной
генерацией — `Context Selector`. Action planner может выбирать следующий tool
для закрытия typed gap, но не решает повторно ту же задачу relevance.

Целевой поток:

```text
TurnContract
  -> typed source/evidence requirements
  -> authoritative catalog/discovery
  -> CandidateRegistry
  -> Context Selector (только для semantic predicate)
  -> deterministic policy compiler
  -> budgeted materialization/hydration
  -> post-pack verifier
  -> minimal verified EvidencePack
  -> Answer Model
```

Для чисто структурного запроса Context Selector и LLM planner не нужны:
contract compiler выбирает deterministic fast path, а backend возвращает
агрегаты и проверяемые элементы.

## 3. Что сохраняем

Нельзя создавать вторую параллельную агентную систему. Используются и расширяются
существующие механизмы:

- `TurnContract` и его revision/checkpoint adapter;
- один `SearchIntentLedger`;
- `material_plan` как единственный durable план materialization;
- semantic cards с revision-проверкой;
- deterministic full-text batches;
- `USE_FAST_PATH` и обязательный verifier перед `FINISH_READY`;
- `EvidencePack` и `message_context_manifest`;
- `known_context_refs`, `used_context_refs`, stale refs;
- существующая observability для search, evidence fidelity и context reuse.

Новые поля добавляются с versioned schema и compatibility projection. Старые
checkpoints должны читаться без миграции всех сохраненных runs.

Порядок архитектурных решений фиксирован: сначала authoritative data и
контракты, затем semantic selection, затем materialization/pack и только после
этого политика planner. Prompt-only исправления до появления соответствующего
typed state не считаются реализацией требования.

## 4. Корневые проблемы и лечение

| Корень проблемы | Текущий риск | Лечение | Фаза |
|---|---|---|---|
| `required` означает сразу discovery, evidence и выбор объекта | слабый кандидат выбирается только ради representation source | независимые discovery/evidence/cardinality/fidelity obligations | 2 |
| Отсутствие поля трактуется как `false`/`0` | ложный ответ «изображений нет» | typed catalog schema, `unknown` до доказанного нуля | 1, 4 |
| Структурные подмножества считает Answer Model | ошибки на больших/обрезанных списках | backend aggregates и result set | 1 |
| Ambient visibility кодируется semantic score | локальная нерелевантная note выглядит как top hit | `origin` отдельно от nullable `semantic_score` | 3 |
| Selector возвращает только положительные selections | нельзя отличить reject от пропуска | assessment каждого visible ref + source disposition | 3 |
| Invalid Selector fallback выбирает всех | загрязненный EvidencePack при schema/timeout | exact-only fallback, bounded retry, explicit gap | 3, 4 |
| Complete coverage смешана с relevance selection | top-k или, наоборот, гидратация всего корпуса | отдельные discovery/assessment/pack coverage | 2, 3, 4 |
| Semantic search отключается для complete source | теряются ranking и useful fragments | search только обогащает complete catalog | 5 |
| Гидратация до char/object budget | дорогие DB reads потом отбрасываются | budgeted materialization queue до чтения | 4 |
| Проверка полноты до pack | после truncation coverage становится ложно complete | verifier после сборки pack | 4 |
| Parent relation трактуется как evidence | родительский пост попадает автоматически | relation остается metadata | 3, 4 |
| Answer Model исправляет ошибки отбора | хороший текст маскирует плохой pipeline | answer только использует verified pack | 4 |

## 5. Термины и состояния

Разные свойства не кодируются одним флагом:

- `discovery_coverage`: исследован ли заявленный корпус (`complete`, `partial`,
  `unknown`);
- `assessment_coverage`: оценены ли все показанные semantic candidates;
- `selection_coverage`: какие объекты Selector признал `direct/supporting`;
- `pack_coverage`: что реально попало в EvidencePack после fidelity, budget и
  provenance checks;
- `property_coverage`: какие структурные поля реально предоставлены catalog
  schema (`provided`, `unknown`), а не выводятся из отсутствия текста.

`coverage=complete` в contract означает полноту исследования корпуса. Оно не
означает, что каждый объект должен попасть в final pack для semantic predicate.
Для structural predicate backend сам формирует итоговое множество.

## 6. Целевая модель данных

### 6.1 Source obligations

Новая версия requirement логически содержит:

```json
{
  "source_id": "workspace-notes",
  "kind": "notes",
  "discovery_obligation": "required",
  "evidence_obligation": "required",
  "selection_cardinality": {"min": 0, "max": 6},
  "coverage": "complete",
  "predicate_kind": "structural",
  "required_fidelity": "catalog",
  "evidence_requirements": ["notes.has_images", "notes.image_count"]
}
```

`selection_cardinality.min=0` разрешает честный `no_relevant_candidate`.
`min=1` используется только если сам вопрос логически требует объект этого
источника. Parent source не становится required автоматически из-за relation.

Старое `required` читается compatibility adapter-ом как временная комбинация,
но новые decisions не должны записывать эту комбинацию обратно.

### 6.2 Catalog schema

Каждый catalog item, если источник заявляет attachment properties, содержит
явные значения, включая нули:

```json
{
  "ref": "note:UUID",
  "kind": "note",
  "title": "...",
  "parent": {"kind": "post", "ref": "post:UUID"},
  "file_count": 2,
  "image_count": 2,
  "has_files": true,
  "has_images": true,
  "visibility": "included",
  "revision": 12
}
```

Catalog envelope содержит `schema_version`, `members_complete`, `total_members`,
`aggregates`, `provided_properties`, `omitted_properties`, `next_cursor` и
`source_requirement_id`. Отсутствующее поле означает `unknown`, пока verifier не
увидит `provided_properties` с этим полем.

Минимальные aggregates для notes:

- `total_notes`;
- `notes_with_files`;
- `notes_with_images`;
- `image_files_total`.

Для posts значения разделяются:

- `direct_media_count`, `direct_image_count`;
- `note_files_total`, `note_image_files_total`;
- `notes_with_files_count`, `notes_with_images_count`;
- `posts_with_any_images` как union без двойного счета.

### 6.3 CandidateEnvelope

```json
{
  "ref": "note:UUID",
  "origin": "ambient_current_post",
  "semantic_score": null,
  "source_requirement_ids": ["workspace-notes"],
  "parent": {"kind": "post", "ref": "post:UUID"},
  "card_eligible": false,
  "available_fidelity": ["full_text"]
}
```

`origin` и inclusion priority не сравниваются с semantic score. Ambient candidate
попадает в registry отдельным правилом, но не считается релевантным автоматически.

### 6.4 Selector decision

Для каждого visible ref должен быть ровно один assessment:

```json
{
  "assessments": [
    {
      "ref": "note:UUID",
      "relevance": "direct|supporting|irrelevant",
      "role": "answer_evidence|none",
      "resolution": "card|full_text|none",
      "confidence": 0.94,
      "reason_code": "exact_fact"
    }
  ],
  "source_dispositions": [
    {"source_id": "workspace-posts", "status": "no_relevant_candidate"}
  ]
}
```

Детерминированный compiler проверяет полноту, duplicate/unknown refs,
cardinality, fidelity floor, parent metadata и право на materialization.

## 7. Режимы обработки

| Режим | Источник истины | Selector | Ответ |
|---|---|---|---|
| structural count/filter | backend catalog + aggregates | нет | count/list из backend |
| exact target | target contract + original | нет или fast path | verified original |
| semantic relevant subset | complete/relevant discovery + cards | один Selector | выбранные objects |
| mixed structural + semantic | backend structural prefilter, затем semantic assessment | один Selector после prefilter | backend count по выбранному множеству |
| attachment content/vision | catalog metadata, затем explicit hydration | Selector выбирает refs | только hydrated evidence |

## 8. Фазы и зависимости

| Фаза | Документ | Результат | Зависит от |
|---|---|---|---|
| 0 | [phase-0-baseline](workspace-agent-unified-phase-0-baseline.md) | quality freeze, fixtures, rollback point | — |
| 1 | [phase-1-catalog](workspace-agent-unified-phase-1-catalog.md) | typed catalogs и deterministic aggregates | 0 |
| 2 | [phase-2-contract](workspace-agent-unified-phase-2-contract.md) | независимые obligations и typed gaps | 0, 1 |
| 3 | [phase-3-selector](workspace-agent-unified-phase-3-selector.md) | один полный semantic Selector | 2 |
| 4 | [phase-4-materialization](workspace-agent-unified-phase-4-materialization.md) | compiler, budgeted hydration, verified pack | 1, 2, 3 |
| 5 | [phase-5-planner-search](workspace-agent-unified-phase-5-planner-search.md) | plan decision, additive search, structural fast path | 2, 3, 4 |
| 6 | [phase-6-rollout](workspace-agent-unified-phase-6-rollout.md) | replay, shadow, canary и default-on gates | 0-5 |

Фазы не включаются «вполовину»: каждая имеет exit criteria и отдельный rollback.

## 9. Защитные инварианты

До и после каждой фазы должны проходить следующие invariants:

1. Tenant/user/status/owner проверяются перед каждым original read.
2. Semantic top-k никогда не уменьшает `discovery_coverage=complete`.
3. `unknown` никогда не сериализуется как `false` или `0`.
4. Число объектов и число файлов считаются раздельно.
5. `irrelevant` не материализуется.
6. Parent relation не добавляет evidence автоматически.
7. Invalid/timeout Selector не вызывает select-all fallback.
8. `required_fidelity` является нижней границей, а не пожеланием Selector.
9. Card не переименовывается в full text без verified hydration lineage.
10. После pack omissions не могут остаться при `coverage=complete`.
11. Negative claim об отсутствии возможен только при complete property coverage.
12. Answer Model не меняет membership EvidencePack.
13. Planner повторно вызывается только после нового evidence или нового typed gap.
14. Existing fast/exact/mutation flows не получают дополнительный LLM call без
    явного contract decision.
15. Checkpoint/resume сохраняет schema version, revisions и все pending gaps.

## 10. Набор обязательных сценариев

- одна глобальная note с двумя `image/png`: `notes_with_images=1`,
  `image_files_total=2`;
- note внутри post и глобальная note учитываются в одном полном корпусе;
- note без файлов явно имеет `file_count=0`, `image_count=0`, `has_images=false`;
- неизвестный MIME не превращается в image или non-image без доказательства;
- прямое post media не смешивается с note attachments;
- вопрос «посты с изображениями» возвращает раздельные direct/nested/union
  aggregates;
- semantic query с complete corpus не теряет low-similarity object;
- ambient relevant note выбирается без semantic score;
- ambient irrelevant note получает `irrelevant`;
- все candidates required discovery нерелевантны: `no_relevant_candidate`, pack
  пуст для этого source;
- parent post виден в metadata, но выбирается только отдельным assessment;
- invalid Selector не приводит к select-all;
- card при required full_text получает explicit promotion или unresolved gap;
- truncation/omission после pack переводит coverage в partial;
- каталог больше 8 и больше 100 объектов проходит paging/batch без скрытой потери;
- exact quote/edit/mutation никогда не завершается card-only.

## 11. Метрики и quality gates

На всех фазах сохраняются baseline и сравниваются:

- `selector_relevant_precision/recall`;
- `irrelevant_selection_rate`;
- `required_source_forced_selection_rate`;
- `fallback_select_all_rate` (обязательное значение `0`);
- `required_evidence_recall`;
- `fidelity_mismatch_rate` (обязательное значение `0`);
- `catalog_property_unknown_rate`;
- `structural_count_error_rate` (обязательное значение `0` на fixtures);
- `final_pack_precision`;
- `planner_noop_rate` и evidence delta;
- p50/p95 latency, tool calls, planner calls и context tokens.

### Quality floors, зафиксированные фазой 0

Точка отсчета: commit `128a96497416bc40d5d019ad3be97866ad094394`.
Read-only отчет: `cd backend && .venv/bin/python
scripts/agent_unified_phase0_report.py --repeat 2 --check`.

- существующие golden/held-out expected results и evidence не изменяются без
  отдельной regression note; их fixtures защищены SHA-256;
- fast/exact/mutation flows не получают дополнительный planner call;
- latency и tool/planner calls не ухудшаются без отдельно согласованного budget;
- отсутствующая telemetry всегда имеет `availability=unavailable` и `value=null`,
  но не `0`; на baseline context tokens отсутствуют для 32 из 32 trace runs;
- `fallback_select_all_rate`, `required_source_forced_selection_rate`,
  `fidelity_mismatch_rate` и `structural_count_error_rate` должны стать `0` на
  соответствующих fixtures до default-on;
- selector precision/recall, required evidence recall, final pack precision,
  catalog unknown rate и planner noop rate не считаются прошедшими gate, пока
  typed state не сделает их измеримыми; до этого отчет явно помечает их
  `unavailable` либо `derived` только на синтетическом ground truth;
- frozen regressions (`invalid selector -> select-all`, forced parent/required
  hit, ambient false positive, скрытые catalog members) сохраняются как baseline,
  а не как допустимое целевое поведение.

Default-on разрешен только если:

- ни один golden exact/quote/edit scenario не завершается card-only;
- complete coverage не ухудшилась;
- structural count и image semantics проходят все golden tests;
- `fallback_select_all_rate=0`;
- `required_source_forced_selection_rate=0`;
- `fidelity_mismatch_rate=0`;
- irrelevant selection статистически лучше baseline;
- latency и LLM calls не выходят за согласованный budget;
- старый путь остается доступен для немедленного rollback.

## 12. Rollout и откат

Каждая фаза сначала выполняется в offline replay и shadow mode. Shadow path не
вызывает Answer Model и не меняет пользовательский ответ: сравниваются contract,
catalog, selector decision, material plan и final pack.

Feature flags должны быть независимыми, но включаться только в порядке фаз:

```text
unified_catalog -> typed_requirements -> unified_selector
-> verified_pack_boundary -> planner_policy -> default_on
```

Откат выключает последний флаг и возвращает предыдущую read-only projection.
Нельзя откатывать только schema parser, оставляя новый compiler с неполными
assessment-ами.

## 13. Definition of done

Работа завершена, когда для каждого item в final EvidencePack можно
детерминированно ответить:

1. откуда он появился;
2. какое obligation он закрывает;
3. как Selector оценил его или почему structural backend включил его;
4. какая fidelity требовалась и достигнута;
5. как проверены owner/status/revision;
6. почему item не был отброшен pack budget;
7. почему он нужен Answer Model.

Если хотя бы один ответ отсутствует, item не должен попадать в final pack.
