# TG Platform Agent Architecture v2

Дата: 2026-08-07

Статус: accepted for incremental migration

## Решение

TG Platform остается agentic-системой, но retrieval переводится из одного сложного
LLM-протокола в code-owned workflow с узкими semantic specialists.

Это не миграция на конкретный SDK. Существующий LangGraph/runtime сохраняется как
provider-agnostic orchestrator. OpenAI Agents SDK полезен как эталон разделения
specialists, guardrails, state and traces, но замена библиотеки не исправит границы
ответственности сама по себе и необоснованно привяжет retrieval к одному provider API.

Целевой pipeline:

```text
request
  -> typed intent and atomic obligations
  -> deterministic source boundary
  -> candidate discovery
  -> bounded semantic labels
  -> deterministic minimal evidence pack
  -> provenance and policy guardrails
  -> answer generation from the verified pack
```

LLM отвечает за смысл, когда смысл нельзя надежно вывести кодом. Код отвечает за
tenant boundary, lifecycle/status boundary, corpus completeness, attachment/series
relations, budgets, provenance, cardinality и сборку итогового pack.

## Почему текущая архитектура нестабильна

Текущий precision-вызов одновременно должен:

1. понять вопрос;
2. решить, какие части ответа обязательны;
3. классифицировать каждый документ;
4. решить, один источник самодостаточен или нужен composite;
5. выбрать subset;
6. назначить row/unit coordinates;
7. повторить часть source policy classifier-а.

Structured Output проверяет только форму. Семантические зависимости `o -> g -> k`,
полнота inventory и минимальность subset проверяются позднее decoder-ом. Поэтому
provider-valid ответ может уничтожить корректный primary selection. Чем больше rows и
units, тем выше вероятность обрезанного frame или внутренне противоречивого решения.

Это не проблема самой идеи Agentic RAG. Это неправильная граница ответственности:
недетерминированная модель владеет политикой и сборкой данных, которые уже описаны
детерминированным runtime-контрактом.

## Соответствие современным практикам

OpenAI рекомендует manager-style workflow, когда основной runtime сохраняет владение
ответом, а specialist выполняет bounded задачу вроде classification. Specialist нужно
добавлять только при реальном изменении contract/policy; guardrails должны находиться
рядом с контролируемой операцией, а traces затем превращаются в repeatable eval dataset.

Anthropic рекомендует начинать с самого простого решения и использовать простые,
composable workflows для предсказуемых задач. Автономный agent нужен для открытых задач,
где число шагов нельзя заранее определить; retrieval selection TG Platform к такому
классу не относится.

Источники:

- https://developers.openai.com/api/docs/guides/agents
- https://developers.openai.com/api/docs/guides/agents/orchestration
- https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- https://developers.openai.com/api/docs/guides/agent-evals
- https://www.anthropic.com/engineering/building-effective-agents

## Компоненты v2

### 1. Intent classifier and deterministic contract compiler

Classifier возвращает только semantic delta: operation (`read`, `finish`, proposal),
workspace dependency и bounded topical source hints. Он не владеет retrieval policy.

Code-owned compiler получает frozen user query, pre-classifier target/corpus boundary и
semantic delta. Он детерминированно вычисляет:

- task profile and answer shape;
- required/optional primary corpora;
- structural predicates, explicit lifecycle statuses and ordering;
- unit of selection: record, complete member inventory or composition;
- runtime-owned obligations, fidelity and cardinality.

Одинаковый query и semantic intent обязаны давать один normalized contract, даже если
provider меняет необязательные `source_requirements`, `answer_shape`, `task_profile` или
формулировки obligations. Classifier не может добавить attachment/media source без
явного predicate и verified parent relation. Candidate details не могут менять вопрос
или порождать новые обязательства.

### 2. Source boundary

Runtime детерминированно строит допустимый registry:

