# Единый план: фаза 6 — replay, shadow, canary и default-on

**Статус:** closure-артефакты и ограниченный account pilot реализованы
2026-07-26; фаза не завершена, default-on заблокирован mandatory gates

**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фазы 0–5

**План закрытия оставшихся gates:**
[workspace-agent-unified-phase-6-closure.md](workspace-agent-unified-phase-6-closure.md)

## Цель

Включить улучшения только после доказательства, что система не стала хуже по
релевантности, полноте, fidelity, latency и устойчивости.

## Порядок включения

1. Offline replay старых runs без вызова Answer Model.
2. Shadow catalog/contract/selector/pack с diff отчётом.
3. Canary на ограниченной доле factual reads.
4. Canary для semantic complete flows.
5. Default-on после quality gates.

Каждый шаг фиксирует old/new contract, candidate registry, assessments,
material plan, pack membership и metrics.

## Обязательные quality gates

- `fallback_select_all_rate = 0`;
- `required_source_forced_selection_rate = 0`;
- `fidelity_mismatch_rate = 0`;
- structural count error rate `0` на golden/held-out fixtures;
- exact/quote/edit/mutation scenarios не card-only;
- complete coverage не ниже baseline;
- relevant recall не ниже baseline;
- irrelevant selection rate ниже baseline;
- p95 latency и LLM calls в согласованном бюджете;
- checkpoint/resume, interrupted и cancelled flows проходят;
- tenant/status/security guards проходят.

## Наблюдаемость

Для каждого run durable trace должен содержать:

1. `candidate_registry` с origin, score/null, parent и source IDs;
2. selector assessments и source dispositions;
3. policy compilation errors/rejections/promotions;
4. materialization result и source revision;
5. final pack membership/omissions/truncation;
6. answer usage и claims/evidence binding;
7. planner action, expected gap и evidence delta.

## Rollback drill

До default-on выполнить искусственный rollback каждого флага:

- во время нового run;
- при resume старого checkpoint;
- после selector timeout;
- после catalog schema mismatch;
- после pack budget overflow.

Rollback не должен терять user message, ledger, known refs или старый evidence.

## Основные файлы

- `backend/app/services/agent/runtime/observability.py`;
- `backend/app/services/agent/runtime/replay.py`;
- `backend/app/services/agent/runtime/executor.py`;
- `backend/app/services/agent/runtime/graders.py`;
- `backend/scripts/` для replay/shadow reports;
- golden/held-out fixtures и integration tests.

## Завершение

Фаза завершена, когда quality report подписан, rollback drill пройден, held-out
набор не ухудшен, а compatibility path имеет срок удаления и владельца. До этого
новые поля и metrics сохраняются для диагностики, даже если default path включен.

## Результат

- исходная точка closure проверена: `HEAD` и commit реализации фазы 6 равны
  `e6bb80c8c984534710e08d2c30514dbd5f7519e7`; до начала closure в рабочем
  дереве были только намеренные изменения этого документа и нового closure-плана;
- offline replay всех 10 golden и 3 held-out phase-0 scenarios выполнен 50 раз
  без Answer Model; digest стабилен:
  `4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`;
- background indexing одним LLM call формирует versioned
  `discovery_summary <= 480` и `selector_summary <= 160`; реализованы
  deterministic extractive fallback, migration `026_selector_summary_projection`,
  freshness checks и backfill с processing ceiling `120 jobs/min`;
- Context Selector использует versioned compact transport с локальными integer
  indexes, sparse candidate/source rows и neutralized untrusted title/summary;
  decoder восстанавливает canonical `workspace.context-selector/v2` и отклоняет
  unknown, duplicate, missing и out-of-range indexes;
- complete source со stale/missing selector summary получает blocking
  `stale_selector_summary`; synchronous rollout ограничен 100 candidates, а
  101-256 не получает `ready` без explicit exhaustive flow или measured boundary
  canary;
- добавлен `workspace.unified-rollout-trace/v1`: для run с запрошенным unified
  rollout durable event сохраняет
  contract, безопасную metadata-проекцию registry, v2 assessments/dispositions,
  plan decisions/no-op, additive-search trace, material plan, pack
  membership/omissions/coverage, claims/evidence binding и run metrics без
  source text и текста ответа;
