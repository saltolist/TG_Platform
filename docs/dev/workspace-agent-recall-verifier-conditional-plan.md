# Workspace Agent: условный план Recall Verifier

**Статус:** conditional follow-up; default-off; не входит в текущее закрытие
фазы 6 до выполнения prerequisites

**Зависимость:**
[workspace-agent-unified-phase-6-selector-reliability-plan.md](workspace-agent-unified-phase-6-selector-reliability-plan.md)

## Назначение

Recall Verifier нужен только для одной измеримой задачи: восстановить
действительно необходимые evidence refs, которые canonical-valid Context
Selector ошибочно пометил как нерелевантные, не ухудшив precision, fidelity,
coverage, latency и устойчивость системы.

Verifier не считается улучшением только потому, что добавил больше объектов.
Он получает право влиять на EvidencePack лишь после доказательства, что:

- required-evidence recall вырос;
- количество false promotions не ухудшило irrelevant selection rate;
- final-pack precision не ниже baseline;
- complete и structural invariants не изменились;
- latency/token/cost overhead находится в заранее согласованном бюджете;
- invalid/timeout verifier никогда не ухудшает результат primary Selector.

При недостаточном ground truth или sample size результат остается
`inconclusive`, feature flag остается выключенным.

## Почему это отдельный этап

Сначала должен быть исправлен transport основного Selector. Пока
`invalid_transport`/`invalid_canonical` доминируют, невозможно отличить ошибку
семантики от ошибки формата. Второй вызов в этот момент дублирует нестабильный
контракт, увеличивает latency и скрывает корень проблемы.

Recall Verifier рассматривается только если после достижения целевых schema
gates остаются размеченные semantic false negatives:

- final canonical-valid = `1.0` на formal cohort;
- first-attempt canonical-valid проходит установленный phase-6 budget;
- required refs и irrelevant refs размечены независимо от model output;
- false negative воспроизводится на frozen replay или production-like shadow;
- потеря произошла в Selector, а не в discovery, materialization или Answer
  Model.

Если нужный ref отсутствовал в CandidateEnvelope, Recall Verifier не является
лечением. Исправляется discovery/indexing/query-conditioned retrieval. Если ref
был в EvidencePack, но проигнорирован Answer Model, это также другая проблема.

## Гарантии и ограничения

### Что Verifier может улучшить

- semantic recall на уже найденном candidate registry;
- покрытие secondary-topic и multilingual evidence;
- восстановление direct evidence при слишком агрессивном primary selection;
- закрытие required source, когда релевантный member присутствовал среди
  кандидатов;
- диагностику систематических false-negative паттернов provider/model.

### Чего Verifier не гарантирует

- корректность произвольной слабой или custom-модели;
- обнаружение объекта, отсутствующего в CandidateEnvelope;
- правильность свободной финальной формулировки;
- снижение latency или provider cost;
- улучшение precision без admission policy и измерений.

## Неподлежащие ослаблению ограничения

- Verifier не заменяет и не повторяет canonical Context Selector целиком;
- Verifier выполняется только после canonical-valid primary decision;
- вызов последовательный, потому что проверяет конкретные omissions primary
  decision;
- Verifier add-only: он не может удалить или понизить primary selection;
- model-visible IDs остаются локальными integer positions;
- полный CandidateEnvelope остается в runtime/checkpoint/trace;
- verifier output не попадает напрямую в Answer Model;
- materialization происходит только после deterministic admission;
- exact/quote/edit/mutation/structural paths не вызывают Verifier;
- complete coverage не использует Verifier и не сокращается через top-k;
- corpus 257 refs сохраняет blocking incomplete и `ready=false`;
- planner loop не добавляется;
- verifier timeout/invalid/provider failure возвращает неизмененный baseline;
- flags default-off для неподтвержденных provider/model/cohort;
- capability transport не зависит от имени provider или модели.

## Целевая архитектура

