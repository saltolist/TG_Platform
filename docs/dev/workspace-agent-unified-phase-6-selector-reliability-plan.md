# Фаза 6: план исправления Selector reliability и окончательного закрытия

**Статус:** implementation plan; фаза 6 остается незавершенной и default-off

**Текущая точка:** `51e2d22be5cfe800b36cb5c9058dcdd2a0f120a3`

**Исходная реализация фазы 6:**
`e6bb80c8c984534710e08d2c30514dbd5f7519e7`

**Closure implementation:**
`712e19b58fc5a96c64a76bc5fe53933bbb5ec7b9`

**Account-pilot follow-ups:**
`6b84695770d0521d5eaa7d12876850da7785c009`,
`51e2d22be5cfe800b36cb5c9058dcdd2a0f120a3`

## Источники истины

1. [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)
2. [workspace-agent-unified-phase-6-rollout.md](workspace-agent-unified-phase-6-rollout.md)
3. [workspace-agent-unified-phase-6-closure.md](workspace-agent-unified-phase-6-closure.md)
4. Текущий код, migrations, tests, fixtures и durable pilot telemetry.

Старые ADR и roadmap используются только как исторический контекст. При
расхождении этого remediation-плана с фактическим кодом сначала проверяется
причина расхождения, затем решение отражается в tests и closure-документах.

## Исходное состояние

Strict phase-6 report содержит `26/34 pass` и 8 blockers:

1. relevant recall недоступен из-за отсутствия ground truth;
2. irrelevant selection rate недоступен по той же причине;
3. `p95 LLM calls per run = 4 > 1`, но метрика считает classifier, Selector и
   Answer Model вместе и измеряет не ту архитектурную границу;
4. actual provider total tokens для boundary 256 не измерены;
5. schema reliability недостаточна: `2/16` canonical-valid и `1/16`
   first-attempt-valid;
6. monetary ceiling не задан;
7. provider cost p95 недоступен при неизвестном тарифе;
8. staging/canary rollback drill не выполнен.

Account pilot: 20 чатов, 46 пользовательских сообщений, максимум 4 сообщения
на чат. Из 46 runs завершились 42, четыре завершились внешними provider/DNS
ошибками. Было 16 Selector runs, 31 provider call и 15 retries. Один
canonical-valid run дал правдоподобный grounded-ответ. При окончательном
Selector failure система могла сформировать ложный ответ об отсутствии данных.

Phase-0 digest обязан остаться неизменным:

```text
4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474
```

## Цель

Закрыть фазу 6, устранив измеренный корень `invalid_transport` и
`invalid_canonical`, доказав semantic quality на размеченном replay и повторном
ограниченном canary, не меняя архитектуру фаз 1-5 и не добавляя обязательный
второй Selector.

После закрытия:

- transport произвольного provider/model использует единый semantic contract;
- модель возвращает только минимальную недетерминируемую семантику;
- полный `workspace.context-selector/v2` строится и проверяется приложением;
- нужные refs попадают в verified EvidencePack с измеренным recall;
- malformed или оборванный результат не превращается в ложный ответ;
- default-on разрешается только после measured pass всех обязательных gates.

## Не входит в эту работу

- второй параллельный или последовательный semantic Selector;
- Recall Verifier до появления измеренных false negatives после transport fix;
- post-answer LLM auditor;
- доказательство того, что произвольная Answer Model оптимально использовала
  каждую supporting detail в свободном аналитическом тексте;
- новый planner loop или изменение planner policy фаз 1-5.

Условный follow-up после измеренных semantic false negatives описан отдельно:
[workspace-agent-recall-verifier-conditional-plan.md](workspace-agent-recall-verifier-conditional-plan.md).
Этот документ не разрешает включать Verifier до прохождения его собственных
shadow/non-inferiority gates.

Пропуск объектов в явных `complete`/classification ответах не относится к
отложенной свободной аналитике: существующий complete-coverage invariant
сохраняется и обеспечивается verified coverage manifest или детерминированным
renderer.