- добавлен read-only shadow diff для contract, registry, selector, planner,
  additive search и pack; shadow trace не имеет поверхности генерации ответа,
  `shadow_answer_model_calls=0`, пользовательский ответ не меняется;
- strict gate evaluator принимает только `availability=measured` как возможный
  pass; `unavailable`, `missing`, `inconclusive`, `not_measured` и `derived`
  никогда не превращаются в успешный gate;
- feature-flag sequencing и deterministic canary allocation блокируют cohort,
  пока все mandatory gates не прошли; planner policy допускается только с
  полным порядком флагов, `workspace.context-selector/v2` и verified pack
  boundary;
- registry limit остается `256`. Для authoritative corpus из 257 refs registry
  содержит 256 refs, coverage target сохраняет 257, а один unassessed ref создает
  blocking `incomplete_assessment`; `ready` недоступен. Лимит не увеличен и
  второй Selector/planner loop не добавлен;
- локальный rollback drill прошел 7 из 7 сценариев, включая interruption summary
  backfill и compact decode failure. Staging/canary drill не выполнялся;
- provider observability сохраняет actual input/cached/output/total tokens,
  provider/model, cohort, candidate count, latency, timeout, retry, schema result
  и estimator delta. Price snapshot и estimated cost имеют
  `availability=unavailable`, потому что достоверный тариф не задан;
- migration `027_agent_run_answer_llm` закрепляет выбранную в composer Answer
  Model за run; runtime отдельно разрешает текущую content revision и больше не
  принимает phase-1 structural catalog revision за freshness revision RAG-card;
- frozen synthetic labeled cohort содержит 8 tenant-safe cases на `de`, `en`,
  `es`, `ru` и mixed language. Model replay, recall и non-inferiority варианта
  160 не измерялись и имеют `inconclusive`;
- compatibility path сохраняется. Владелец: `workspace-agent`; пересмотр срока
  удаления: `2026-10-24`, только после успешного production canary;
- в account-scoped pilot явно включены пять staged flags, а
  `AGENT_UNIFIED_DEFAULT_ON=false`; defaults в конфигурации не изменены.

Ограниченный pilot содержит ровно 20 новых чатов и 46 user messages, от 2 до 4
на чат. Создано 46 runs: 42 completed и 4 failed из-за внешних Answer Model/DNS
ошибок. Обезличенный fixture хранит только агрегаты, без account/run/thread IDs,
credentials и raw user content.

Selector был вызван в 16 runs: 31 provider call, 15 bounded retries, 0 timeouts.
Actual usage и latency измерены для всех 31 calls. Canonical valid result получен
в 2 из 16 runs; только 1 из 16 прошел с первой попытки. В post-fix окне из двух
complete-sync runs по 13 refs один retry завершился valid canonical решением с
13/13 assessments и 2/2 source dispositions, второй run не прошел обе попытки
(`invalid_canonical`, затем `invalid_transport`). Поэтому schema reliability не
считается pass.

Deployed account snapshot имеет 13/13 summary rows v2: 7 notes, 6 posts, одна
extractive fallback row; pending/failed backfill jobs равны 0/0. Это закрывает
coverage gate только для наблюдаемого account snapshot, не для production fleet.

Quality report строится командой:

```bash
cd backend
.venv/bin/python scripts/agent_unified_phase6_report.py --repeat 50 --check
```

Blocked attestation quality-части локального closure-прогона
`unified-phase6-2026-07-26`:
`sha256:387549cb5845d88a5f8dbf9c9cf2597a6ddf883100554a46840f449348661ebe`.
Strict report содержит 34 mandatory gates: 26 pass и 8 blocked.

## Результаты gates

