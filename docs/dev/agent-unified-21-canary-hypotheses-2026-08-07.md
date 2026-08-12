# Гипотезы для выхода на 21/21 live-канареек

Дата: 2026-08-07  
Манифест: `backend/tests/fixtures/agent_unified_phase6/v174/formal_canary_manifest.json`  
Последний полный UI-прогон: 21 свежий run после пересборки backend и celery-worker

## Назначение документа

Это не отчет о завершенном исправлении и не список prompt-костылей. Документ фиксирует
наблюдаемую причинную картину, рабочие гипотезы и controlled replay-ы, которые должны
привести к универсальному решению. Подтвержденные причины и изменения зафиксированы
ниже.

## Подтвержденный архитектурный дефект после sparse precision

После устранения provider/schema collapse главный источник нестабильности оказался
выше Selector-а. Один frozen query digest в разных live run-ах материализовался в
разные typed contracts. Bootstrap classifier одновременно менял:

- `task_profile` и `answer_shape`;
- required source kinds, включая не запрошенные attachments;
- complete/relevant coverage и source/member scope;
- lifecycle statuses, fidelity и cardinality;
- количество и формулировки `answer_obligations`.

Из-за этого downstream не «повторно ошибался» на одной задаче: он корректно выполнял
разные задачи, созданные недетерминированным classifier output. Selector tuning при
такой входной границе неизбежно исправлял один run и ухудшал следующий.

Исправление реализуется как staged deterministic contract compiler. В unified v3
classifier теперь является semantic specialist, а не владельцем policy. Compiler:

1. берёт frozen user query и pre-classifier tenant/target/corpus boundary;
2. допускает только primary source kinds внутри уже разрешенного boundary;
3. выводит inventory/composition, coverage, statuses, fidelity, cardinality и atomic
   source obligations детерминированно;
4. отбрасывает classifier-added attachments без явного query predicate и verified
   parent relation;
5. не использует candidate contents и не добавляет recent-post fallback.

Focused-инвариант проверяет, что разные необязательные policy-поля LLM дают один и тот
же materialized contract для одинакового query/semantic intent. Текущий focused gate:
`298 passed`. Live smoke и immutable gate после пересборки ещё должны подтвердить влияние
на recall/precision; до этого `21/21` не заявляется.

## Результаты controlled replay

Подтверждено в runtime:

- strict structured precision schema отклоняла большой `coordinate.enum` для
  row/unit-картезиана; transport теперь ограничивает только `position` небольшим
  enum, а unit проверяется decoder-ом;
- provider/API, unsupported schema, timeout, invalid transport и decoder outcomes
  записываются раздельно, с bounded secret-free diagnostics;
- typed answer obligations фильтруются по source IDs, реально представленным в
  immutable registry. Это исключает подмену обязательного post доказательством note;
- при precision подтверждении закрывается только уже отобранный required source,
  если его собственные entailment gates прошли; новые материалы и новые tenant
  boundaries не открываются.

Focused suite после изменений: `237 passed` (phase2 contract, phase3 selector,
phase6 closure). Backend и celery-worker пересобраны со staged unified-флагами.

Свежие live replay-ы подтвердили устранение прежнего schema/provider-collapse для
части сценариев и выявили независимые semantic-selection/cross-record проблемы.
Последующий вызов precision остановился на внешнем ответе `HTTP 429`,
`insufficient_quota`, `credit_balance_exhausted`; это не decoder/schema failure.
Поэтому immutable критерий `21/21` в этой сессии не подтвержден и не должен
считаться достигнутым до восстановления квоты и повторного полного прогона.

Целевой gate:

- 21/21 формальных сценария;
- critical recall 100%;
- irrelevant selection 0;
- отсутствие provider, validation/decoder и position ошибок;
- пустой evidence-контекст только когда подходящих материалов действительно нет;
- соблюдение tenant/provenance/fidelity boundary и лимитов серии.

## Что уже доказано

### Исходный provider failure был внутренним контрактным дефектом

