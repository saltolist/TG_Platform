# Workspace Agent: план окончательного semantic closure фазы 6

**Статус:** implementation plan; phase 6 остается default-off до measured pass
всех mandatory gates.

**Baseline при создании плана:**
`bd86b5b01639aa4e6f7944dff7a29cd358e10355`.

**Связанные документы:**

- [workspace-agent-unified-phase-6-selector-reliability-plan.md](workspace-agent-unified-phase-6-selector-reliability-plan.md);
- [workspace-agent-recall-verifier-conditional-plan.md](workspace-agent-recall-verifier-conditional-plan.md);
- [workspace-agent-unified-phase-6-rollout.md](workspace-agent-unified-phase-6-rollout.md);
- [workspace-agent-unified-phase-6-closure.md](workspace-agent-unified-phase-6-closure.md);
- [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md).

## 1. Цель

Закрыть оставшиеся semantic, canary и rollback blockers фазы 6, не скрывая
ошибки дополнительными вызовами и не ослабляя quality floors.

Transport remediation уже доказала, что основной positional Context Selector
может работать без `invalid_transport` и `invalid_canonical`. Следующая работа
должна:

1. точно локализовать измеренный critical false negative и false positive;
2. сначала попытаться исправить semantic quality одного primary Selector;
3. использовать Recall Verifier только как явно разрешенную conditional ветку,
   если primary-only path не достигает quality floors;
4. пройти offline qualification, formal live canary и canary rollback;
5. получить measured pass каждого mandatory gate;
6. оставить default-off при любом failed, unavailable или inconclusive gate.

Закрытие фазы является результатом измерений, а не обязательным исходом одного
запуска плана. Нельзя изменить labels, sample или thresholds после просмотра
неудачного результата, чтобы объявить фазу завершенной.

## 2. Фактическая исходная точка

На baseline `bd86b5b`:

- strict report: `33/42 pass`, 9 blockers;
- summary 160 provider replay: final valid `8/8`, first-attempt valid `8/8`,
  retries `0`, positional errors `0`;
- required recall: `8/9 = 0.888889`, compatibility baseline `8/9`;
- critical required-evidence recall: `7/8 = 0.875`, target `1.0`;
- irrelevant selection: `1/7 = 0.142857`, compatibility baseline `0/7`;
- boundary 256: `19982 <=22000` actual provider total tokens, valid с первой
  попытки;
- formal live canary: `0 chats`, `0 messages`, `0 Selector decisions`;
- local rollback drill: pass; staging/canary rollback: unavailable;
- phase-0 digest:
  `4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`;
- `AGENT_UNIFIED_DEFAULT_ON=false`;
- широкий DB-backed regression был остановлен из-за повторяющегося PostgreSQL
  recovery, а не из-за доказанного Selector assertion regression.

Текущие blockers:

1. `irrelevant_selection_rate`;
2. `selector_schema_reliability_within_budget`;
3. `selector_first_attempt_valid_rate`;
4. `selector_final_valid_rate`;
5. `selector_retry_rate`;
6. `selector_position_error_count`;
7. `complete_classification_required_object_coverage`;
8. `required_critical_evidence_recall`;
9. `staging_canary_rollback_drill_pass_rate`.

Матрица закрытия:

| Blocker | Действие | Доказательство закрытия |
|---|---|---|
| irrelevant selection | исправить zero-baseline gate и semantic precision | measured value `0` на qualification и canary |
| schema reliability composite | вычислять из дочерних canary metrics | measured composite `1` при sample >=20 |
| first-attempt validity | formal canary | минимум `19/20` |
| final validity | formal canary | `20/20` |
| retry rate | formal canary | максимум `1/20` |
| position errors | formal canary | unknown/duplicate/missing/out-of-range = `0` |
| complete/classification coverage | проверять EvidencePack, не status | required-object coverage `1.0` |
| critical recall | primary correction или conditional Verifier | `1.0` на qualification и canary |
| staging/canary rollback | выполнить drill в canary infrastructure | pass rate `1.0` и сохранность state |

## 3. Неподлежащие ослаблению ограничения

- архитектура фаз 1-5 не меняется;
- primary semantic Context Selector остается один, с максимум одним bounded
  schema retry;
- runtime fallback между capability tiers не добавляется;
- exact/quote/edit/mutation/structural paths не вызывают Selector или Verifier;
- complete/classification flows не используют Recall Verifier и не сокращают
  coverage через top-k;
