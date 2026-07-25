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