- только current tenant/current user;
- только разрешенные corpora and targets;
- все lifecycle states для semantic member classification;
- bounded catalog window только для явно ordered задач;
- series membership only when the relation exists;
- attachments only through a verified parent relation;
- no recent-post fallback.

Если допустимых и релевантных материалов нет, pack остается пустым.

### 3. Semantic specialists

Два узких протокола заменяют монолитный precision frame.

Member classifier:

```json
{
  "version": 1,
  "count": 2,
  "registry_nonce": "...",
  "labels": {
    "0": {"match": true, "warrant_unit": 0},
    "1": {"match": false, "warrant_unit": -1}
  },
  "done": true
}
```

Каждый row классифицируется независимо. Модель не выбирает `k`, `best`, pack size или
source disposition. Runtime сохраняет все и только `match=true` rows.

Obligation classifier v3 uses sparse positive edges. Binary member mode is reserved
for a complete inventory with one category obligation; inventories and cross-record
requests with several independent obligations use sparse obligation labels.

```json
{
  "v": 3,
  "support": {
    "0": [{"obligation_index": 0, "warrant_unit": 0}],
    "1": [{"obligation_index": 1, "warrant_unit": 2}]
  }
}
```

Внешний ключ обозначает immutable row. Каждое значение содержит только доказанные
пары runtime-owned obligation/local evidence unit; отрицательный результат представлен
пустым списком. Runtime проверяет row, obligation index, duplicate edge и local warrant.
Модель не может добавлять obligations, candidate rows или владеть итоговым subset.

### 4. Deterministic pack assembler

Assembler работает только с validated labels:

- inventory: включает каждый matching member required source registry;
- record: выбирает один self-contained record;
- composition: решает deterministic set cover по atomic obligations;
- optional source: включается только если закрывает явное obligation;
- ties: меньший pack, более узкий proof span, более высокая verified fidelity, stable
  registry order;
- no match: empty pack.

Assembler не выполняет поиск и не открывает полный текст.

### 5. Fidelity escalation

Semantic classification использует свежие selector cards. Full text открывается только
после выбора row и только когда required claim нельзя подтвердить card-level evidence.
Ошибки provider-а не расширяют registry и не повышают fidelity.

### 6. Guardrails and failure semantics

- invalid schema/transport: specialist result is rejected, safe validated baseline is
  retained only when it already satisfies provenance and source boundaries;
- provider timeout/transient API error: same bounded baseline fallback;
- unsupported schema: capability downgrade without changing semantic contract;
- decoder error: never interpreted as "all selected rows are irrelevant";
- tenant/provenance/status violations: hard block, no fallback;
- final generator cannot search or mutate evidence membership.

## Что удаляется после миграции

- LLM-owned contract policy fields and generated obligations derived from candidates;
- one-frame `g/o/b/k` protocol for inventory and cross-record classification;
- LLM-owned subset cardinality;
- total dematerialization on one unassigned obligation;
- source-kind recovery in final generation;
- scenario-specific language rules and manifest-specific labels.

## Миграция

1. Ввести отдельный member-classification protocol и включить его для complete corpus
   inventories. Старый decoder остается для record/composition.
2. Ввести obligation-classification protocol и deterministic set-cover assembler.
3. Перевести record precision на тот же label format.
4. Удалить generated obligation mode и старый `g/o/b/k` protocol.
5. Зафиксировать 21 immutable canaries как обязательный release gate и добавить
   property tests для tenant, source, fidelity and empty-context invariants.

Каждый этап должен быть independently deployable и сравниваться на одном immutable
candidate registry. Нельзя менять manifest или labels между baseline и candidate run.

## Acceptance gate

- 21/21 immutable live canaries;
- critical recall 100%;
- irrelevant selection 0;
- no provider, validation, decoder or position errors;
- no full-text read without selected-row justification;
- no cross-tenant/cross-corpus evidence;
- current series material limit remains unchanged;
- empty context when no material matches.