- synchronous primary Selector ceiling остается 100;
- 101-256 требуют explicit exhaustive flow и сохраняют measured boundary guard;
- 257 refs всегда blocking incomplete с `ready=false`;
- полный CandidateEnvelope остается в runtime/checkpoint/trace;
- title, summary и snippets остаются untrusted data;
- planner policy работает только после verified canonical decision и verified
  EvidencePack boundary;
- Answer Model не вызывается после final primary Selector failure;
- shadow Answer Model calls и answer change rate равны нулю;
- Recall Verifier, если активирован, является отдельным add-only call, а не
  вторым Selector или planner loop;
- Verifier выполняет максимум один provider call без retry;
- invalid/timeout/provider failure Verifier возвращает неизмененный primary
  result;
- unavailable, missing, inconclusive, not_measured и derived никогда не pass;
- compatibility path сохраняется до успешного closure и review;
- price/cost остаются unavailable, пока нет достоверного snapshot;
- chat/message ceilings не расширяются: максимум 20 chats и 4 user messages на
  chat;
- credentials, raw user content, tenant/account IDs и secrets не попадают в
  repository, fixtures, logs или отчеты.

## 4. Исправить контракт двух непроходимых gates

До semantic tuning нужно исправить две проблемы самого gate evaluator.

### 4.1 Irrelevant selection

Текущее правило требует `irrelevant_selection_rate < baseline`. Compatibility
baseline равен нулю, поэтому даже идеальный результат `0` не может пройти.

Не ослабляя quality, заменить правило на:

```text
irrelevant_selection_rate <= compatibility baseline
AND irrelevant_selection_rate <= 0.0 для текущего frozen cohort
```

Практически gate может использовать `MAX threshold=0.0`, а compatibility
baseline остается diagnostic. Tests обязаны доказать:

- `0` против baseline `0` проходит;
- любое значение `>0` блокирует;
- unavailable/inconclusive не проходит.

### 4.2 Composite schema reliability

`selector_schema_reliability_within_budget` должен стать явным composite gate:

```text
value = 1 только если одновременно:
  first_attempt_valid_rate >= 0.95
  final_valid_rate = 1.0
  retry_rate <= 0.05
  position_error_count = 0
  formal Selector decisions >= 20
иначе value = 0 или availability != measured
threshold = 1
```

Composite не заменяет дочерние gates: strict report показывает и проверяет все
пять строк. Нельзя выставлять composite pass вручную.

## 5. Этап A: scenario-level attribution

Текущий aggregate фиксирует `7/8` и `1/7`, но не сохраняет, какой scenario/ref
ошибочен. Перед изменением prompt или кода:

1. расширить provider replay raw-safe scenario rows;
2. для каждого scenario сохранять только IDs frozen fixture, expected labels,
   selected positions, reason codes, schema result и attempt count;
3. отдельно записать missed critical refs и selected irrelevant refs;
4. не сохранять provider raw output или source/user content;
5. повторить summary 160 replay на неизмененном baseline, чтобы проверить
   воспроизводимость;
6. классифицировать каждый miss по boundary:
   - ref отсутствует в CandidateEnvelope: discovery/indexing defect;
   - ref присутствует, но summary не содержит нужный факт: summary projection;
   - ref и факт присутствуют, primary assessment irrelevant: Selector semantic;
   - ref selected, но не materialized: material-plan/fidelity defect;
   - ref в verified pack, но ответ его игнорирует: Answer Model defect.

Recall Verifier разрешен только для третьего случая. Остальные boundaries
исправляются у владельца соответствующего слоя.

## 6. Этап B: усилить ground truth без подгонки

Разделить cohort на два versioned набора:

- calibration: текущие случаи и воспроизведенные failures, разрешенные для
  prompt/summary tuning;
- untouched qualification: независимая разметка, которая не используется при
  выборе prompt или policy.

Qualification cohort должен включать как минимум:

- 20 semantic scenarios;
- 20 critical required refs;
- 20 явно irrelevant refs;
- `ru`, `en`, mixed и минимум один дополнительный язык;
- secondary-topic facts вне первой фразы;
- posts, notes, parent relations, multiple sources и nullable score;
- близкие по теме, но неправильные distractors;
- required-source gap и empty-primary-selection cases;
- exact/structural bypass и complete/overflow guards как отдельные invariants.