До последней итерации `_run_precision_confirmation` передавал
`member_classification_mode` в `_precision_confirmation_json_schema`, хотя функция не
принимала этот аргумент. `TypeError` скрывался широким `except Exception`, превращался в
`schema_result=provider_error`, после чего все primary refs демонтировались.

Дополнительная проблема была в strict schema: generated obligation array содержал
`minItems/maxItems`, которые не входят в поддерживаемый поднабор OpenAI Structured
Outputs. Эти ограничения уже проверяются decoder-ом.

После исправления:

- precision provider реально вызывается;
- свежие run-ы не содержат `precision_confirmation.schema_result=provider_error`;
- structured payload для формы сценария 21 (`11` строк, до `63` units на строку)
  проходит локальный focused-тест;
- provider/API, unsupported schema, transport и decoder outcomes различаются в trace;
- provider failure больше не уничтожает безопасный primary baseline.

Следовательно, исходный provider collapse не объясняет оставшиеся 14 failures.

### Свежая матрица 21 run-ов

| № | Precision | Основной gate failure | Наблюдение |
|---:|---|---|---|
| 1 | valid | нет | PASS |
| 2 | valid | нет | PASS |
| 3 | valid | нет | PASS |
| 4 | decoder_error | critical recall, materialization | precision демонтировал весь subset |
| 5 | decoder_error | critical recall, materialization | inventory/member cardinality не подтверждена |
| 6 | not called | нет | PASS, пустой workspace context ожидаем |
| 7 | valid | нет | PASS |
| 8 | decoder_error | critical recall, materialization | generated obligation assignment не прошел decoder |
| 9 | valid | recall + unexpected/irrelevant | выбраны две заметки вместо нужного delivery contour |
| 10 | decoder_error | critical recall, materialization | duplicate generated obligation |
| 11 | valid | recall + unexpected | лишняя широкая заметка, нужные posts не materialized |
| 12 | valid | recall + unexpected | выбрана заметка вместо опубликованных capability posts |
| 13 | valid | нет | PASS |
| 14 | valid | critical materialization | inventory выбран, но часть корпуса не попала в pack |
| 15 | valid | critical recall | plan note выбран, связанные published posts потеряны |
| 16 | valid | unexpected selection | слишком широкий cross-record subset |
| 17 | invalid_transport | critical recall, materialization | precision ответ не образовал frame |
| 18 | decoder_error | critical recall, materialization | generated/member proof не прошел semantic decode |
| 19 | valid | нет | PASS |
| 20 | valid | critical recall | выбран общий note, нужные note/posts не удержаны |
| 21 | valid | recall + unexpected | лишняя note, один архитектурный post потерян |

Итог этой серии: **7/21 PASS**, position errors отсутствуют, provider errors отсутствуют.

## Рабочая модель контура

```text
classifier/contract
        |
        v
candidate discovery -> primary selector -> opened reads/reassessment
        |                       |
        |                       v
        |                precision registry + gates + obligations
        |                       |
        v                       v
material plan ------------> verified evidence pack -> final generator
```

Каждый класс failure нужно привязать к одному переходу. Нельзя лечить весь результат
изменением final generator: к моменту генерации лишние или потерянные refs уже находятся
в material plan/evidence pack.

## Гипотезы по semantic decoder failures

### H1. Generated-obligation mode включается при отсутствии typed obligations

**Сигнал.** В сценарии 21 trace содержит одновременно:

```text
decision_input_mode=true
generated_obligation_mode=true
decision_obligations=[]
```

Та же комбинация встречается в сценариях 4, 8 и 10. В этом режиме модель должна сама
придумать source-neutral obligations, хотя контракт не дал ей typed obligation registry.
Это превращает precision из проверки контракта в дополнительное планирование.

**Почему это правдоподобно.** В trace generated assignments появляются как
`answer:0`, `answer:1` и свободные описания. Для широкого запроса модель может выбрать
координату, которая семантически кажется подходящей, но не проходит row-local gate.

**Почему это не доказано окончательно.** В некоторых сценариях с такой же широкой
формулировкой precision возвращает `valid`; значит, отсутствие typed obligations не
является единственной причиной.

