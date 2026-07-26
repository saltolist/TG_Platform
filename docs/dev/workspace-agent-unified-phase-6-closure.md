# Единый план: закрытие фазы 6

**Статус:** безопасные локальные артефакты и ограниченный account pilot
реализованы 2026-07-26; фаза 6 остается незавершенной и default-off из-за 8
blocking gates

**Исходная реализация фазы 6:** commit
`e6bb80c8c984534710e08d2c30514dbd5f7519e7`

**Фазовый план:**
[workspace-agent-unified-phase-6-rollout.md](workspace-agent-unified-phase-6-rollout.md)

**Главный план:**
[workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)

## Цель

Закрыть оставшиеся quality gates фазы 6 и разрешить безопасный rollout без
скрытого уменьшения complete coverage, второго Selector/planner loop,
дополнительного Answer Model или неконтролируемого роста стоимости.

Оптимизируется transport единственного Context Selector. Архитектура фаз 1-5,
authoritative catalog, canonical `workspace.context-selector/v2`, verified
EvidencePack boundary и compatibility path сохраняются.

## Исходное состояние

На commit `e6bb80c8c984534710e08d2c30514dbd5f7519e7` пройдено 15 из 21
обязательного gate. Блокируют закрытие:

- relevant recall: `unavailable`;
- irrelevant selection rate: `unavailable`;
- end-to-end p95 latency: `unavailable`;
- LLM calls per run: `unavailable`;
- Selector provider p95 latency: `unavailable`;
- Selector p95 prompt tokens: `49736 > 30000` по snapshot-only
  `chars_div_4` estimator.

Полный локальный расчет текущего Selector request для 256 синтетических
кандидатов, включая system prompt и user prefix, равен примерно `50117` input
tokens. Это estimator, а не provider usage. Из них примерно `21632` tokens
приходятся на `card_text` с повторными trust wrappers и `27968` tokens - на
остальные candidate metadata.

Все unified flags остаются default-off. Значение `unavailable`, `missing`,
`inconclusive`, `not_measured` или `derived` не считается пройденным gate.

## Зафиксированное решение

### Две индексируемые проекции

При создании или изменении поста/заметки существующий background RAG worker
одним индексирующим LLM-вызовом формирует:

- `discovery_summary` длиной до 480 символов для embeddings и discovery;
- `selector_summary` длиной до 160 символов только для Context Selector.

`selector_summary` в порядке приоритета сохраняет тему, назначение, ключевые
сущности и существенные ограничения. Она не является answer evidence.

Формат versioned. Изменение поднимает summary schema version и запускает
rate-limited backfill. Карточка с отсутствующей, устаревшей или неподтвержденной
версией не считается покрытой: для complete source это создает blocking typed
gap, а не fallback к stale text.

Fallback генерации остается детерминированным и extractive. Нельзя добавлять
отдельный runtime LLM-вызов для сокращения карточки.

### Компактный Selector transport

Полный `CandidateEnvelope` остается в runtime state, checkpoint, validation и
durable rollout trace. В provider prompt передается отдельная versioned
wire-проекция с таблицей полей и rows.

Пример логической формы:

```json
{
  "columns": ["i", "kind", "data", "origin", "score", "sources", "parent", "fidelity"],
  "candidates": [
    [0, "note", "<workspace_data>title: ...\nsummary: ...</workspace_data>", "catalog", null, [0], null, "cf"]
  ]
}
```

Требования:

- model-visible candidate/source IDs являются локальными целыми индексами;
- runtime хранит immutable mapping index -> canonical ref/source ID;
- title и summary целиком находятся внутри untrusted-data boundary;
- fence tokens внутри данных neutralize-ятся существующим trust helper;
- `null`/default optional fields не сериализуются без необходимости;
- revisions, summary model/version, eligibility, status guards и `has_more`
  проверяются до LLM, но не дублируются в prompt;
- единственный source ID representation не дублируется singular/plural полями;
- semantic score остается nullable и не подменяется inclusion priority;
- parent остается relation metadata и не создает selection.

Selector возвращает компактные rows с candidate index, relevance, resolution,
confidence и reason code, а также dispositions для source indexes.
Детерминированный decoder разворачивает transport в
`ContextSelectorDecision`, после чего применяется неизмененная canonical v2
validation:

- каждый visible ref оценен ровно один раз;
- каждый visible source имеет ровно один disposition;
- unknown/duplicate/missing indexes отклоняются;
- role согласуется с relevance, resolution и fidelity;
- cardinality и complete assessment coverage соблюдены.

