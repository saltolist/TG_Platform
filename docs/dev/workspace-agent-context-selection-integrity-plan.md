# Workspace Agent: план целостности отбора контекста

**Дата:** 2026-07-20  
**Статус:** историческая диагностика; порядок реализации заменен единым планом
**Актуальный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)
**Разобранные post-chat:**
`82f9068e-b54c-415b-b225-369b808d35e3`,
`052605bd-4f2b-4443-9bd8-e96835562feb`  
**Ключевые runs:**
`51ab775e-8ff7-462f-a5f2-239677fde635`,
`b659720c-c8f6-4be6-a853-645ecfbc2837`,
`caea7965-6f3f-4014-8ecb-348cc7bccb53`

Этот документ сохраняется как разбор корневых причин и набор проверяемых
сценариев. Реализация и rollout выполняются только по актуальному master-плану и
его фазовым документам.

## 1. Решение

В системе должен остаться один семантический LLM-фильтр между discovery и
финальной генерацией. Им является Context Selector. Добавлять второй LLM,
который повторно решает ту же задачу перед Answer Model, не нужно: это повысит
стоимость, задержку и недетерминизм, но не устранит причину ошибок первого
решения.

Нужно исправить границы ответственности:

1. contract определяет, какие источники надо исследовать и какое evidence нужно
   для ответа;
2. discovery показывает доступных кандидатов, но ничего не объявляет
   релевантным;
3. Context Selector является единственным владельцем семантического решения
   `direct | supporting | irrelevant`;
4. runtime детерминированно проверяет полноту решения, ограничения fidelity и
   допустимость refs, но не подменяет нерелевантный объект «любым объектом из
   required source»;
5. materialization получает оригиналы только выбранных объектов;
6. EvidencePack содержит только выбранные и успешно материализованные объекты;
7. Answer Model пишет ответ, а не исправляет ошибки отбора контекста.

Целевой поток:

```text
TurnContract
  -> Source obligations
  -> Discovery candidates
  -> ONE semantic Context Selector
  -> Typed selection decision
  -> Deterministic policy compiler
  -> Materialization / hydration
  -> Minimal verified EvidencePack
  -> Answer Model
```

## 2. Что фактически произошло

### 2.1 Локальная заметка оказалась полезной

В чате `052605bd-...` текущий пост содержал заметку «Про медведя». Ambient
catalog сделал ее видимой, Selector выбрал ее, runtime открыл оригинал, а ответ
корректно использовал содержание заметки.

Это подтверждает полезность постоянной видимости заметок текущего поста.
Удалять ambient catalog или возвращаться к primer/summaries не нужно.

### 2.2 Локальная заметка оказалась нерелевантной

В чате `82f9068e-...` текущий пост содержал только заметку «Варианты изображений
для поста». Она получила искусственный `score=1.0`, попала в обычный список
кандидатов и была выбрана, хотя вопрос был про шутку. Runtime затем выполнил
`OpenNote`, а объект попал в EvidencePack, но Answer Model его не использовала.

`score=1.0` здесь означал «объект всегда виден», но выглядел для Selector как
«максимальная semantic relevance». Visibility и relevance оказались смешаны.

### 2.3 Слабый пост был выбран ради required source

На вопрос «А если взять шутку из заметки другого поста?» поиск заметок нашел
«Про медведя» с similarity около `0.487`. Независимый поиск постов вернул
нерелевантный пост «Олр» с similarity около `0.424`.

Classifier сделал одновременно `workspace-notes` и `workspace-posts`
обязательными. Validator требовал, чтобы выбранные refs представляли каждый
required source, если от него существовали кандидаты. Единственным post-hit был
«Олр», поэтому контракт и validator подтолкнули Selector к выбору какого-нибудь
поста вместо возможности честно отклонить все post-кандидаты.

Фраза «заметка другого поста» описывала принадлежность заметки, а не
необходимость использовать текст родительского поста как evidence.

### 2.4 Родительская связь потерялась

Search hit заметки «Про медведя» содержал `post_id` родительского поста, но эта
связь не дошла до компактного входа Selector. Родительский пост не был
кандидатом, а Selector не имел права придумать его ref.

Правильное поведение здесь не состоит в автоматическом добавлении родительского
поста в EvidencePack. Selector должен видеть связь, но выбирать родительский
пост только тогда, когда его содержание действительно нужно ответу.

### 2.5 Финальный full text был, но trace был неоднозначным

