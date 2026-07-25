# Единый план: закрытие фазы 6

**Статус:** безопасные локальные артефакты реализованы 2026-07-26; фаза 6
остается незавершенной и default-off из-за 14 blocking gates

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
дал totals `2286/5635/8151/10122/19134` для `16/64/100/128/256` candidates.
Input gate на 256 (`17489 <= 30000`) и локальные estimator ceilings для 16, 100
и 256 проходят. Эти значения не являются provider usage и не закрывают
provider token gates.

Strict report содержит 33 mandatory gates: 19 measured pass и 14 blockers.
Полная таблица приведена в фазовом rollout-плане. Блокируют:

- relevant recall и irrelevant selection rate;
- end-to-end и Selector provider p95 latency, LLM calls per run;
- actual provider token usage и три provider total-token budgets;
- schema/retry telemetry на provider traffic;
- monetary ceiling, price/cost p95;
- deployed selector-summary backfill coverage;
- staging/canary rollback drill.

Недоступны credentials, production-like traffic, deployed backfill state,
ground truth, trustworthy price snapshot/ceiling и staging/canary infrastructure.
Для них зафиксированы `unavailable` или `inconclusive`, без выдуманных pass.

Локальный blocked attestation `unified-phase6-2026-07-26`:
`sha256:f5b7f27157b3a4835a2db0c9a07ae089699904e36fc91099076f9cbdb86ed370`.
Phase-0 digest сохранен:
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`.
Regression-набор фаз 0-6, closure и затронутого indexing/telemetry:
`460 passed, 1 warning` за `43.95s`; warning `fastembed` существовал до closure.
Canary не запускался, `AGENT_UNIFIED_DEFAULT_ON` остается выключен.

## Exit criteria

- [ ] dual discovery/selector summary реализованы, но deployed backfill coverage
  не измерен;
- [x] compact transport декодируется в verified canonical v2 без второго loop;
- [ ] полный prompt и actual provider token/cost telemetry доступны;
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

## Артефакты завершения

- migration и versioned summary schema;
- compact transport encoder/decoder;
- updated replay/shadow/canary observability;
- frozen labeled cohort без source leakage;
- provider token/latency/cost report;
- signed final quality attestation;
- staging/canary rollback report;
- обновленный фазовый план и отдельный commit только с closure фазы 6.