Каждый semantic scenario хранит required, critical, allowed supporting и
irrelevant refs. Labels создаются до provider replay. Изменение label после
output требует новой cohort version и не может использоваться в текущей
attestation.

## 7. Этап C: primary-only semantic correction

Сначала исправить один основной Selector без дополнительного provider call.

Проверять по отдельности и в минимальных комбинациях:

1. semantic instruction: явно отличать direct evidence от near-topic card;
2. reason-code definitions и примеры для secondary-topic/required evidence;
3. query goal и ограниченный dialog context;
4. selector summary projection 160 и 240;
5. compatibility projection только как baseline;
6. deterministic resolution/source expansion без изменения model output;
7. optional query-conditioned extractive snippet только с provenance,
   deterministic bounds и untrusted-data protection.

Нельзя:

- добавлять список ground-truth refs в prompt;
- использовать scenario IDs как model-visible hints;
- делать forced selection required source;
- выбирать все near-topic candidates;
- менять cohort labels под результат;
- добавлять второй primary semantic attempt;
- скрывать false positives через post-hoc deletion без общей deterministic
  policy.

Выбор primary variant производится лексикографически:

1. critical required recall = `1.0`;
2. irrelevant selection rate = `0` на текущем zero-baseline cohort;
3. relevant recall не ниже compatibility в каждом mandatory language cohort;
4. final-pack precision не ниже baseline;
5. shortest request, который проходит предыдущие floors;
6. actual provider token/latency ceilings проходят.

Если primary-only path проходит calibration и untouched qualification, Recall
Verifier не реализуется и работа переходит к formal canary.

## 8. Этап D: conditional Recall Verifier

Если primary-only path после добросовестного этапа C не проходит critical recall
или irrelevant floor, этот план является новым явным решением, разрешающим
реализацию conditional Recall Verifier по отдельному плану
`workspace-agent-recall-verifier-conditional-plan.md`.

Перед реализацией должны быть одновременно доказаны:

- primary transport invalid rate = `0` на qualification replay;
- false negative воспроизводим;
- required ref присутствует в immutable CandidateEnvelope;
- summary/snippet содержит достаточный semantic signal;
- miss происходит до materialization и EvidencePack;
- exact/structural/complete/overflow cohorts исключены eligibility policy.

Минимальная active architecture:

```text
canonical-valid primary Selector
-> pure eligibility
-> one add-only Verifier call, no retry
-> deterministic two-key admission
-> verified materialization/EvidencePack
-> Answer Model
```

Добавить отдельный default-off flag, например
`AGENT_RECALL_VERIFIER_V1_ENABLED`. Он эффективен только после unified Selector
и до verified pack boundary. Primary Selector metrics, Verifier metrics и total
provider calls измеряются раздельно.

Initial limits:

- maximum additions: 1 per eligible run;
- verifier call rate на exact/structural/complete: 0;
- verifier retry count: 0;
- primary selected-ref removal rate: 0;
- invalid/timeout verifier result-change rate: 0;
- shadow Answer Model calls: 0;
- shadow user-answer change rate: 0;
- verifier p95 total tokens: <=2500;
- verifier p95 latency overhead: <=10000 ms;
- unknown price/cost остается unavailable, а live traffic остается внутри
  утвержденных chat/message ceilings.

Сначала выполнить shadow: proposals и hypothetical admissions не меняют pack
или answer. Active admission разрешен только после measured pass всех verifier
gates из conditional plan, включая critical recall `1.0`, zero false promotion
на mandatory qualification cohort и non-inferior final-pack precision.

## 9. Этап E: offline qualification

Для выбранного primary-only или primary+Verifier path:

1. заморозить provider/model/capability/cohort/prompt/summary versions;
2. выполнить calibration report отдельно от qualification report;
3. выполнить untouched qualification минимум дважды;
4. получить final/first-attempt valid без transport errors;
5. получить critical required recall `1.0` в каждом повторе;
6. получить irrelevant selection `0` на zero-baseline cohort;
7. подтвердить relevant recall и final-pack precision non-inferiority;
8. подтвердить exact/structural Selector/Verifier calls = 0;
9. подтвердить complete coverage = 1.0 и overflow-257 ready rate = 0;
10. повторить boundary-256 actual provider measurement после любого изменения
    primary prompt/summary;
11. отдельно измерить Verifier overhead, если он реализован;
12. не начинать live canary при любом failed/inconclusive результате.

Provider failure учитывается отдельно. Он не становится semantic miss, но
qualification остается inconclusive, пока минимальный valid sample не набран в
заранее установленном traffic/provider-call ceiling.