В run `caea7965-...` Selector выбрал заметку «Про медведя» как `card`, и
отдельного tool-вызова `OpenNote` для нее не было. На final handoff карточка была
гидратирована из оригинала. Итоговый EvidencePack содержал `note_chunk` с
реальным телом заметки и `fidelity=full_text`; discovery summary остался только
в metadata.

Следовательно, финальная генерация получила оригинал. Ошибка предыдущей
интерпретации возникла потому, что `material_plan` и `evidence_records`
продолжали показывать semantic card, а handoff-гидратация была видна только в
финальном EvidencePack. Нужна явная трассировка перехода
`selected card -> hydrated original`.

### 2.6 Почему хороший ответ не означает корректный pipeline

Answer Model проигнорировала заметку с изображениями и «Олр» и сослалась только
на текущий пост и заметку «Про медведя». Поэтому пользователь получил приемлемый
ответ.

Это не достаточная гарантия. Лишние объекты:

- расходуют контекст и деньги;
- увеличивают риск смешивания фактов;
- расширяют поверхность prompt injection;
- усложняют claims/citations;
- скрывают низкую precision Selector за способностью Answer Model игнорировать
  мусор.

## 3. Корневые причины

### 3.1 Перегруженное понятие `required`

Один флаг одновременно означает несколько разных обязательств:

- источник нужно исследовать;
- источник должен дать evidence;
- из найденных кандидатов нужно выбрать хотя бы один объект;
- без объекта из источника нельзя завершить research.

Эти утверждения не эквивалентны. Required discovery может честно закончиться
результатом `no_relevant_candidate`.

### 3.2 Ambient visibility закодирована как relevance

Локальная заметка должна гарантированно дойти до Selector, но для этого ей был
выдан semantic-like score. Это нарушает смысл поля и искажает решение модели.

### 3.3 Selector сообщает только положительный выбор

По итоговому списку selections невозможно надежно отличить:

- осознанное отклонение кандидата;
- потерю кандидата моделью;
- ограничение completion;
- ошибку schema parsing;
- выбор «на всякий случай» ради required source.

### 3.4 Validator проверяет representation, а не решение

Текущий validator умеет подтвердить, что ref существует и что required sources
представлены. Он не умеет подтвердить, что модель оценила всех кандидатов и
осознанно отклонила нерелевантные.

### 3.5 Fallback оптимизирован на recall любой ценой

При невалидном решении fallback выбирает все найденные refs. Это сохраняет
recall, но превращает любой сбой Selector в загрязненный EvidencePack. Для
финального factual-контекста такой fallback небезопасен.

### 3.6 Нет явной границы final-pack membership

После положительного выбора Selector последующие стадии проверяют доступность,
freshness и fidelity, но не пересматривают релевантность. Это правильно только
при условии, что решение Selector полное и строго типизировано. Сейчас это
условие не гарантировано.

## 4. Новая модель контрактов

### 4.1 Разделить обязательства источника

Вместо перегруженного `required` SourceRequirement должен независимо задавать:

```json
{
  "source_id": "workspace-notes",
  "discovery_obligation": "required",
  "evidence_obligation": "required",
  "selection_cardinality": {"min": 1, "max": 6},
  "coverage": "relevant",
  "required_fidelity": "full_text"
}
```

Семантика:

- `discovery_obligation=required`: источник обязан быть исследован или явно
  помечен недоступным/исчерпанным;
- `evidence_obligation=required`: ответ требует evidence этого типа;
- `selection_cardinality.min=0`: допустимо исследовать источник и не выбрать
  ни одного нерелевантного кандидата;
- `selection_cardinality.min=1`: задача логически требует хотя бы один объект
  этого источника;
- `required_fidelity`: минимальная глубина именно для выбранных объектов.

Для «шутки из заметки другого поста»:

- текущий пост: required full-text target;
- workspace notes: required discovery, required evidence, `min=1`;
- parent post заметки: relationship/locator, не evidence obligation;
- workspace posts как отдельный corpus: не required, если содержание постов не
  участвует в ответе.

Classifier должен выражать зависимости ответа, а не механически превращать
каждое существительное запроса в required corpus.

### 4.2 Разделить типы происхождения кандидата

CandidateEnvelope должен содержать:

```json
{
  "ref": "note:UUID",
  "kind": "note",
  "title": "...",
  "card_text": "...",
  "discovery_origin": "ambient_current_post",
  "semantic_score": null,
  "source_requirement_ids": ["workspace-notes"],
  "parent": {"kind": "post", "ref": "post:UUID"},
  "card_eligible": false,
  "available_fidelity": ["full_text"]
}
```

