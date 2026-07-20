# Единый план: фаза 6 — replay, shadow, canary и default-on

**Статус:** план  
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