## 10. Этап F: изолированный regression environment

Не использовать нестабильный shared PostgreSQL как основание для closure.

1. создать отдельный disposable test PostgreSQL/compose project с отдельным
   database name, volume и port;
2. не удалять и не пересоздавать пользовательский/shared database;
3. применить migrations к isolated test DB;
4. запустить focused Selector/provider/runtime/indexing tests serially;
5. повторить девять tests, ранее затронутых recovery errors;
6. проверить отсутствие Postgres server-process crashes/recovery в test logs;
7. запустить scoped phase 0-6 regression, но не полный unrelated suite;
8. дважды выполнить phase-0 report и сохранить исходный digest;
9. выполнить strict phase-6 report минимум 50 раз.

DB infrastructure defect фиксируется отдельно и не превращается в product
failure или pass. Для closure нужен зеленый scoped run в стабильной среде.

## 11. Этап G: formal live canary

Canary запускается только после полного offline pass через существующую
авторизованную платформенную сессию без чтения или сохранения credentials.

До первого сообщения создать versioned canary manifest:

- provider/model и code commit;
- максимум 20 chats и 4 user messages per chat;
- ровно 20 planned semantic Selector decisions;
- дополнительные exact/structural проверки не входят в denominator;
- query, expected refs, expected source coverage и criticality для каждого
  scenario;
- replacement policy для внешнего provider/DNS failure;
- stop conditions;
- rollback sequence.

Для каждого run проверять durable trace, CandidateEnvelope, canonical primary
decision, Verifier/admission при наличии, EvidencePack и ответ. `completed`
status сам по себе не pass.

Обязательные targets:

- final canonical-valid primary decisions = `20/20`;
- first-attempt canonical-valid >=`19/20`;
- primary retries <=`1/20`;
- primary position errors = `0`;
- composite schema reliability = `1`;
- critical required-evidence recall = `1.0`;
- irrelevant selection rate = `0` для размеченных zero-baseline cases;
- complete/classification required-object coverage = `1.0`;
- false workspace-data-unavailable answers = `0`;
- Answer Model calls after final primary failure = `0`;
- exact/structural Selector and Verifier calls = `0`;
- primary selected-ref removal by Verifier = `0`;
- false Verifier promotions = `0`, если Verifier active;
- user message, ledger, refs, evidence и checkpoint сохранены.

Внешние provider/DNS failures публикуются отдельно и не считаются ни schema
invalid, ни pass. Нельзя превышать chat/message ceiling ради добора sample.

## 12. Этап H: canary rollback drill

В той же canary infrastructure повторить:

1. staged feature-flag rollback;
2. resume старого checkpoint;
3. primary Selector timeout;
4. schema mismatch;
5. pack overflow;
6. summary backfill interruption;
7. compact primary decode failure;
8. Verifier invalid/timeout/admission rejection, если он реализован.

Каждый сценарий должен сохранить user message, ledger, known refs, evidence,
checkpoint и compatibility contract. Pass rate = `1.0`. Drill не должен
генерировать второй пользовательский ответ.

## 13. Этап I: strict closure и default-on decision

Обновить strict report так, чтобы он содержал:

- все исходные 42 gates;
- исправленные, но не ослабленные semantics двух gates из раздела 4;
- все новые mandatory Verifier gates, если Verifier реализован;
- provider/model/cohort/prompt/summary versions и sample sizes;
- actual provider usage и latency;
- price/cost availability без выдуманного значения;
- offline, canary и rollback attestation;
- результат isolated scoped regression;
- phase-0 digest;
- compatibility owner/review date;
- exact live canary chat/message counts.

Phase 6 можно отметить закрытой только если:

```text
every mandatory gate availability = measured
AND every mandatory gate passed = true
AND offline qualification passed
AND formal live canary passed
AND canary rollback passed
AND isolated scoped regression passed
AND phase-0 digest unchanged
AND no unresolved security/coverage violation
```

Только после этого разрешается отдельное решение об
`AGENT_UNIFIED_DEFAULT_ON=true`. Успешное закрытие не обязано автоматически
менять default в том же commit; rollout owner может сделать это отдельным
контролируемым шагом.

## 14. Минимальные tests

### Gate evaluator

- irrelevant zero equals zero baseline passes;
- irrelevant positive value fails;
- schema composite выводится только из пяти measured canary inputs;
- missing/unavailable child блокирует composite;
- gate replacements и cost diagnostics остаются явными.