```text
Canonical candidate registry
        |
        v
Primary Context Selector -- canonical-valid decision
        |
        +--> deterministic eligibility policy -- not eligible --> baseline pack
                         |
                         v
                 Recall Verifier
                         |
                         v
                 typed proposal only
                         |
                         v
          deterministic admission and validation
                         |
             +-----------+-----------+
             |                       |
          rejected                 admitted
             |                       |
       baseline selection      additive refs only
             +-----------+-----------+
                         |
                         v
             materialization + verified pack
                         |
                         v
                    Answer Model
```

Verifier не видит и не изменяет пользовательский ответ. В shadow он также не
изменяет material plan или EvidencePack.

## 1. Deterministic eligibility

Verifier нельзя вызывать на каждом run. Вызов разрешен только для semantic
`relevant` flow с canonical-valid primary decision и хотя бы одним
детерминированным risk signal:

1. required source имеет visible members, но primary decision не выбрал ни
   одного member;
2. primary selection пуст, хотя registry содержит semantic candidates;
3. omitted candidate содержит нормализованное exact entity/term match с
   запросом;
4. omitted candidate является member незакрытого required source;
5. multilingual или secondary-topic cohort соответствует доказанному frozen
   false-negative pattern;
6. primary decision пометил source как `ambiguous` или `search_more`, а
   разрешение можно получить среди уже visible candidates.

Nullable semantic score и model confidence не являются самостоятельным
основанием вызова. Они могут использоваться только как дополнительная
telemetry или tie-breaker после доказанной calibration.

Запрещенные cohorts:

- exact/structural deterministic fast paths;
- complete/classification coverage flows;
- mutation path;
- invalid primary Selector decision;
- incomplete/stale candidate registry;
- 101-256 без разрешенного exhaustive/boundary flow;
- 257 overflow;
- exhausted run deadline или provider call budget.

Eligibility policy является pure function и сохраняет reason codes в trace.

## 2. Минимальный verifier input

Verifier получает:

- user request и ограниченный dialog context;
- registry/request nonce;
- только compact cards omitted candidates, соответствующих risk signals;
- локальную позицию кандидата в исходном immutable registry;
- source memberships, parent relation, nullable score и available fidelity;
- список уже выбранных local indexes без source content;
- required source gaps и допустимое число additions.

Он не получает runtime-only metadata, canonical refs, tenant IDs, revisions,
credentials, полный checkpoint или уже материализованный source text. Title,
summary и query-conditioned snippet остаются внутри существующей
untrusted-data boundary. Forged frame/fence tokens neutralize-ятся.

Query-conditioned snippet допускается только если он детерминированно извлечен
из индексированного объекта, имеет provenance и не используется как answer
evidence до materialization.

## 3. Минимальный verifier output

Verifier возвращает fixed-cardinality vector только для переданных omitted
candidates. Логическая форма:

```text
RV1|n=4|r=18bc|a=k9,p8,k7,u5|done
```

Где:

- `k` - keep omitted;
- `p` - propose promotion as missed direct evidence;
- `u` - unresolved/uncertain, не является promotion;
- digit - coarse confidence bucket, не provider probability;
- position однозначно задает candidate index через immutable mapping;
- `n`, nonce и `done` защищают от stale/truncated output.

Никакие refs, role, resolution, source dispositions или content модель не
генерирует. Strict schema/tool/JSON/plain transports нормализуются в один
internal vector тем же provider-neutral capability adapter, что основной
Selector.

На первоначальном rollout Verifier выполняет максимум один provider call без
schema retry. Invalid/timeout дает typed no-op и baseline result. Возможность
bounded retry может быть рассмотрена отдельно только после измерения invalid
rate и latency; она не включается скрыто.

## 4. Deterministic admission

Proposal `p` не означает автоматическое включение. Promotion принимается только
при выполнении всех hard checks:

1. candidate существует в immutable registry и был omitted primary decision;
2. candidate доступен текущему tenant и прошел status/security/freshness guards;
3. candidate связан с текущим запросом хотя бы одним независимым risk signal;
4. verifier предложил direct evidence, а не supporting «на всякий случай»;
5. required/available fidelity совместимы;
6. source membership и selection cardinality не нарушены;
7. materialization и EvidencePack budget допускают addition без удаления
   primary required evidence;