## Неподлежащие ослаблению ограничения

- полный `CandidateEnvelope` остается в runtime/checkpoint/trace;
- semantic Context Selector call остается один, кроме одного bounded retry;
- exact/structural paths не вызывают Selector;
- shadow не вызывает Answer Model и не меняет пользовательский ответ;
- planner policy работает только после verified canonical v2 и verified
  EvidencePack boundary;
- complete coverage нельзя сокращать через top-k;
- initial synchronous rollout ceiling остается 100 candidates;
- 101-256 не получают `ready` без explicit exhaustive flow или measured
  boundary canary;
- 257 refs всегда дают blocking incomplete и `ready=false`;
- `unavailable`, `missing`, `inconclusive`, `not_measured` и `derived` не
  считаются pass для mandatory gate;
- все unified flags остаются default-off до measured pass всех gates;
- provider/model neutrality: запрещена корректность, основанная на имени
  OpenAI, DeepSeek или конкретной модели.

## Решение

### 1. Единый минимальный semantic payload

Текущий transport заставляет LLM для каждого кандидата согласованно вернуть
index, relevance, role, resolution, confidence и reason, а затем отдельно
disposition каждого source. Это создает ненужные cross-field ошибки.

Новый versioned wire contract использует позиционный assessment vector.
Локальный candidate index определяется позицией, source dispositions не
генерируются моделью. Логическая plain-text форма:

```text
CS2|n=13|r=7f2a|a=dt8,ix9,st6,...|done
```

Где:

- `CS2` - transport version;
- `n` - точное число visible candidates;
- `r` - короткий request/registry nonce, который модель только копирует;
- `a` - ровно `n` fixed-width assessment codes в исходном порядке;
- первый символ - relevance `d|s|i`;
- второй символ - ограниченный reason code из canonical enum;
- третий символ - confidence bucket `0..9`;
- `done` отличает полный ответ от обрезанного.

Перед реализацией допускается скорректировать конкретную пунктуацию кадра, если
parser tests докажут более надежный вариант. Нельзя возвращать модели
обязанность генерировать runtime refs, source IDs, role, resolution или source
dispositions.

### 2. Capability negotiation без provider lock-in

Один semantic contract передается через лучший явно доступный transport:

1. strict JSON schema;
2. tool/function calling;
3. JSON mode;
4. plain completion с `CS2` frame.

Capability определяется конфигурацией provider/model или подтвержденным
adapter metadata, а не hardcoded списком брендов. Unsupported capability может
понизить transport tier в рамках того же semantic attempt. Ошибка semantic
validation не должна запускать неограниченный перебор tiers или скрытый второй
Selector.

Все tiers нормализуются в одну внутреннюю последовательность assessment codes и
один canonical decoder. Plain parser терпим к markdown fences и вводному тексту,
но принимает ровно один полный кадр с правильными `n`, nonce, cardinality и
completion marker. Forged frame tokens внутри title/summary нейтрализуются на
существующей untrusted-data boundary.

### 3. Детерминированное canonical expansion

Pure decoder по позиции и immutable mapping строит каждый
`ContextSelectorAssessment`:

- `ref` берется из mapping;
- `role=none` и `resolution=none` для irrelevant;
- `role=answer_evidence` для direct/supporting;
- resolution выбирается pure policy из reason code, required fidelity и
  available fidelity;
- confidence восстанавливается из bucket без выдуманного provider precision;
- source disposition выводится из assessments и source membership;
- ambiguous/search-more состояния выводятся только из разрешенных reason codes;
- every-ref/every-source completeness создается приложением.

Canonical validation остается последней обязательной границей и проверяет:

- точную cardinality и deterministic ordering;
- relevance/reason compatibility;
- role/relevance/resolution compatibility;
- available/required fidelity;
- source membership и source selection cardinality;
- отсутствие unknown/duplicate/missing refs и sources;
- complete assessment coverage.

Нельзя молча сокращать positive assessments до source maximum. Нарушение
cardinality возвращает typed validation error и может использовать единственный
bounded retry.