| Gate | Availability | Факт | Порог/baseline | Результат |
|---|---|---:|---:|---|
| `fallback_select_all_rate` | measured | 0 | 0 | pass |
| `required_source_forced_selection_rate` | measured | 0 | 0 | pass |
| `fidelity_mismatch_rate` | measured | 0 | 0 | pass |
| `structural_count_error_rate` | measured | 0 | 0 | pass |
| exact/quote/edit/mutation card-only rate | measured | 0 | 0 | pass |
| complete coverage | measured | 1.0 | baseline 1.0 | pass |
| relevant recall | unavailable | null | baseline unavailable | **blocked** |
| irrelevant selection rate | unavailable | null | baseline unavailable | **blocked** |
| end-to-end p95 latency | measured | 18466.8 ms | 119061.25 ms | pass |
| LLM calls per run | measured | p95 4 | 1 | **failed** |
| Selector provider p95 latency | measured | 3226.45 ms | 30000 ms | pass |
| Selector p95 input tokens (`chars_div_4`) | measured | 17646 | 30000 | pass |
| full system + user request measured | measured | 1.0 | 1.0 | pass |
| actual provider token usage measured | measured | 31/31 calls | 1.0 | pass |
| relevant <=16 provider p95 total tokens | measured | 1214.85 | 2500 | pass |
| complete <=100 provider p95 total tokens | measured | 2559 | 10000 | pass |
| complete boundary 256 provider p95 total tokens | unavailable | null | 22000 | **blocked** |
| Selector schema/retry telemetry measured | measured | 31/31 calls | 1.0 | pass |
| Selector schema reliability within budget | inconclusive | 2/16 canonical, 1/16 first attempt | budget not agreed | **blocked** |
| monetary ceiling configured | unavailable | null | 1.0 | **blocked** |
| Selector cost p95 within ceiling | unavailable | null | 1.0 | **blocked** |
| selector summary deployed backfill coverage | measured | 13/13 | 1.0 | pass |
| compact decoder completeness | measured | 1.0 | 1.0 | pass |
| synchronous rollout ceiling guard | measured | 1.0 | 1.0 | pass |
| checkpoint/resume pass rate | measured | 1.0 | 1.0 | pass |
| interrupted/cancelled pass rate | measured | 1.0 | 1.0 | pass |
| tenant/status/security guard pass rate | measured | 1.0 | 1.0 | pass |
| shadow Answer Model calls | measured | 0 | 0 | pass |
| shadow user-answer change rate | measured | 0 | 0 | pass |
| planner decision/no-op trace coverage | measured | 1.0 | 1.0 | pass |
| additive-search trace coverage | measured | 1.0 | 1.0 | pass |
| registry-overflow ready rate | measured | 0 | 0 | pass |
| rollback drill pass rate | measured | 1.0 | 1.0 | pass |
| staging/canary rollback drill pass rate | unavailable | null | 1.0 | **blocked** |

Полный benchmark измеряет system + user request, maximum valid output и их
сумму. Результаты `chars_div_4` estimator, не provider usage:

| Candidates | Input | Maximum valid output | Total | Estimator budget |
|---:|---:|---:|---:|---|
| 16 | 2337 | 106 | 2443 | pass (`<=2500`) |
| 64 | 5385 | 406 | 5791 | offline fixture |
| 100 | 7677 | 631 | 8308 | pass (`<=10000`) |
| 128 | 9467 | 813 | 10280 | offline fixture |
| 256 | 17646 | 1645 | 19291 | pass (`<=22000`) |

Overflow fixture с 257 refs сохраняет `assessment_coverage=incomplete` и
`ready=false`. Варианты summary `80/120/240` измерены только как offline size
challengers; основной `160` не разрешен к rollout без non-inferior recall.

## Проверки