Wire encoder/decoder не является вторым Selector: semantic LLM call остается
ровно один, кроме уже разрешенного единственного schema retry.

### Размеры и режимы

`160` символов - основной вариант. `120` и `240` остаются offline challengers;
`80` не допускается к canary без доказанного non-inferior recall.

Целевые estimator budgets для согласованного compact transport:

| Cohort | Candidates | Selector input + output |
|---|---:|---:|
| relevant | до 16 | до 2500 tokens p95 |
| complete sync | до 100 | до 10000 tokens p95 |
| complete boundary | до 256 | до 22000 tokens p95 |

Существующий mandatory input gate `selector_p95_prompt_tokens <= 30000` не
ослабляется. Новые total-token ceilings строже и проверяются по фактической
provider telemetry, а estimator используется только для offline regression.

Первоначальный synchronous rollout ceiling равен 100 candidates. Это rollout
ограничение, а не top-k: authoritative coverage target не сокращается. Для
corpus 101-256 новый synchronous path не может вернуть `ready`, пока не выполнен
явный exhaustive flow или отдельный measured boundary canary. Corpus из 257
refs по-прежнему обязан иметь incomplete assessment и `ready=false`.

## Этапы реализации

### 1. Исправить измерительную границу

- benchmark сериализует полный system + user request тем же encoder, который
  используется provider call;
- отдельно фиксируются input, maximum valid v2 output и total tokens;
- измеряются размеры 16, 64, 100, 128 и 256 candidates;
- synthetic payload заменяется или дополняется реалистичными multilingual
  cards, titles, parent/source combinations и максимальным dialog context;
- `chars_div_4` явно маркируется estimator и не подменяет provider usage.

### 2. Добавить versioned selector summary

- определить storage/schema migration для `selector_summary` и ее version;
- расширить один существующий indexing call dual-output contract;
- реализовать deterministic fallback и freshness checks;
- обновить post/note upsert, restore и startup backfill;
- rate-limit backfill и наблюдать queue depth, failures и provider cost;
- не удалять старую discovery summary и embedding до подтвержденной замены.

### 3. Реализовать compact transport

- добавить pure encoder и decoder с versioned schema;
- передавать provider только compact projection;
- после decode создавать и валидировать canonical
  `workspace.context-selector/v2`;
- сохранить bounded retry, timeout и exact-only failure semantics;
- не менять material planner, policy compiler или Answer Model input;
- durable trace хранит безопасную полную metadata-проекцию и transport version,
  но не source text и не пользовательский ответ.

### 4. Добавить token/cost observability

Для каждого Selector call сохранять:

- provider и model;
- candidate count и cohort;
- actual input, cached input, output и total tokens;
- estimator tokens и отклонение estimator/provider;
- latency, timeout, retry и schema validation result;
- price snapshot/version и estimated cost, если тариф известен.

`provider_token_usage`, `provider_latency` и `estimated_cost` имеют explicit
availability. Неизвестный тариф дает `estimated_cost=unavailable`, а не ноль.
До canary владелец rollout фиксирует monetary ceiling для выбранной модели;
отсутствующий ceiling блокирует cost gate.

### 5. Offline quality experiment

Создать versioned, tenant-safe и обезличенный labeled cohort, включающий:

- relevant и irrelevant posts/notes;
- secondary topics и сущности вне первого предложения;
- multilingual и длинные cards;
- parent relations, nullable scores и ambient candidates;
- complete semantic corpora 64, 100, 128, 256 и overflow 257;
- selector timeout, malformed compact output и bounded retry.

На одном frozen cohort сравнить `120`, `160`, `240` и текущий compatibility
path. Основным остается самый короткий вариант, который проходит все quality
floors. Сокращение tokens само по себе не разрешает вариант с худшим recall.

### 6. Production-like shadow

Shadow выполняет catalog/contract/Selector/planner/pack comparison read-only:

- не вызывает дополнительный Answer Model;
- не меняет пользовательский ответ, evidence или mutation proposal;
- фиксирует planner decision/no-op и additive-search trace;
- измеряет recall/irrelevant selection только на размеченных или
  детерминированно проверяемых outcomes;
- разделяет cohorts relevant, factual, complete <=100 и complete 101-256.

### 7. Canary

Canary начинается только после прохождения offline и shadow gates:

1. factual reads;
2. relevant semantic flows до 16 candidates;
3. complete semantic flows до 100 candidates;
4. отдельный boundary/exhaustive cohort 101-256.