**Проверка.** На immutable registry одного и того же run-а сравнить два режима:

1. generated obligations с пустым registry;
2. заранее выведенный typed atomic registry из contract, без свободного текста.

Сравнивать только decoder outcome, confirmed positions и obligation coverage. Не менять
кандидатный набор и final generator.

**Ожидаемый корневой вариант исправления.** Atomic obligations должны быть получены из
typed contract/classifier до precision. Свободная генерация разрешается только для
действительно открытой семантической части запроса и не должна заменять отсутствие
contract obligations.

### H2. Transport schema описывает форму, но не семантическую связь `o -> g -> k`

**Сигналы из свежих trace.** Зафиксированы такие ошибки:

- `invalid_generated_obligation_assignment` в сценариях 4, 8 и 18;
- `duplicate_generated_obligation` в сценарии 10;
- `incomplete_generated_obligations` в сценарии 4;
- `missing_frame` в сценарии 17;
- `wrong_subset_member_cardinality` в сценарии 5.

Structured schema проверяет типы, ключи и локальные enum, но не может выразить всю
проверку: координата должна ссылаться на row с согласованными `subject/relation`, все
обязательства должны покрываться, а inventory должен дать ровно ожидаемое число members.
Эти ограничения появляются только после ответа, поэтому модель может получить
provider-valid JSON, который semantic decoder отвергает.

**Почему это правдоподобно.** Большие rows имеют до 63 units и много повторяющихся
локальных координат. Для модели допустимы по JSON Schema несколько вариантов, которые
runtime затем считает несовместимыми.

**Почему нельзя просто ослабить decoder.** Это позволит выбрать материал без доказанной
связи, схлопнуть независимые premises или принять неполный inventory. Такой шаг нарушит
recall/irrelevant tradeoff и provenance safety.

**Проверка.** Нужен focused replay, который сохраняет provider raw output только в
локальном тесте (не в telemetry), и печатает коды по стадиям:

```text
parse JSON -> frame/cardinality -> row-local warrants -> obligations -> subset/member cardinality
```

Для каждого rejected payload должно быть видно первое нарушенное звено, а не только
обобщенный `decoder_error`.

**Возможное универсальное исправление.** Разделить precision protocol на:

1. компактное обязательное решение позиций/gates;
2. отдельную bounded obligation assignment, если typed registry действительно требует ее.

Обе части должны ссылаться на один immutable mapping. Это уменьшит неоднозначность, не
открывая материалы за пределами primary selection.

### H3. Большой registry перегружает один precision вызов

**Сигнал.** Свежие registry unit counts включают `63, 63, 52` в одном payload; в
сценарии 21 было `6, 63, 63, 9, 11, 13, 1`. В сценарии 17 provider вернул
`missing_frame`, хотя selector до этого был valid.

**Почему это правдоподобно.** Один ответ одновременно содержит полный `g` для всех rows,
локальные warrants, generated obligations и `k`. Даже при provider-valid structured
transport модель может вернуть пустой/обрезанный message из-за output/context pressure.

**Почему это не сводится к лимиту token.** Некоторые payload такого же размера
проходят, а сценарий 17 не имеет provider error. Нужна фактическая длина prompt,
completion и finish reason из provider response, а не догадка по `candidate_count`.

**Проверка.** В безопасной telemetry добавить только размеры и статус:

- `registry_chars`, `schema_chars`, `prompt_tokens_estimate`;
- `completion_chars`;
- provider finish/reason code, если доступен;
- без текста rows и без API secrets.

Сравнить failures и passes по этим метрикам.

**Возможное исправление.** Для больших registries использовать bounded two-pass proof:
сначала row-level subset, затем локальные units только для selected rows. Лимит должен
оставаться текущим; это не разрешает добирать последние posts или весь архив.

### H4. Inventory/member classification смешивает покрытие корпуса и subset proof

**Сигнал.** Сценарий 5 получает `wrong_subset_member_cardinality` при
`expected_member_count=5`; сценарий 14 формально имеет critical recall, но
`critical_materialized=false`.

**Почему это правдоподобно.** Для inventory-запроса есть две разные задачи:

- классифицировать каждого member корпуса;
- выбрать и материализовать members, требуемые финальному ответу.

Сейчас они проходят через общий `g/k/member_warrants`, поэтому модель может правильно
классифицировать карточки, но не собрать ровно требуемый evidence pack.

**Проверка.** На полном immutable note catalog отдельно проверить:

1. member labels для всех rows;
2. expected member count;
3. material plan cardinality;
4. final pack cardinality.

Никаких provider calls между этими проверками.

**Возможное исправление.** Сначала детерминированно зафиксировать member classification
и provenance по каждому row, затем bounded selector выбирает pack из уже классифицированных
members. Нельзя принимать один документ как доказательство полного корпуса.

## Гипотезы по valid precision, но неправильному recall

### H5. Primary candidate pool не сохраняет cross-record coverage

**Сигналы.** Сценарии 9, 11, 12, 15, 16, 20 и 21 получают `precision=valid`, но:

- теряют критические posts;
- выбирают широкую заметку, которая не отвечает на все части вопроса;
- иногда выбирают unexpected note `note:27a2...`.

Это означает, что precision честно подтверждает уже предложенный subset, но не может
подтвердить material, который primary selector не удержал или не получил в registry.

**Почему это правдоподобно.** Precision не является поиском. Если нужный post не попал
в `selector_candidates`, ни один последующий gate не восстановит его без отдельной
bounded recall/reassessment ветки.

**Проверка.** Для каждого failure зафиксировать три множества:

```text
discovered candidates
primary selected refs
precision registry refs
```

Затем пометить critical ref как `absent-before-selector`, `rejected-by-primary`,
`demoted-by-precision` или `materialized-loss`. Это разделит discovery failure от
precision failure.

**Возможное исправление.** Contract должен заранее создавать независимый source/obligation
coverage target для каждой части cross-record запроса. Recall probes должны быть
ограничены typed gap и связями объектов, а не recent-N или полным архивом.

### H6. Referential/anaphoric queries не закрепляют anchor до поиска

Сценарии 9 и 19 спрашивают о «двух вариантах поставки», сценарии 15 сопоставляет план
с уже опубликованными постами, а 11/16 связывают тезис о канале с механизмом retrieval.
Если classifier не записывает устойчивый referent/anchor set, selector видит похожие
заметки и выбирает наиболее широкую, но не ту сущность.

**Проверка.** Сравнить contract для русской/французской формулировок 9 и 19:

- одинаковы ли target refs/source requirements;
- одинаковы ли alternative set и relation obligations;
- одинаков ли candidate source boundary.

Если contracts различаются до selector, проблема в classifier/contract, а не в языке
или prompt.

**Возможное исправление.** Детерминированно сохранять referent set и relation edges в
turn contract. Selector должен подтверждать relation по evidence, но не заново угадывать,
что означает местоимение или «второй вариант».

### H7. Series/catalog lifecycle closure не удерживает связанные posts

Сценарии 15, 20 и 21 требуют совместить заметку/план с published posts. В системе уже
есть catalog window, status-aware prefix и лимит серии, но свежий результат теряет
критические posts при valid precision.

**Проверка.** Для каждого candidate вывести только структурированные поля:

- `source_requirement_id`;
- `catalog_window_memberships.position/window_size`;
- `status` (`draft/published/scheduled`);
- `parent_post_id`/relation ref;
- причина, по которой row не попал в final prefix.

Нужно проверить, не закрывает ли prefix окно раньше нужного published row и не смешивает
ли он draft/scheduled с already-published audit.

**Возможное исправление.** Строить series relation из явных edges и typed status scope,
а temporal prefix применять только после semantic relation. Текущий лимит материалов
сохраняется; обход лимита недопустим.

### H8. Materialization policy теряет уже выбранные refs после precision

Сценарии 14, 15 и 21 показывают, что ref может быть selected/confirmed, но не попасть в
final pack (`critical_materialized=false`). Это отдельный слой после selector.

**Проверка.** Для каждого confirmed ref проследить:

```text
assessment -> material_plan card/full_text -> read action -> record_full_read_results
-> evidence pack item
```