### Attribution/replay

- scenario-level missed-critical and selected-irrelevant aggregation;
- no raw content, credentials или account IDs в artifact;
- calibration и qualification cohorts не смешиваются;
- provider errors отделены от transport и semantic outcomes;
- deterministic report/attestation.

### Primary Selector

- secondary-topic, multilingual и near-topic distractors;
- stable nonce/cardinality/completion marker;
- typed retry feedback и максимум один retry;
- every-ref/every-source completeness;
- exact/structural bypass;
- complete 100, boundary 256, overflow 257;
- final failure без Answer Model.

### Recall Verifier, если реализован

- весь список conditional plan;
- pure eligibility allowed/forbidden matrix;
- add-only two-key admission;
- maximum one call, no retry, maximum one addition;
- invalid/timeout/provider failure exact baseline preservation;
- no call on exact/structural/complete/overflow;
- checkpoint resume deduplication;
- shadow pack/answer invariance;
- security/fidelity/cardinality/budget rejection.

### Integration/closure

- verified EvidencePack membership and required coverage;
- canary manifest/denominator validation;
- rollback preservation;
- isolated DB scoped regression;
- phase-0 digest twice;
- strict report reproducibility and default-off on any blocker.

## 15. Deliverables

- scenario-level raw-safe semantic attribution artifact;
- versioned calibration and untouched qualification cohorts;
- primary semantic correction или документированное доказательство перехода к
  conditional Verifier;
- optional Recall Verifier implementation, flag, telemetry and tests;
- provider replay and boundary reports;
- formal canary manifest and factual result;
- canary rollback report;
- isolated scoped regression result;
- strict quality report with every gate;
- updated rollout/closure/semantic-closure documents;
- отдельный phase-6 final-closure commit.

Если traffic, provider, authorized session или stable test infrastructure
недоступны, локальные безопасные артефакты все равно завершаются, но фаза не
объявляется закрытой и flags остаются default-off.

## 16. Фактический результат реализации 2026-07-27

Gate contract исправлен без ослабления quality floors. Irrelevant selection
теперь является `MAX 0`, поэтому `0` против zero baseline проходит, а любое
положительное значение блокирует. Schema reliability composite вычисляется
только из четырех measured child metrics при общем sample не менее 20 и равен
`1` только для first-attempt `>=0.95`, final `=1.0`, retry `<=0.05` и zero
position errors. Дочерние gates сохранены отдельными mandatory строками.

Raw-safe baseline attribution воспроизвела исходные `7/8` и `1/7`. В
`es-launch-risk` пропущен `note:fixture-es-supporting`, хотя ref присутствовал в
CandidateEnvelope и summary содержал явный signal; обе позиции получили
`search_more`. В `budget-specific-near-topic` был ошибочно выбран
`note:fixture-mixed-multi-source` с reason `topic_only`. Boundary обоих defects -
primary Selector semantics, до materialization и Answer Model. Артефакты не
содержат provider output, source/user content, credentials или account IDs.

Primary-only correction состоит из deterministic query-goal fallback,
определения direct/secondary/near-topic, evidence-bearing reason contract,
multilingual explicit-absence и interrogative answer-slot rules. Второй primary
attempt, forced source selection, select-all, ground-truth hints и post-answer
call не добавлены. Первый qualification v1 честно не прошел precision floor и
был сохранен как known calibration failure set. Независимый qualification v2
был заморожен до provider output с digest
`accb307c40bd2c01018ac565e59cfaba73c5ba2feabd5bd94a15e154c0f4ef1a`.

Qualification v2 содержит 21 semantic scenario, 20 critical refs, 22 irrelevant
refs, восемь language cohorts, note/post, parent, multi-source, required-source,
nullable-score и empty-selection cases. Первый repeat inconclusive из-за одного
внешнего provider error. Два следующих repeats дали по `21/21` first/final
valid, zero retries/position errors, critical recall `20/20`, irrelevant
selection `0/22` и final-pack precision `1.0` во всех cohorts. Compatibility
projection также дала recall/precision `1.0`, поэтому non-inferiority проходит.
Recall Verifier не реализован: primary-only path выполнил semantic floors.