```bash
cd backend
.venv/bin/pytest -q tests/test_agent_unified_phase6_rollout.py \
  tests/test_agent_unified_phase6_closure.py \
  tests/test_agent_unified_phase5_planner_search.py \
  tests/test_agent_unified_phase4_materialization.py \
  tests/test_agent_unified_phase3_selector.py \
  tests/test_agent_unified_phase2_contract.py \
  tests/test_agent_unified_phase1_catalog.py \
  tests/test_agent_unified_phase0.py tests/test_agent_phase5_planner.py \
  tests/test_agent_adaptive_evidence_depth.py tests/test_agent_phase6.py \
  tests/test_agent_phase2_contract.py tests/test_turn_contract.py \
  tests/test_message_context_manifest.py tests/test_agent_runtime.py \
  tests/test_workspace_graph.py tests/test_rag_tools.py tests/test_agent_research.py \
  tests/test_rag.py tests/test_rag_query.py tests/test_rag_retrieval_policy.py \
  tests/test_agent_phase4_retrieval.py tests/test_agent_listing.py \
  tests/test_agent_e2e.py tests/test_config.py tests/test_agent_security.py \
  tests/test_agent_graders.py tests/test_agent_trace.py \
  tests/test_agent_budget.py tests/test_rag_worker.py tests/test_semantic_summary.py
.venv/bin/python scripts/agent_unified_phase0_report.py --repeat 2 --check
.venv/bin/python scripts/agent_unified_phase6_report.py --repeat 50 --check
```

Результат scoped regression-набора фаз 0-6 и затронутого indexing/runtime:
`231 passed, 1 warning`; полный несвязанный suite не повторялся. Warning про
смену pooling в `fastembed` существовал до фазы. Frontend typecheck и lint
измененных файлов прошли. Phase-0 replay сохранил прежний digest.

## Exit criteria

- [x] offline replay воспроизводим и не вызывает Answer Model;
- [x] shadow comparison, durable observability и strict unavailable semantics
  реализованы и покрыты тестами;
- [x] rollback drill пройден, compatibility path имеет владельца и дату
  пересмотра;
- [x] golden/held-out frozen results и связанные regression tests не изменены;
- [x] dual summary, compact transport, local full-request benchmark, telemetry
  schema и дополнительные rollback fixtures реализованы;
- [ ] production-like relevant recall и irrelevant selection rate измерены;
- [ ] latency и provider token usage измерены и проходят, но p95 LLM calls per
  run `4 > 1`, schema reliability и boundary-256 не проходят closure;
- [ ] factual-read canary пройден;
- [ ] semantic-complete canary пройден;
- [ ] все mandatory gates пройдены и default-on разрешен.

## Остаточные риски

- account pilot измерил actual provider usage и latency только на 1-13 refs;
  provider boundary canary на 256 refs отсутствует;
- production shadow и размеченный ground truth отсутствуют, поэтому recall и
  irrelevant-selection improvement нельзя считать прошедшими;
- synthetic shadow доказывает side-effect boundary и schema diff, но не заменяет
  production-like traffic comparison;
- manual account pilot не заменяет formal canary: preconditions не были полностью
  пройдены, schema success составил 2/16 runs, а p95 LLM calls равен 4;
- price snapshot, monetary ceiling и staging/canary infrastructure недоступны;
- `160` остается кандидатом, а не доказанным вариантом: quality comparison с
  `120/240` и compatibility path не запускался;
- default-on и удаление compatibility path запрещены, пока любой gate имеет
  статус, отличный от измеренного pass.

## Selector reliability remediation: фактический результат 2026-07-27

Эта секция дополняет исторический closure-result выше и является текущим
состоянием phase-6 remediation. Реализован positional transport
`workspace.context-selector-transport/v2`: модель возвращает только assessment
vector, а ref, role, resolution и source dispositions восстанавливаются
детерминированно. Registry nonce, exact cardinality и completion marker являются
обязательными. Decoder возвращает typed error codes; retry ограничен одной
попыткой и получает конкретные codes. V1 decoder сохранён для rollback/checkpoint
compatibility. Второй Selector, planner loop, Recall Verifier и post-answer
auditor не добавлены.

Capability negotiation использует metadata адаптера и выбирает ровно один tier
в порядке `strict_json_schema -> tool_calling -> json_mode -> plain`. Между tiers
нет runtime fallback. Exact/structural bypass, полный CandidateEnvelope,
verified EvidencePack boundary, synchronous ceiling 100 и blocking overflow 257
сохранены. После final Selector failure Answer Model не вызывается; deterministic
failure response не утверждает, что workspace data отсутствует.