Допустимые origins должны быть явными, например:

- `exact_target`;
- `ambient_current_post`;
- `semantic_search`;
- `catalog_member`;
- `dialog_reference`.

У ambient-кандидата нет semantic score. Он гарантированно присутствует в
registry за счет отдельного правила включения и budget, а не за счет ложного
`1.0`. Настоящий search score остается только у semantic-search hits и не
сравнивается напрямую с приоритетом exact/ambient objects.

### 4.3 Parent relation является metadata

`parent_post_id` должен сохраняться от retrieval до Selector, material plan,
canonical citation path и trace. Наличие parent relation:

- помогает понять контекст происхождения заметки;
- позволяет корректно вызвать `OpenNote`;
- не делает родительский пост автоматически выбранным evidence;
- не закрывает post source requirement, если вопрос действительно требует
  содержание родительского поста.

## 5. Единственный семантический Selector

### 5.1 Полное typed-решение

Selector должен оценить каждый показанный кандидат:

```json
{
  "assessments": [
    {
      "ref": "note:UUID",
      "relevance": "direct",
      "role": "answer_evidence",
      "resolution": "full_text",
      "confidence": 0.94,
      "reason_code": "content_required"
    },
    {
      "ref": "post:UUID",
      "relevance": "irrelevant",
      "role": "none",
      "resolution": "none",
      "confidence": 0.97,
      "reason_code": "unrelated_topic"
    }
  ],
  "source_dispositions": [
    {
      "source_id": "workspace-posts",
      "status": "no_relevant_candidate"
    }
  ]
}
```

Это остается небольшим enum-heavy ответом без пересказов содержимого. Второй
LLM не нужен: полноту оценки можно проверить детерминированно.

Обязательные свойства:

- assessment существует для каждого visible ref;
- один ref встречается ровно один раз;
- `irrelevant` никогда не материализуется;
- `direct/supporting` всегда имеют роль и resolution;
- source disposition согласуется с assessments;
- ambient origin не означает relevance;
- relationship metadata не означает selection.

### 5.2 Source disposition вместо выбора мусора

Для каждого исследованного source Selector должен иметь возможность вернуть:

- `selected`;
- `no_relevant_candidate`;
- `search_more`;
- `ambiguous`.

Если required discovery не нашел релевантный объект, runtime не выбирает
лучший из плохих. Он либо выполняет разрешенное уточнение поиска, либо завершает
source как exhausted и отражает evidence gap. Это сохраняет честность без
потери recall.

### 5.3 Fidelity является ограничением, а не пожеланием

Selector выбирает желаемую resolution, а runtime применяет жесткую нижнюю
границу SourceRequirement:

```text
effective_fidelity = max(selector_resolution, required_fidelity)
```

Смысловой порядок глубины:

```text
metadata < semantic_card < full_text < hydrated_attachment/vision
```

Точный факт, цитата, подробный пересказ, сравнение или редактирование не могут
остаться на semantic card. Runtime повышает depth и фиксирует override в trace.

## 6. Детерминированный policy compiler

После Selector нужен не второй LLM, а строгий компилятор решения.

Он должен:

1. проверить полный набор assessments;
2. отклонить неизвестные/дублирующиеся refs;
3. исключить `irrelevant` до material plan;
4. применить source fidelity floor;
5. проверить selection cardinality;
6. преобразовать `search_more` в bounded discovery action;
7. преобразовать `no_relevant_candidate` в exhausted source, а не в случайный
   выбор;
8. сформировать materialization queue только из direct/supporting refs;
9. сохранить parent relations и canonical paths;
10. записать понятный trace решения и каждого runtime override.

### 6.1 Безопасный fallback

При schema/timeout/invalid-output нельзя выбирать все discovery candidates.

Допустимый fallback:

- сохранить authoritative exact targets;
- материализовать только explicit refs, если они уже известны;
- для discovery sources вернуть `selector_failed` и разрешить один bounded retry;
- после исчерпания retry дать partial answer с unresolved gap;
- не добавлять semantic/ambient candidates в EvidencePack без положительного
  typed assessment.

Такой fallback снижает ложный recall, но не скрывает проблему: gap будет виден
пользователю и в trace. Для factual answers честная неполнота безопаснее
нерелевантного evidence.

## 7. Materialization и EvidencePack

### 7.1 Card и original должны быть различимы