Boundary-256 после изменений прошел с первой попытки: input `19410`, output
`794`, total `20204 <=22000`, latency `11565.6 ms`, zero retry/position errors.
Изолированный compose project `tg_platform_phase6_closure` на порту `55436`
применил migrations до `027` и дважды прошел scoped regression: `129 passed` +
`129 passed`; expanded runs дали `130` и `131 passed`. Recovery/FATAL/server-
process crashes в PostgreSQL logs нет.
Phase-0 digest сохранен.

Formal canary не запускался: единственная доступная local browser session была
не авторизована и показывала zero configured LLM models. Фактический denominator
остался `0 chats / 0 messages / 0 Selector decisions`; staging rollback также
unavailable. Strict report после 50 repeats: `35/42 pass`, семь live blockers,
attestation
`e647a8cdad744146da850ae9170e9eaa5beb8f43295efbd3e3d172a18583de64`.
Фаза 6 не закрыта, `AGENT_UNIFIED_DEFAULT_ON=false`.

## 17. Formal live canary 2026-07-27

После предоставления авторизованного account доступа backend и Celery workers
были пересобраны из `c65b1ea`, пять staged flags включены, а
`AGENT_UNIFIED_DEFAULT_ON=0` сохранен. Один доформальный probe был исключен:
его обработал старый worker image, что доказано несовместимым reason contract.

Live labels для 20 planned scenarios заморожены до formal provider output без
account identifier, query text или source content. Первый current-code scenario
дал canonical-valid primary Selector с первой попытки, zero retry и zero
position errors, но выбрал все восемь кандидатов. Frozen irrelevant ref был
выбран и попал в final pack; frozen critical ref был выбран Selector, но затем
исключен material budget и в final pack не попал. Три неожиданных post refs не
были размечены до output и сохранены как unlabelled, поэтому precision не
объявлена measured.

Сработали заранее заданные stop conditions
`irrelevant_selection_above_zero` и `evidence_or_checkpoint_loss`. Formal
traffic остановлен на `1 chat / 1 user message / 1 Selector decision`; остальные
19 сообщений не отправлялись, staging rollback не запускался. Strict report:
`33/42 pass`, девять blockers, attestation
`91a6aeee9c4cd6c5a3e544d2481b5577621672df38dcf2c1a8b431a74bf636f1`.
Фаза 6 остается незакрытой и default-off.

## 18. Post-stop mixed-complexity diagnostic 2026-07-27

Для локализации semantic defects после formal stop выполнена отдельная frozen
diagnostic выборка: 19 chats и 19 one-message read-only runs. Она намеренно
смешанная: 13 сложных сценариев проверяют анафоры, implied source need,
cross-object reasoning, complete classification, parent/media и near-topic
границы; последовательности `4`, `6`, `10`, `13`, `14`, `17` оставлены простыми
controls. Diagnostic traffic не является продолжением formal canary и не может
использоваться для closure pass.

Context Selector был вызван в 16 runs. Provider observability измерена для 15:
`14/15` first-attempt valid, `15/15` final valid, `1/15` retries, zero position
errors. Один retry вызван `invalid_transport`; один decision имеет assessments,
но provider row unavailable. Sample `15 <20`, first-attempt `0.9333 <0.95` и
retry `0.0667 >0.05`, поэтому composite не проходит и не объявляется measured
pass.

Scenario-level attribution фиксирует 58 frozen critical occurrences. Для
inventory control пять refs отделены от individual denominator, потому что fast
path дал `catalog:notes`, а не ref-level evidence. Из оставшихся 53 критических
occurrences 21 потерян на discovery, 19 на Selector и 6 на materialization; 7
дошли до final pack. Frozen irrelevant selection равен `0/8` на двух controls.
Из простых controls exact-fact прошёл, catalog inventory доказал только root
coverage, absence остался inconclusive, ещё три выявили реальные
discovery/Selector failures. Таким образом, простые controls сохранены, а
сложные вопросы не сведены к обычному RAG retrieval.

Raw-safe artifacts:

- `backend/tests/fixtures/agent_unified_phase6/v4/agentic_diagnostic_manifest.json`;
- `backend/tests/fixtures/agent_unified_phase6/v4/agentic_diagnostic_result.json`.

Они не содержат raw queries, source content, raw provider output, credentials
или account IDs. Action proposals и audit events равны нулю. Formal denominator
остаётся `1`, rollback unavailable, strict report `33/42`,
`AGENT_UNIFIED_DEFAULT_ON=false`. Финальный isolated focused regression после
добавления artifact-contract test дал `131 passed`; phase-0 digest и strict
attestation остались неизменны.