Frozen provider replay выполнен на 8 semantic scenarios и вариантах
compatibility/120/160/240. Для основного 160 transport дал 8/8 final valid,
8/8 first-attempt valid, 0 retries и 0 position errors. Required recall равен
`8/9 = 0.888889`, как compatibility baseline, поэтому non-inferiority проходит.
Critical required-evidence recall равен `7/8 = 0.875`, а irrelevant selection
rate `1/7 = 0.142857` при compatibility baseline `0/7`; оба quality floor не
пройдены. Это подтверждённый semantic false negative после устранения transport
invalidity. Он остаётся blocker и входным условием отдельного conditional Recall
Verifier plan, но verifier в этой работе не реализован.

Всего replay сделал 33 provider calls: 32 valid schema results и один внешний
provider failure в варианте 120; invalid transport/canonical и positional errors
не наблюдались. Boundary measurement на 256 realistic multilingual candidates с
3000 characters dialog context прошёл с первой попытки: input `19188`, cached
input `18944`, output `794`, total `19982`, latency `9531.7 ms`, retry `0`,
estimator input `17453`, estimator delta `+1735`. Provider gate
`19982 <= 22000` проходит. Price snapshot и estimated cost остаются
`availability=unavailable`.

Formal live canary не запускался, поскольку этап F разрешён только после полного
offline pass. Его фактический sample size: `0 chats`, `0 user messages`,
`0 Selector decisions`. Поэтому canary schema/coverage gates и staging rollback
остаются unavailable, а не превращаются в pass. `AGENT_UNIFIED_DEFAULT_ON=false`.

### Актуальные mandatory gates

Strict report содержит 42 gates: 33 pass и 9 blocked.

| Gate | Availability | Факт | Порог/baseline | Результат |
|---|---|---:|---:|---|
| fallback select-all rate | measured | 0 | 0 | pass |
| required-source forced-selection rate | measured | 0 | 0 | pass |
| fidelity mismatch rate | measured | 0 | 0 | pass |
| structural count error rate | measured | 0 | 0 | pass |
| card-only exact/quote/edit/mutation rate | measured | 0 | 0 | pass |
| complete coverage | measured | 1.0 | baseline 1.0 | pass |
| relevant recall | measured | 0.888889 | baseline 0.888889 | pass |
| irrelevant selection rate | measured | 0.142857 | baseline 0 | **blocked** |
| end-to-end p95 latency | measured | 18466.8 ms | 119061.25 ms | pass |
| initial semantic Selector calls/run | measured | 1.0 | <=1 | pass |
| Selector p95 latency | measured | 3226.45 ms | 30000 ms | pass |
| full-request input estimator | measured | 17453 | 30000 | pass |
| full Selector request measured | measured | 1.0 | 1.0 | pass |
| provider token usage measured | measured | 1.0 | 1.0 | pass |
| relevant <=16 p95 total tokens | measured | 1214.85 | 2500 | pass |
| complete <=100 p95 total tokens | measured | 2559 | 10000 | pass |
| complete boundary 256 total tokens | measured | 19982 | 22000 | pass |
| schema/retry telemetry measured | measured | 1.0 | 1.0 | pass |
| schema reliability within canary budget | inconclusive | null | agreed canary budget | **blocked** |
| canary first-attempt valid rate | unavailable | null | >=0.95 | **blocked** |
| canary final valid rate | unavailable | null | 1.0 | **blocked** |
| canary retry rate | unavailable | null | <=0.05 | **blocked** |
| canary position error count | unavailable | null | 0 | **blocked** |
| Answer Model calls after final failure | measured | 0 | 0 | pass |
| complete/classification object coverage | unavailable | null | 1.0 | **blocked** |
| critical required-evidence recall | measured | 0.875 | 1.0 | **blocked** |
| summary 160 non-inferior recall | measured | 1.0 | 1.0 | pass |
| capped pilot chat count | measured | 20 | <=20 | pass |
| capped pilot max messages/chat | measured | 4 | <=4 | pass |
| selector-summary backfill coverage | measured | 1.0 | 1.0 | pass |
| compact decoder completeness | measured | 1.0 | 1.0 | pass |
| synchronous rollout ceiling guard | measured | 1.0 | 1.0 | pass |
| checkpoint/resume pass rate | measured | 1.0 | 1.0 | pass |
| interrupted/cancelled pass rate | measured | 1.0 | 1.0 | pass |
| tenant/status/security guard pass rate | measured | 1.0 | 1.0 | pass |
| shadow Answer Model calls | measured | 0 | 0 | pass |
| shadow answer change rate | measured | 0 | 0 | pass |
| planner trace coverage | measured | 1.0 | 1.0 | pass |
| additive-search trace coverage | measured | 1.0 | 1.0 | pass |
| overflow-257 ready rate | measured | 0 | 0 | pass |
| local rollback drill pass rate | measured | 1.0 | 1.0 | pass |
| staging/canary rollback drill | unavailable | null | 1.0 | **blocked** |