В trace должны быть различимы `not_scheduled`, `read_failed`, `fidelity_downgrade`,
`pack_cardinality_drop` и `scope_guard_demote`.

**Возможное исправление.** Material plan должен быть monotonic относительно
provenance-checked positive assessment: выбранный ref нельзя тихо потерять из-за
не связанной probe или административного planner шага. При read failure нужно явно
оставить card-level evidence, если именно card разрешен контрактом, но не подменять его
full text.

## Гипотезы по конфигурации и воспроизводимости

### H9. Backend и worker могут использовать разные effective bindings

Флаги передавались обоим контейнерам, а после пересборки оба сервиса были перезапущены.
Тем не менее для каждого immutable run нужно подтвердить в telemetry:

- provider/model selector;
- provider/model precision;
- provider/model final answer;
- rollout flags/version;
- image/source digest.

Отсутствие такого подтверждения делает сравнение run-ов ненадежным: UI может показывать
новый backend, а Celery завершать старым процессом или другой binding.

### H10. Query-digest inspection может выбрать не тот run

`agent_unified_formal_canary_inspect.py` ищет последний run с совпадающим query digest.
Для immutable gate нужно сохранять конкретные `run_id` из запуска, а не только искать по
тексту после факта. Иначе повторный одинаковый вопрос может случайно заменить результат.

**Проверка.** Для следующей серии составить manifest:

```text
sequence -> run_id -> created_at -> source/image digest -> outcome
```

Инспектор должен принимать этот immutable mapping и не выбирать latest-by-query.

## Что нельзя считать исправлением

- `normative_value=false` для конкретной заметки или scenario;
- prompt-условие под русский/французский/английский вопрос;
- правило «всегда добавлять последние N posts»;
- передача всего catalog/full text в final generator;
- ослабление decoder так, чтобы любой coordinate считался доказательством;
- маркировка `decoder_error` как `valid` ради canary gate;
- отдельная ветка только для сценария 4 или только для одного document ref;
- изменение final generator с целью компенсировать неверный evidence pack.

## Предлагаемый порядок проверки

### Шаг 1. Получить детальную классификацию каждого failure

Добавить локальный debug-only report по immutable raw outputs (не в production trace):

- первый decoder failure code;
- row/unit/obligation coordinate;
- размеры schema/prompt/completion;
- primary/precision/materialization transitions.

### Шаг 2. Устранить contract ambiguity

Проверить generated mode при `decision_input_mode=true` и пустом
`decision_obligations`. Сформировать typed atomic registry из общих contract rules,
не из конкретных документов.

### Шаг 3. Разделить proof phases

Сделать bounded row-level adjudication и локальный obligation/member proof только там,
где он требуется. Сохранить один immutable mapping и текущие лимиты.

### Шаг 4. Исправить source coverage

Добавить универсальные cross-source coverage targets для независимых premises,
referential alternatives и series-to-published relations. Проверить draft/published/
scheduled scope и attachment fidelity.

### Шаг 5. Проверить materialization monotonicity

Подтвердить, что positive provenance-checked refs не исчезают между plan, read и pack,
и что отсутствие подходящего материала дает именно пустой context.

### Шаг 6. Повторить controlled runs

Порядок gate:

1. focused decoder/contract tests;
2. failed scenarios `4, 5, 8-12, 14-18, 20-21`;
3. полный immutable 21-run batch с сохраненными run ids;
4. проверка `21/21`, recall, irrelevant, provider/decoder/position и provenance.

Остановка на первом failure запрещена: нужен полный отчет по всем сценариям каждой версии.

## Критерий перехода от гипотезы к коду

Гипотеза считается подтвержденной только если controlled replay меняет ровно
предполагаемый слой и не ухудшает уже проходящие сценарии 1, 2, 3, 6, 7, 13 и 19.
После каждого изменения должны оставаться доказуемыми:

- tenant boundary;
- source/cardinality limits;
- opened-evidence provenance;
- status and attachment scope;
- empty-context behavior;
- отсутствие prompt/document-specific exceptions.