Размер cohort и observation window фиксируются в release attestation до старта.
Недостаточный sample size дает `inconclusive`, а не pass. На каждом шаге
проверяются checkpoint/resume, interrupted/cancelled, tenant/status guards,
latency, tokens, LLM calls, cost и answer invariance shadow path.

### 8. Rollback и default-on

Повторить rollback drill в staging/canary infrastructure для пяти исходных
сценариев и дополнительно во время summary backfill и compact decode failure.
Rollback обязан сохранять user message, ledger, known refs, evidence,
checkpoint и compatibility contract.

Feature flags включаются только в существующем порядке:

```text
unified_catalog -> typed_requirements -> unified_selector
-> verified_pack_boundary -> planner_policy -> default_on
```

`AGENT_PLANNER_POLICY_V1_ENABLED` эффективен только с canonical
`workspace.context-selector/v2` после успешного decode и verified EvidencePack
boundary. Compatibility path сохраняется минимум до review date `2026-10-24`.

## Обязательные gates закрытия

Все исходные 21 gates фазового плана сохраняются. Дополнительно обязательны:

- полный, а не snapshot-only Selector prompt измерен;
- actual provider input/output/total tokens measured;
- relevant p95 total tokens <= 2500;
- complete <=100 p95 total tokens <= 10000;
- complete boundary 256 p95 total tokens <= 22000;
- schema success/retry telemetry measured и находится в согласованном budget;
- monetary cost ceiling зафиксирован и cost p95 не превышает его;
- summary backfill coverage measured, stale selector summary не дает `ready`;
- compact decoder сохраняет canonical v2 assessment/source completeness;
- 257-ref overflow ready rate остается 0;
- staging/canary rollback drill проходит полностью.

Любой новый gate со статусом `unavailable`, `missing`, `inconclusive`,
`not_measured` или `derived` блокирует rollout так же, как исходные gates.

## Тесты

Минимальный обязательный набор:

- encoder/decoder round trip и deterministic ordering;
- unknown, duplicate, missing и out-of-range indexes;
- every-ref/every-source canonical v2 completeness;
- trust boundary для title, summary и forged fence tokens;
- summary version, stale revision, fallback и interrupted backfill;
- 16/64/100/128/256 token fixtures и 257 overflow;
- selector timeout, one retry, cancelled и resumed runs;
- exact/structural bypass без Selector call;
- planner policy sequencing и verified pack dependency;
- shadow Answer Model calls `0` и answer change rate `0`;
- golden/held-out phases 0-5 и phase-0 digest без изменений.

## Фактический результат 2026-07-26

Локально реализованы migration и dual-output indexing contract, compact
transport/decoder, complete freshness и 100-candidate sync guards, provider
observability schema, full-request benchmark, synthetic multilingual cohort и
семь rollback fixtures. Архитектура фаз 1-5, один semantic Selector call с одним
bounded retry, Answer Model boundary и полный runtime/checkpoint
`CandidateEnvelope` сохранены.

`chars_div_4` estimator для полного system + user request и maximum valid output
дал totals `2443/5791/8308/10280/19291` для `16/64/100/128/256` candidates.
Input gate на 256 (`17646 <= 30000`) и локальные estimator ceilings для 16, 100
и 256 проходят. Эти значения не являются provider usage и не закрывают
provider token gates.

Account-scoped pilot ограничен 20 чатами и 46 user messages, максимум 4 на чат.
Он дал 46 runs, actual provider telemetry для 31 Selector call и измеренный
backfill snapshot 13/13. Relevant p95 total tokens `1214.85 <= 2500`, complete
sync p95 `2559 <= 10000`, Selector p95 latency `3226.45 <= 30000 ms`, end-to-end
p95 `18466.8 <= 119061.25 ms`. Post-fix complete-sync окно содержит два runs по
13 refs: один valid после retry с 13/13 assessments и 2/2 sources, второй invalid
после обеих попыток. Всего canonical valid только 2/16 Selector runs, first-pass
valid 1/16; p95 LLM calls per run `4 > 1`.

Strict report содержит 34 mandatory gates: 26 measured pass и 8 blockers.
Полная таблица приведена в фазовом rollout-плане. Блокируют:

- relevant recall и irrelevant selection rate;
- LLM calls per run;
- complete boundary 256 provider total-token budget;
- schema first-attempt/final reliability budget;
- monetary ceiling, price/cost p95;
- staging/canary rollback drill.

Недоступны production shadow, размеченный ground truth, boundary-256 traffic,
trustworthy price snapshot/ceiling и staging/canary infrastructure.
Для них зафиксированы `unavailable` или `inconclusive`, без выдуманных pass.