Исходный `llm_calls_per_run` остаётся diagnostic (`p95=4`), но заменён
mandatory gate `semantic_selector_initial_calls_per_selector_run <=1`. Monetary
gates заменены owner-approved risk controls `chat_count <=20` и
`max_user_messages_per_chat <=4`; price/cost не объявлены известными или
успешными.

Phase-0 report выполнен дважды и сохранил digest
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`.
Strict report выполнен с 50 repeats; blocked attestation:
`sha256:6a2aac8f05934e7bd71904c3ab325cfa030627668e3f7fdf19f6257230deca25`.
Focused closure/rollout regression: `31 passed`; дополнительные targeted
capability/decoder/report checks: `8 passed`; compile-check пройден. Более широкий scoped
прогон остановлен после `229 passed`: два failures и девять teardown errors были
вызваны подтверждённым `PostgreSQL in recovery mode`, а не assertion regression.

### Актуальные exit criteria и риски

- transport invalidity устранена на frozen replay и boundary-256 measurement;
- summary 160 non-inferior по required recall, но critical recall и irrelevant
  selection quality floors не пройдены;
- formal live canary и staging rollback не выполнялись из-за offline blocker;
- canary reliability/coverage sample отсутствует, поэтому соответствующие gates
  unavailable;
- conditional Recall Verifier остаётся отдельным follow-up только после нового
  решения; эта remediation не добавляет скрытый semantic call;
- phase 6 не завершена, compatibility path сохраняется, flags остаются
  default-off.

## Semantic closure remediation: фактический результат 2026-07-27

После transport remediation исправлены два gate contracts: irrelevant selection
использует `MAX 0`, а schema reliability composite выводится из measured canary
children при sample `>=20`. Scenario-level baseline attribution локализовала
critical miss `note:fixture-es-supporting` и false positive
`note:fixture-mixed-multi-source` в primary Selector, сохранив только fixture IDs,
позиции, reason codes и attempt metadata.

Один primary Selector получил query-goal fallback и непротиворечивые semantic
reason definitions. Qualification v1 не был переписан после неудачи: первые
прогоны показали `7/22` и `8/22` irrelevant selections. После calibration на
этом known failure set создан и до provider output заморожен независимый v2
cohort. Два valid v2 repeats дали `21/21` first/final valid, critical `20/20`,
irrelevant `0/22`, precision `1.0`, zero retries и position errors. Один более
ранний repeat остался inconclusive из-за отдельного provider error. Recall
Verifier не реализован, потому что primary-only path прошел semantic floors.

Новый boundary-256: `19410` input, `794` output, `20204` total provider tokens,
`11565.6 ms`, first-attempt valid. Изолированный regression дважды дал
`129 passed`; финальный expanded scope дал `130 passed`. PostgreSQL
recovery/crash events равны нулю. Phase-0 digest остался
`4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`.

Formal canary preflight через доступную local browser session заблокирован
отсутствием авторизации и configured LLM: `0 chats`, `0 messages`, `0 Selector
decisions`. Никакие credentials не читались и сообщения не отправлялись.
Canary reliability, complete/classification coverage и staging rollback остаются
unavailable. Strict report после 50 repeats содержит `35/42 pass`, семь blockers,
attestation
`e647a8cdad744146da850ae9170e9eaa5beb8f43295efbd3e3d172a18583de64`.
Default-on запрещен.