8. complete/overflow invariants не затронуты;
9. proposal прошел canonical additive-decision validation.

Начальная политика использует two-key admission:

- semantic key: valid verifier proposal `p`;
- deterministic key: required-source gap, exact entity/term match,
  query-conditioned retrieval hit или доказанный false-negative cohort rule.

Без обоих ключей candidate остается omitted. Supporting evidence не добавляется
по одному verifier proposal. Его admission возможен только для явного required
source/relationship obligation и проходит отдельный measured gate.

Promotion ceiling задается source cardinality и отдельным canary config. Он не
может использоваться для сокращения complete coverage. При нехватке pack budget
Verifier не вытесняет primary evidence: proposal отклоняется с typed reason или
создает gap в разрешенном flow.

## 5. Baseline-preserving failure semantics

Любое из событий ниже обязано вернуть ровно исходную primary selection:

- Verifier не eligible;
- feature flag выключен;
- provider/model capability unavailable;
- timeout, cancellation или provider error;
- malformed/truncated output;
- wrong nonce/cardinality;
- unknown/duplicate position;
- admission validation failure;
- budget/deadline exhausted;
- checkpoint resumed с несовместимой verifier version.

Failure Verifier не блокирует `ready`, если primary path был независимо ready,
не вызывает Answer Model повторно и не меняет user response. Trace фиксирует
availability и typed reason без выдачи failure за pass.

Checkpoint сохраняет primary decision, verifier eligibility signature,
proposal, admission result и provider call identity. Resume не должен повторять
уже завершенный verifier call при неизменном registry/query/primary signature.

## 6. Shadow experiment

До active admission Verifier работает только read-only:

- primary Selector, material plan, EvidencePack и Answer Model остаются
  неизменными;
- Answer Model calls shadow path = `0`;
- user answer change rate = `0`;
- proposals и hypothetical admissions сравниваются с frozen ground truth;
- отдельно считаются recovered true positives и false promotions;
- результаты разделяются по provider/model, language, candidate count, source
  topology и eligibility reason.

Обязательная confusion matrix:

| Ground truth | Verifier/admission add | Результат |
|---|---:|---|
| required/relevant | yes | recovered true positive |
| required/relevant | no | remaining false negative |
| irrelevant | yes | false promotion |
| irrelevant | no | correct no-op |

Нельзя считать proposal полезным только по согласию с другой LLM. Ground truth
создается независимой разметкой или детерминированно проверяемым outcome.

## 7. Mandatory quality gates

Active canary запрещен, пока все следующие показатели не имеют
`availability=measured`:

- `primary_selector_final_valid_rate` проходит phase-6 gate;
- `verifier_eligible_sample_size` достаточен для cohort comparison;
- `required_evidence_recall_delta > 0` на cohort с исходными false negatives;
- critical required-evidence recall после admission = `1.0`;
- relevant recall не ниже shadow baseline ни в одном обязательном language
  cohort;
- irrelevant selection rate не выше baseline;
- final-pack precision не ниже baseline;
- false-promotion rate находится в заранее зафиксированном ceiling;
- verifier invalid/timeout result-change rate = `0`;
- primary selected-ref removal rate = `0`;
- exact/structural/complete verifier call rate = `0`;
- shadow Answer Model calls = `0`;
- shadow user-answer change rate = `0`;
- tenant/status/security violation rate = `0`;
- checkpoint duplicate verifier call rate = `0`;
- provider tokens, latency и известная стоимость измерены;
- p95 latency/token/cost overhead проходит численные ceilings, зафиксированные
  до canary.

Не следует заранее выдумывать абсолютный latency или cost threshold. Rollout
owner фиксирует его после shadow measurement и до active canary. Изменение
ceiling после просмотра canary результата требует новой attestation.

