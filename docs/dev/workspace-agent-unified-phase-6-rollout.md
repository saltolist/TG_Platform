# Единый план: фаза 6 — replay, shadow, canary и default-on

**Статус:** безопасные артефакты реализованы 2026-07-24; canary и default-on заблокированы quality gates

**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фазы 0–5

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

- исходная точка проверена: `HEAD=dcc3aeae0781ff6e773ff0bc9f52d7d94d5d4d36`,
  рабочее дерево до начала фазы было чистым;
- offline replay всех 10 golden и 3 held-out phase-0 scenarios выполнен 50 раз
  без Answer Model; digest стабилен:
  `4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`;
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
- rollback drill прошел 5 из 5 сценариев: новый run, resume старого checkpoint,
  selector timeout, catalog schema mismatch и pack budget overflow. Сохраняются
  user message, ledger, known refs, evidence records/IDs и старый contract;
- compatibility path сохраняется. Владелец: `workspace-agent`; пересмотр срока
  удаления: `2026-10-24`, только после успешного production canary;
- все unified flags, включая `AGENT_UNIFIED_DEFAULT_ON`, остаются default-off.

Quality report строится командой:

```bash
cd backend
.venv/bin/python scripts/agent_unified_phase6_report.py --repeat 50 --check
```

Attestation quality-части финального прогона:
`sha256:0f73ed9c60a33d5a9f79969c476ff536c2f5b3e36952869a4fd66d890e978204`.

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
| end-to-end p95 latency | unavailable | null | 119061.25 ms | **blocked** |
| LLM calls per run | unavailable | null | 1 | **blocked** |
| Selector provider p95 latency | unavailable | null | 30000 ms | **blocked** |
| Selector p95 prompt tokens | measured | 49736 | 30000 | **failed** |
| checkpoint/resume pass rate | measured | 1.0 | 1.0 | pass |
| interrupted/cancelled pass rate | measured | 1.0 | 1.0 | pass |
| tenant/status/security guard pass rate | measured | 1.0 | 1.0 | pass |
| shadow Answer Model calls | measured | 0 | 0 | pass |
| shadow user-answer change rate | measured | 0 | 0 | pass |
| planner decision/no-op trace coverage | measured | 1.0 | 1.0 | pass |
| additive-search trace coverage | measured | 1.0 | 1.0 | pass |
| registry-overflow ready rate | measured | 0 | 0 | pass |
| rollback drill pass rate | measured | 1.0 | 1.0 | pass |

Для Selector на полном bounded registry из 256 синтетических cards один
зафиксированный локальный прогон сериализации на 50 повторах дал p50 `0.976 ms`,
p95 `1.320 ms`, размер input
`198944` символа и `49736` tokens по действующему `chars_div_4` estimator;
output cap остается `12000`. Эти локальные числа не считаются provider latency.
Provider latency/token usage отсутствуют и не подменены локальным benchmark.

## Проверки

```bash
cd backend
.venv/bin/pytest -q tests/test_agent_unified_phase6_rollout.py \
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
  tests/test_agent_graders.py tests/test_agent_trace.py
.venv/bin/python scripts/agent_unified_phase0_report.py --repeat 2 --check
.venv/bin/python scripts/agent_unified_phase6_report.py --repeat 50 --check
```

Результат regression-набора: `424 passed, 1 warning`. Warning про смену pooling
в `fastembed` существовал до фазы. Phase-0 replay сохранил прежний digest.

## Exit criteria

- [x] offline replay воспроизводим и не вызывает Answer Model;
- [x] shadow comparison, durable observability и strict unavailable semantics
  реализованы и покрыты тестами;
- [x] rollback drill пройден, compatibility path имеет владельца и дату
  пересмотра;
- [x] golden/held-out frozen results и связанные regression tests не изменены;
- [ ] production-like relevant recall и irrelevant selection rate измерены;
- [ ] p95 latency, LLM calls и provider Selector latency/token usage измерены и
  находятся в budget;
- [ ] factual-read canary пройден;
- [ ] semantic-complete canary пройден;
- [ ] все mandatory gates пройдены и default-on разрешен.

## Остаточные риски

- Selector input для 256 refs уже превышает token budget по текущему estimator;
  повышать registry limit до устранения и provider-измерений запрещено;
- production shadow/canary telemetry и размеченный ground truth отсутствуют,
  поэтому recall, irrelevant-selection improvement, end-to-end latency и LLM
  calls нельзя считать прошедшими;
- synthetic shadow доказывает side-effect boundary и schema diff, но не заменяет
  production-like traffic comparison;
- canary cohort allocation реализован, но намеренно возвращает
  `quality_gates_blocked`; factual и semantic canary не запускались;
- default-on и удаление compatibility path запрещены, пока любой gate имеет
  статус, отличный от измеренного pass.