Discovery card остается производным материалом. Full-text item создается только
после успешного чтения оригинального объекта с проверкой owner, status и
revision.

Full text может быть получен как обычным `OpenNote/OpenPost`, так и
детерминированной handoff hydration. Важен не конкретный tool event, а
проверяемый результат:

- original найден;
- revision совпадает;
- content взят из original source;
- final item имеет `hydrated_from` и source ref;
- при ошибке card не переименовывается в full text.

### 7.2 Минимальный EvidencePack

EvidencePack включает:

- обязательные exact targets;
- только `direct/supporting` selections;
- только успешно достигнутую effective fidelity;
- explicit unresolved gaps для недоступных required selections.

Он не включает:

- `irrelevant` assessments;
- ambient objects только по факту локальности;
- слабый hit только ради representation required source;
- parent objects только из-за связи;
- все candidates при отказе Selector.

Answer Model не считается relevance-фильтром. Если она проигнорировала лишний
объект, это полезная устойчивость, но не доказательство корректности pipeline.

### 7.3 Цитаты

`claim_scope=exact` требует буквального подтверждения. Переформулированный
исходник нельзя оформлять как прямую цитату. Output validator/grader должен
отличать:

- verbatim quote;
- grounded paraphrase;
- unsupported exact wording.

## 8. Наблюдаемость

Для каждого хода trace должен показывать отдельные стадии:

1. `candidate_registry`:
   - ref, origin, semantic score или `null`, parent, source IDs;
2. `selector_assessment`:
   - relevance, role, requested resolution, reason code;
3. `source_disposition`:
   - selected/no relevant/search more/exhausted;
4. `policy_compilation`:
   - rejected refs, fidelity promotions, validation errors;
5. `materialization`:
   - source ref, original revision, result fidelity, failure;
6. `final_pack_membership`:
   - почему каждый item включен;
7. `answer_usage`:
   - considered, cited и claim-bound evidence.

Нельзя диагностировать final fidelity по промежуточному `evidence_records`.
Trace должен явно показывать переход card -> original и итоговый source hash или
revision digest.

## 9. План реализации

### Этап 0. Зафиксировать near-miss как fixture

Сохранить обезличенные snapshots трех разобранных runs как golden fixtures:

- текущий пост с релевантной ambient note;
- текущий пост с нерелевантной ambient image note;
- external relevant note + weak unrelated post hit.

Fixture содержит contract, candidate registry, selector input/output, material
plan и final pack. Тексты нужны только в минимальном объеме для проверки
релевантности; пользовательские данные в репозиторий целиком не копировать.

### Этап 1. Typed candidate registry

- ввести `discovery_origin` и nullable `semantic_score`;
- убрать fake semantic score у ambient objects;
- сохранить parent relation и canonical ref;
- отделить inclusion priority от retrieval score;
- добавить schema/unit tests.

Основные файлы:

- `backend/app/services/agent/research/material_plan.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/prefetch.py`;
- `backend/app/services/ai/rag_tools.py`.

### Этап 2. Source obligations

- разделить discovery, evidence, cardinality и fidelity obligations;
- обновить classifier schema и deterministic normalization;
- перестать делать parent corpus required только из-за relationship phrase;
- сохранить compatibility adapter для checkpoint старой версии;
- добавить contract fixtures, включая «заметка другого поста».

Основные файлы:

- `backend/app/services/agent/runtime/turn_contract.py`;
- `backend/app/services/agent/runtime/workspace_graph.py`;
- `backend/app/services/agent/research/sufficiency.py`.

### Этап 3. Полное решение одного Selector

- заменить selections-only output на assessments всех visible refs;
- добавить source dispositions;
- оставить enum-heavy bounded JSON;
- валидировать полноту ответа без semantic эвристик в Python;
- исключить select-all fallback;
- сохранить один LLM call.

Основные файлы:

- `backend/app/services/agent/research/planner_decision.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/material_plan.py`.

### Этап 4. Policy compiler и fidelity

- компилировать assessments в material plan;
- применять required fidelity floor;
- выполнять search_more/partial без случайного выбора;
- не считать source закрытым только по наличию кандидата;
- проверить checkpoint/resume и budgets.

Основные файлы:

- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/sufficiency.py`;
- `backend/app/services/agent/runtime/state.py`.

### Этап 5. Final evidence boundary

- усилить card -> original hydration invariant;
- проверять fidelity и provenance непосредственно перед pack;
- строить minimal EvidencePack только из compiled selections;
- добавить explicit hydration lineage;
- запретить silent card/full mismatch.

Основные файлы:

- `backend/app/services/agent/research/evidence_pack.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/evidence.py`;
- `backend/app/services/agent/runtime/message_context.py`.

### Этап 6. Rollout

- включить новый контракт и Selector за одним feature flag;
- прогнать offline replay старых runs без вызова Answer Model;
- затем shadow/canary на реальном трафике;
- сравнить старый и новый material plan/EvidencePack;
- включать по умолчанию только после прохождения quality gates;
- удалить compatibility path после периода стабильности.

## 10. Обязательные тесты

### Разобранные сценарии

1. Текущий пост + локальная «Про медведя»: ambient catalog гарантированно
   доставляет заметку в Selector независимо от search ranking; обычный
   workspace discovery остается включенным; materialize только релевантные
   selections с требуемой fidelity.
2. Текущий пост + локальная image note + external «Про медведя» + «Олр»:
   выбрать текущий пост и «Про медведя»; image note и «Олр» получить
   `irrelevant`; родительский пост заметки видеть в metadata, но не выбирать.
3. Тот же набор при invalid Selector output: не использовать select-all;
   выполнить retry или вернуть explicit partial gap.

### Общие сценарии

4. Ambient note релевантна вопросу и выбирается без semantic score.
5. Все кандидаты required discovery source нерелевантны: source получает
   `no_relevant_candidate`, ни один объект не попадает в pack.
6. Вопрос действительно требует несколько постов: Selector сохраняет recall и
   выбирает все релевантные объекты, а не один top hit.
7. Parent post нужен для сравнения: он добавляется отдельным осознанным
   selection, а не автоматически.
8. Parent post является только владельцем заметки: metadata доступна, evidence
   не добавляется.
9. `required_fidelity=full_text` + selector card: runtime materializes original
   и фиксирует promotion.
10. Ошибка hydration: item отсутствует в pack, source unresolved; card не
    получает ложный `full_text`.
11. Topic-only задача допускает eligible semantic card и ограничивает
    `allowed_claim_scope`.
12. Прямая цитата проверяется на verbatim; парафраз не маркируется цитатой.
13. Optional source не блокирует ready и не заставляет выбирать слабый hit.
14. Exact targets сохраняются при сбое Selector.
15. Candidate registry больше prompt budget: truncation является source-aware и
    явной, а не случайно вытесняет ambient или semantic candidates.

## 11. Метрики и quality gates

Нужны human-labeled golden и held-out наборы. Одного успешного ответа
недостаточно.

Основные метрики:

- `selector_relevant_precision`;
- `selector_relevant_recall`;
- `irrelevant_selection_rate`;
- `required_source_forced_selection_rate`;
- `ambient_false_selection_rate`;
- `fallback_select_all_rate`;
- `final_pack_precision`;
- `required_evidence_recall`;
- `fidelity_mismatch_rate`;
- `hydration_failure_rate`;
- `exact_quote_grounding_rate`;
- final context tokens, planner tokens и time-to-final.

Обязательные gates перед default-on:

- `fidelity_mismatch_rate = 0`;
- `fallback_select_all_rate = 0`;
- `required_source_forced_selection_rate = 0`;
- ни один golden exact/quote/edit scenario не завершается card-only;
- relevant recall не хуже текущего baseline;
- irrelevant selection статистически ниже baseline;
- p95 latency не ухудшается за согласованный предел;
- число LLM calls не увеличивается в обычном compact flow.

## 12. Что намеренно не делать

- не добавлять второй LLM relevance-фильтр перед Answer Model;
- не вводить keyword branches для «другого поста», «шутки» или известных chat
  IDs;
- не решать relevance одним глобальным similarity threshold;
- не скрывать ambient notes от Selector;
- не добавлять parent post автоматически в EvidencePack;
- не считать способность Answer Model игнорировать мусор достаточной защитой;
- не сохранять select-all fallback ради формального recall;
- не смешивать visibility priority и semantic score;
- не переписывать весь research graph до проверки typed-contract подхода на
  replay.

## 13. Критерий завершения

Работа завершена, когда для любого item финального EvidencePack можно
детерминированно ответить:

1. откуда кандидат появился;
2. почему Selector признал его релевантным;
3. какое source obligation он закрывает;
4. почему выбрана именно эта fidelity;
5. как original был материализован и проверен;
6. почему item нужен финальной генерации.

Если на любой из этих вопросов нет структурированного ответа, объект не должен
попадать в final EvidencePack.
