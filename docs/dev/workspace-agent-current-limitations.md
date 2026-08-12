# Workspace Agent: текущие ограничения и оставшиеся работы

**Дата:** 2026-07-19  
**Текущий baseline:** `0b69a06`  
**План:** [workspace-agent-intelligence-performance-plan.md](workspace-agent-intelligence-performance-plan.md)  
**Статус:** фазы 1–3 реализованы; phase-3 production canary и phase-4 retrieval quality остаются следующими release gates

Этот файл является handoff и рабочим списком ограничений. Он не отменяет
exit criteria завершённых фаз и не является разрешением ослаблять runtime или
quality gates.

## Что уже закрыто

- Фаза 1: child-owned asyncio loop, fork-safe pools, child-local embedding
  warmup, retry policy для cross-loop ошибок, queue isolation и runtime health.
- Prometheus prefork aggregation: `MultiProcessCollector`, отдельный
  multiprocess directory на worker-контейнер, `mark_process_dead` при штатном
  shutdown и scrape targets для interactive/heavy workers.
- `fastembed==0.8.0`; embedding fingerprint содержит runtime version и
  pooling strategy.
- Фаза 2: typed `TargetContract`/`TurnContract`, deterministic resolution,
  multi-target/multi-source bootstrap, budgets и evidence-boundary checks.
- Фаза 3: run-scoped `SearchIntentLedger`, canonical signatures, one
  gap-linked rewrite, read/empty-result cache, L1/hybrid reuse и validator event.
- Phase-2 compatibility flag `AGENT_TURN_CONTRACT_V2_ENABLED` остаётся для
  canary/rollback.
- Локальный ignored `docker-compose.override.yml` настроен так, чтобы
  наследовать phase-1 entrypoint и bind-mount heavy worker. Изменение локальное
  и в Git не фиксируется.

## Release blockers

Это не причины отменять разработку фазы 3, но их нужно закрыть перед широким
production rollout.

| Ограничение | Почему важно | Критерий закрытия |
|---|---|---|
| Нет полного Docker/broker soak на 1000 LLM runs | Локальный stress проверяет DB/runtime operations, но не весь Celery/provider path | Soak без cross-loop/retry regression, с latency/error report |
| Held-out phase-2 check не является автономным CI gate | Проверка target resolution `4/4` опирается на защищённую локальную БД | Повторяемый anonymized label artifact и canary сравнение target/evidence/latency |
| Static Prometheus targets | При scaling одного service Prometheus может не скрапить каждый replica | Docker/Kubernetes service discovery и проверка всех replicas |
| Stale live gauges после `SIGKILL` | `mark_process_dead` не вызывается при жёстком убийстве процесса | Restart cleanup policy плюс alert на scrape health/worker readiness |

## Фаза 3: SearchIntentLedger (реализовано)

Реализация описана в [phase-3 handoff](workspace-agent-phase3-search-ledger.md).
Существующие `TargetContract`, `SourceRequirement`, `resolution_events`,
`revision` и budgets не менялись.

1. `SearchIntentLedger` хранится в run state/checkpoint.
2. Каждый intent связан с `source_requirement_id`, scope и freshness revision.
3. Canonical tool signatures и semantic `intent_key` детерминированы.
4. Состояния `planned`, `running`, `satisfied`, `exhausted` сериализуются.
5. Для intent разрешён максимум один gap-linked rewrite.
6. Успешные reads и empty search outcomes кэшируются внутри run.
7. Повторный LLM `FinishRetrieval` заменяется validator event.
8. `hybrid_prefetch` и `retrieve_for_chat` используют общий discovery policy.

### Exit criteria фазы 3

- duplicate successful external calls равен `0`;
- один intent исполняется не более двух раз с rewrite;
- repeated `FinishRetrieval` отсутствует во всех golden traces;
- planner получает явный `exhausted_reason`;
- quality floor фазы 0 и target/evidence accuracy фазы 2 не ухудшаются;
- problematic chat имеет измеримый выигрыш по tool/planner rounds и latency.

## Runtime и observability hardening

Эти задачи не нужно смешивать с SearchIntentLedger, но они нужны для
масштабирования и эксплуатации.

- Перевести Prometheus worker targets на service discovery до запуска нескольких
  replicas.
- Добавить проверку cleanup multiprocess files после нормального restart и
  документировать поведение при `SIGKILL`.
- Проверить autoscaling policy: новый interactive child не должен получать task
  до завершения warmup; cold start может занимать до 90 секунд.
- Добавить production p50/p95/p99 после rollout. Текущие значения warmup и
  scrape latency являются локальными измерениями, не SLO.

## Отложенные maintenance-задачи

- Удалять старые embeddings после подтверждённого reindex и retention policy.
- Решить, нужно ли подавлять или устранять informational pooling warning
  fastembed. Версия уже зафиксирована на `0.8.0`; переход на `0.5.1` вернёт
  другое CLS-поведение и требует отдельного quality/reindex решения.
- Разобрать unrelated failures полного backend suite отдельно от agent release
  gate: config/.env, stale RAG mocks, Telegram/network fixtures и прочие
  области, не входящие в фазы 1–3.

## Проверки перед rollout

Минимальный agent gate:

```bash
cd backend
PYTHONPATH=. .test-venv/bin/pytest -q \
  tests/test_agent_phase1_runtime.py \
  tests/test_agent_phase2_contract.py \
  tests/test_agent_phase0_baseline.py \
  tests/test_agent_budget.py \
  tests/test_agent_runtime.py \
  tests/test_agent_trace.py
```

Ожидаемый baseline для зафиксированных xfail: phase-0 quality regressions
остаются видимыми и не превращаются в XPASS без обновления fixture/quality
floor. Полный backend green не является acceptance criterion этого handoff,
пока unrelated failures не классифицированы.

## Handoff

Следующий исполнитель начинает с SearchIntentLedger и его golden tests. Не
добавлять новый resolver layer, не ослаблять required-source/evidence boundary,
не заменять deterministic dedupe новым LLM critic и не считать UI progress
доказательством ускорения. После фазы 3 провести soak/canary и затем закрыть
runtime/observability hardening перед production rollout.