Локальный blocked attestation `unified-phase6-2026-07-26`:
`sha256:387549cb5845d88a5f8dbf9c9cf2597a6ddf883100554a46840f449348661ebe`.
Phase-0 digest сохранен:
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`.
Scoped regression-набор фаз 0-6 и затронутого indexing/runtime:
`231 passed, 1 warning`; полный несвязанный suite не повторялся. Warning
`fastembed` существовал до closure. Frontend typecheck и lint измененных файлов
прошли.
Manual account pilot выполнен с явным включением пяти staged flags;
`AGENT_UNIFIED_DEFAULT_ON=false`, defaults в конфигурации не изменены.

## Exit criteria

- [x] dual discovery/selector summary реализованы, account backfill coverage
  измерен как 13/13; fleet-wide coverage не заявляется;
- [x] compact transport декодируется в verified canonical v2 без второго loop;
- [ ] полный prompt и provider token/latency telemetry доступны, но provider cost
  остается unavailable;
- [ ] `160` прошел non-inferior recall и остальные offline quality floors;
- [ ] все исходные и дополнительные gates имеют `measured pass`;
- [ ] factual, relevant, complete <=100 и boundary/exhaustive canary пройдены;
- [ ] rollback drill повторен в staging/canary infrastructure;
- [ ] итоговый quality report подписан и воспроизводим;
- [x] phase-6 план обновлен фактическими значениями без скрытых unavailable;
- [ ] default-on разрешен только после выполнения всех предыдущих пунктов.

Если хотя бы один критерий не выполнен, безопасные артефакты фазы 6 считаются
реализованными, но сама фаза остается незавершенной, flags default-off, а
блокирующие причины публикуются в quality report.

## Остаточные риски

- provider usage и latency измерены только для account pilot с 1-13 candidates;
  provider boundary canary на 256 refs отсутствует;
- production shadow и размеченный ground truth отсутствуют, поэтому relevant
  recall, irrelevant selection и non-inferiority summary `160` не доказаны;
- schema reliability недостаточна: post-fix один из двух complete runs не получил
  valid canonical decision даже после bounded retry;
- p95 LLM calls per run равен 4 при обязательном gate 1;
- manual account pilot не является formal production canary, потому что shadow,
  ground truth и все mandatory gates до его запуска не были закрыты;
- price snapshot, monetary ceiling и staging/canary infrastructure недоступны;
- default-on и удаление compatibility path запрещены, пока любой mandatory gate
  имеет статус, отличный от measured pass.

## Артефакты завершения

- migration и versioned summary schema;
- compact transport encoder/decoder;
- updated replay/shadow/canary observability;
- frozen labeled cohort без source leakage;
- provider token/latency/cost report;
- signed final quality attestation;
- staging/canary rollback report;
- обновленный фазовый план и отдельный commit только с closure фазы 6.

## Selector reliability remediation 2026-07-27

После исторического closure выполнена отдельная remediation transport boundary.
Versioned positional transport v2, typed decoder errors, metadata-driven
capability negotiation и один bounded retry реализованы без изменения архитектуры
фаз 1-5. V1 decoder и compatibility path сохранены. Answer Model после final
Selector failure не вызывается; exact/structural paths по-прежнему обходят
Selector.

Provider replay подтвердил transport validity для основного 160: 8/8 final и
first-attempt valid, 0 retries, 0 positional errors. Boundary-256 measurement
прошёл: `19188` input, `18944` cached input, `794` output, `19982` total,
`9531.7 ms`, estimator delta `+1735`. Однако critical required-evidence recall
составил только `7/8 = 0.875`, а irrelevant selection rate ухудшился до `1/7`
против compatibility `0/7`. Поэтому offline phase не пройдена, live canary не
запускался (`0 chats`, `0 messages`, `0 Selector decisions`).

Актуальный strict report: `33/42 pass`, 9 blocked; полная gate matrix и замены
исходных LLM/cost gates приведены в rollout-плане. Attestation:
`sha256:6a2aac8f05934e7bd71904c3ab325cfa030627668e3f7fdf19f6257230deca25`.
Phase-0 digest дважды сохранён без изменений:
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`.

Фаза 6 остаётся незавершённой. `AGENT_UNIFIED_DEFAULT_ON=false`; formal canary,
canary schema/coverage gates и staging rollback остаются unavailable. Измеренный
semantic false negative зафиксирован как blocker и основание для отдельного
conditional Recall Verifier plan, но Recall Verifier в этой работе не реализован.