### 4. Typed retry

Decoder возвращает не только `None`, а typed result с стабильными кодами:

- `missing_frame`;
- `multiple_frames`;
- `wrong_version`;
- `registry_mismatch`;
- `missing_completion_marker`;
- `wrong_cardinality`;
- `invalid_assessment_code`;
- `invalid_relevance_reason`;
- `unsupported_fidelity`;
- `source_cardinality_exceeded`;
- `invalid_canonical`.

Retry получает компактный список фактических ошибок и тот же registry nonce.
Retry не содержит source text вне существующей trust boundary, не меняет
semantic задачу и выполняется не более одного раза.

### 5. Failure boundary

После окончательного Selector failure:

- Answer Model не вызывается;
- system не утверждает, что workspace data отсутствует;
- возвращается детерминированный честный application response о невозможности
  надежно завершить оценку контекста;
- typed gaps блокируют `ready`;
- candidate registry, raw-safe diagnostics, attempts, failure codes и provider
  telemetry сохраняются в checkpoint/trace;
- compatibility path не выбирает все объекты и не скрывает failure.

Это аварийная защита. Основным критерием готовности остается `invalid=0` в
formal canary, а не частота показа failure response.

## Этапы реализации

### Этап A. Зафиксировать baseline и контракты

1. Проверить HEAD, commits, `git status` и намеренные изменения документов.
2. Прочитать полностью этот план и closure-план, затем `Результат`,
   `Exit criteria`, `Остаточные риски` фаз 0-6.
3. Заморозить raw-safe формы pilot failures как parser/retry fixtures без PII,
   credentials и source content.
4. Зафиксировать до изменений strict report `26/34 pass`.

### Этап B. Реализовать transport v2

Основные файлы для проверки и минимально необходимых изменений:

- `backend/app/services/agent/research/selector_transport.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/planner_decision.py`;
- `backend/app/services/ai/llm.py`;
- provider configuration/schema, только если capability metadata отсутствует.

Требования:

1. Сохранить v1 decoder для checkpoint/replay compatibility до review date.
2. Добавить pure v2 encoder/parser/normalizer/decoder.
3. Не менять canonical `workspace.context-selector/v2` без доказанной
   необходимости; wire version не равен canonical version.
4. Вывести role, resolution и sources детерминированно.
5. Сократить `max_tokens` согласно fixed-width maximum output, сохранив
   provider token telemetry.
6. Записывать capability tier, parser result, canonical result и retry reason.

### Этап C. Исправить измерительную границу LLM calls

Текущий gate `LLM calls per run <=1` ошибочно агрегирует classifier, Selector и
Answer Model. Strict report должен отдельно измерять:

- `semantic_selector_initial_calls_per_selector_run = 1`;
- `semantic_selector_retry_rate`;
- `semantic_selector_final_valid_rate`;
- `semantic_selector_first_attempt_valid_rate`;
- total provider calls per run как diagnostic, а не как замена Selector gate;
- Answer Model calls после final Selector failure, обязательный порог `0`.

Это исправление границы измерения, а не разрешение второго Selector.

### Этап D. Labeled offline replay

Расширить обезличенный frozen cohort:

- relevant/irrelevant posts и notes;
- secondary-topic facts вне первого предложения;
- `ru`, `en`, mixed-language;
- nullable scores, multiple sources, parent relations;
- exact/structural bypass;
- complete 16/64/100/128/256 и overflow 257;
- malformed/truncated/multiple-frame responses;
- timeout/provider error и один retry;
- checkpoint/resume, interrupted/cancelled;
- tenant/status/security guards;
- forged fence/frame tokens.

Для каждого semantic case хранить ground-truth required refs, allowed supporting
refs и irrelevant refs. На одном cohort сравнить compatibility projection,
summary `120`, основной `160` и `240`. `80` остается offline challenger.

Quality gates:

- required/critical evidence recall = `1.0`;
- relevant recall не ниже compatibility baseline;
- irrelevant selection rate ниже compatibility baseline;
- `160` non-inferior по recall относительно `240`;
- structural and complete coverage = `1.0`;
- exact/structural Selector calls = `0`;
- shadow Answer Model calls = `0`, answer change rate = `0`.

Если ground truth или sample size недостаточны, результат остается
`inconclusive`; нельзя подобрать разметку под уже полученный output.

### Этап E. Provider boundary 256

На выбранном provider/model выполнить контролируемый вызов с реалистичным
multilingual fixture на 256 candidates и максимальным dialog context.

Фиксируются actual input, cached input, maximum valid output, actual output,
total tokens, latency, timeout, retry, parser/canonical result, provider/model и
estimator delta. Gate:

```text
actual provider p95 total tokens <= 22000
```

Estimator `chars_div_4` остается только offline estimator. Boundary canary не
разрешает synchronous ready для 101-256 автоматически. Fixture 257 обязан
оставаться incomplete с `ready=false`.

### Этап F. Formal account canary

Canary выполняется только после offline pass. Ограничение, одобренное rollout
owner:

- не более 20 чатов;
- не более 4 пользовательских сообщений в каждом чате;
- все сообщения, retries и provider calls отражаются в attestation;
- existing signed-in account/session используется без записи credentials в
  repository, fixtures, trace или документацию.

Сценарии заранее размечаются и включают factual, relevant, secondary-topic,
multilingual, complete, exact/structural, interrupted/resumed и один
контролируемый failure. Результат оценивается по EvidencePack и обязательному
coverage, а не только по `run.status=completed`.

Schema gates для этого ограниченного canary:

- final canonical-valid `20/20` Selector decisions;
- first-attempt canonical-valid не менее `19/20`;
- retries не более `1/20`;
- unknown/duplicate/missing positions = `0`;
- false `workspace data unavailable` answers = `0`;
- Answer Model calls after final Selector failure = `0`;
- complete/classification required object coverage = `1.0`.

Внешние DNS/provider failures учитываются отдельно и не превращаются ни в
Selector invalid, ни в pass. Если Selector runs меньше 20 из-за deterministic
bypass, reliability denominator и точный sample size явно публикуются; для
schema gate при необходимости используются дополнительные offline provider
replays в пределах утвержденного message ceiling.

### Этап G. Cost policy и observability

По решению rollout owner денежный бюджет ограниченного canary заменяется
жестким conversation/message ceiling. Это изменение closure contract должно
быть явным:

- mandatory gates `monetary ceiling configured` и `cost p95 within ceiling`
  заменяются measured gates соблюдения `chat_count <=20` и
  `max_user_messages_per_chat <=4`;
- unknown price и cost сохраняют `availability=unavailable`, а не получают
  ложный pass или нулевую стоимость;
- provider usage, latency и известная стоимость продолжают записываться;
- неизвестная стоимость остается residual observability limitation, но не
  mandatory gate именно этого capped canary.

Нельзя просто отметить старые monetary gates как pass: strict report и планы
должны показать замену gate и основание решения.

### Этап H. Rollback, regression и closure

1. Повторить rollback drill пяти исходных flags во время нового run, resume,
   timeout, schema mismatch, pack overflow, summary backfill и v2 decode failure.
2. Проверить сохранность user message, ledger, refs, evidence и checkpoint.
3. Прогнать scoped regression фаз 0-6 и затронутых indexing/runtime/provider
   адаптеров. Полный несвязанный suite не обязателен.
4. Повторить phase-0 report минимум дважды и проверить исходный digest.
5. Сформировать strict phase-6 report с каждым старым и замененным gate.
6. Обновить rollout/closure только фактическими измерениями.
7. Не отмечать фазу завершенной и не включать default-on при любом результате,
   отличном от measured pass.
8. Создать отдельный commit только с phase-6 selector reliability/closure
   работой и намеренными изменениями документов.

## Матрица закрытия текущих blockers