Non-inferiority должна проверяться не только aggregate-значением. Regression в
critical, multilingual или required-source cohort блокирует rollout, даже если
общая средняя улучшилась.

## 8. Active canary

После shadow pass:

1. включить admission только для одного размеченного provider/model profile;
2. ограничить eligible traffic и maximum additions конфигурацией;
3. сохранить compatibility path и мгновенный rollback flag;
4. проверять каждый changed EvidencePack против ground truth;
5. отдельно фиксировать Answer Model response только как downstream
   observation, не использовать его как замену evidence metrics;
6. остановить canary при первом security/coverage violation или статистически
   подтвержденном precision regression;
7. при inconclusive sample продолжить shadow, не расширять rollout.

Новый provider/model не наследует semantic qualification другого профиля. Он
может использовать универсальный transport, но admission остается default-off
до measured compatibility/quality pass.

## 9. Observability

Durable trace для каждого eligible run содержит:

- verifier schema/transport version и capability tier;
- provider/model и qualification profile;
- eligibility result/reason;
- omitted candidate count и proposed/admitted/rejected positions;
- admission rejection reason по каждому proposal;
- ground-truth label только в replay/shadow fixtures;
- primary и hypothetical/final pack membership diff;
- required recall, irrelevant selection и pack precision deltas;
- input/cached/output/total tokens;
- latency, timeout, cancellation и schema result;
- estimator/provider delta;
- price snapshot и estimated cost, если известны;
- checkpoint/resume identity;
- feature-flag state и rollback reason.

Raw source content, credentials и PII в telemetry не сохраняются.

## 10. Тесты

### Pure/unit

- eligibility для каждого allowed/forbidden cohort;
- stable omitted-index mapping и nonce;
- all keep/propose/uncertain combinations;
- malformed/truncated/multiple frames;
- wrong version/nonce/cardinality/completion marker;
- forged frame/fence tokens;
- add-only invariant;
- two-key admission;
- source membership/cardinality;
- fidelity and budget rejection;
- no primary evidence eviction;
- deterministic ordering and checkpoint signature.

### Integration

- canonical-valid primary -> eligible -> admitted addition;
- canonical-valid primary -> verifier no-op -> identical baseline pack;
- verifier invalid/timeout/provider error -> identical baseline pack;
- interrupted/cancelled and checkpoint/resume without duplicate call;
- tenant/status/security rejection;
- exact/structural/complete paths with zero verifier calls;
- 101-256 guards and 257 blocking incomplete;
- shadow with zero Answer Model calls and zero answer changes;
- active flag rollback before/after proposal and during materialization.

### Offline replay

- known primary false negatives recovered;
- irrelevant near-topic cards not promoted;
- secondary-topic facts;
- `ru`, `en`, mixed-language;
- multiple required/optional sources;
- parent/source relations;
- nullable semantic score;
- weak/custom provider output wrappers;
- per-provider/model qualification report;
- repeated replay produces stable digest.

## Rollback

Отдельный flag, например `AGENT_RECALL_VERIFIER_ENABLED`, default-off. Его
выключение обязано:

- прекратить новые verifier calls;
- сохранить primary Selector и verified pack path;
- не потерять checkpoint, evidence, ledger или user message;
- игнорировать неadmitted proposals старых checkpoints;
- сохранить trace для анализа;
- не требовать rollback canonical v2 transport.

Compatibility path сохраняется до отдельной review date и владельца. Нельзя
откатывать только admission validator, оставляя LLM proposals активными.

## Решение о включении

Recall Verifier включается только если итоговый отчет доказывает одновременно:

```text
schema stable
AND measured primary false negatives exist
AND verifier recovers required evidence
AND irrelevant selection does not regress
AND final-pack precision does not regress
AND no invariant/security regression
AND latency/token/cost ceilings pass
AND rollback drill passes
```

Если хотя бы одно условие не выполнено, Verifier остается shadow/default-off.
Его код и telemetry могут быть сохранены как безопасный эксперимент, но нельзя
утверждать, что он делает систему лучше.