| Текущий blocker | Действие | Условие закрытия |
|---|---|---|
| relevant recall | frozen ground truth + replay | measured, не ниже baseline |
| irrelevant selection | тот же cohort | measured, ниже baseline |
| LLM calls per run | разделить metric boundaries | initial Selector calls = 1; retry отдельно |
| boundary 256 tokens | provider boundary canary | p95 total <=22000 |
| schema reliability | v2 vector + formal canary | 20/20 final, >=19/20 first attempt |
| monetary ceiling | заменить capped-canary gate | <=20 chats measured |
| cost p95 | не выдавать unavailable за pass; заменить risk control | <=4 user messages/chat measured |
| staging/canary rollback | выполнить на canary flags | pass rate 1.0 |

## Минимальные тесты

- v2 round trip для всех capability tiers;
- deterministic ordering и stable registry mapping;
- wrong version/nonce/cardinality/completion marker;
- malformed, truncated, multiple frames и wrapper text;
- reason/relevance combinations и confidence buckets;
- deterministic role/resolution/fidelity mapping;
- every-ref/every-source expansion;
- source membership/cardinality;
- forged fence/frame token neutralization;
- typed retry feedback и максимум одна повторная попытка;
- final failure без Answer Model;
- exact/structural bypass;
- complete <=100, boundary 256, overflow 257;
- checkpoint/resume и v1 checkpoint compatibility;
- provider usage/latency/schema telemetry;
- strict gate replacement без превращения unavailable cost в pass;
- phase-0 digest regression.

## Условия завершения

Фаза 6 закрывается только если одновременно выполнено следующее:

- все mandatory gates strict report имеют `availability=measured` и pass;
- Selector schema targets выполнены на frozen replay и formal canary;
- recall/irrelevant/non-inferiority имеют достаточный ground truth;
- boundary 256 provider budget измерен и пройден;
- 257 overflow остается blocking incomplete;
- capped-canary limits измерены и соблюдены;
- rollback drill пройден;
- scoped regression зеленый и phase-0 digest не изменился;
- quality report воспроизводим и содержит provider/model/cohort/sample sizes;
- compatibility path, owner и review date сохранены;
- default-on включен только после всех предыдущих пунктов.

Если хотя бы один gate не прошел, реализация и результаты коммитятся как
безопасный progress, но фаза остается незавершенной и default-off. Никакие
production/provider/canary результаты не выдумываются.

## Фактический результат реализации 2026-07-27

Этапы B-E, локальная часть G и локальный rollback этапа H реализованы. Positional
transport v2 прошёл provider replay без `invalid_transport` или
`invalid_canonical`: основной 160 дал 8/8 first/final valid, 0 retries и 0
position errors. Boundary-256 прошёл с actual provider total `19982 <=22000`
tokens и latency `9531.7 ms`; estimator/provider input delta равен `+1735`.

Offline quality gate не пройден: critical required-evidence recall `7/8=0.875`
при обязательном `1.0`, irrelevant selection `1/7` при compatibility baseline
`0/7`. Required recall 160 равен compatibility (`8/9=0.888889`) и не хуже 240,
поэтому только non-inferiority gate проходит. Измеренный semantic false negative
зафиксирован как blocker; второй Selector или Recall Verifier не добавлялся.

По precondition этапа F formal canary не запускался. Sample sizes равны нулю,
его reliability/coverage gates и staging rollback остаются unavailable. Strict
report: `33/42 pass`, 9 blockers, default-off. Full gate matrix находится в
rollout-плане. Phase-0 digest дважды сохранён, strict report воспроизводим с
attestation
`sha256:6a2aac8f05934e7bd71904c3ab325cfa030627668e3f7fdf19f6257230deca25`.

Локальные focused tests и compile-check прошли. Широкий DB-backed regression не
заявляется зелёным: он был остановлен после 229 pass из-за повторяющегося
PostgreSQL recovery (`2 failed`, `9 teardown errors` с одним infrastructure
root cause). Фаза 6 не закрыта, compatibility path и все flags default-off
сохранены.
