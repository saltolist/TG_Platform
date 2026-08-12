# Workspace Agent phase 1: async runtime и cold start

**Дата:** 2026-07-19  
**План:** [workspace-agent-intelligence-performance-plan.md](workspace-agent-intelligence-performance-plan.md)  
**База:** phase 0, commit `4492a2da18bc565148667af82a1823fd8c791d53`  
**Фаза:** 1, без реализации typed contracts фазы 2

## Реализованный runtime

- каждый Celery prefork child владеет одним долгоживущим asyncio loop;
- `publish`, analytics, media и agent tasks используют общую `run_async` точку;
- после fork child сбрасывает унаследованные SQLAlchemy pool, checkpointer и
  fastembed objects; shutdown закрывает child-local pools и loop;
- pooling checkpointer разрешён только явно зарегистрированным долгоживущим
  API/Celery loops. Временные loops используют `AsyncNullConnectionPool` и не
  оставляют PostgreSQL connections;
- `Future attached to a different loop` классифицируется как programming
  error и не отправляется в transient retry;
- interactive worker после fork конструирует local embedding model и выполняет
  реальный query embed. `worker_proc_alive_timeout=90s` покрывает холодный host;
- task не принимается при `warmup_failed`; состояние доступно через
  `app.tasks.agent_runs.runtime_health`, structured log и Prometheus gauges;
- `agent-interactive`, `agent-heavy`, `telegram-io` и `analytics` маршрутизируются
  раздельно. Compose запускает heavy worker отдельно от interactive worker.
- rollout/rollback управляется `AGENT_RUNTIME_PHASE1_ENABLED` (default `1`);
  `0` отключает phase-1 lifecycle hooks и отдельные task routes.
- `fastembed` зафиксирован на `0.8.0`; local `model_key` содержит runtime version
  и pooling strategy. Startup backfill создаёт reindex jobs, если существует
  только embedding с прежним fingerprint.

## Проверки и измерения

Фазовый gate:

```bash
cd backend
PYTHONPATH=. .test-venv/bin/pytest -q \
  tests/test_agent_phase1_runtime.py \
  tests/test_comment_sync_pending.py \
  tests/test_telegram_sync_pending.py \
  tests/test_rag_worker.py::test_startup_backfill_is_model_fingerprint_aware
```

Первоначальный результат общего gate: `18 passed`; после добавления
multiprocess regression тот же gate даёт `19 passed`. С проверкой phase-2
contracts и agent budget/runtime/trace актуальный объединённый gate дал
`71 passed`, из них phase-1 runtime module — `12 passed`, а model-fingerprint
backfill — два параметризованных сценария.
Stress-case выполняет 500 последовательных и 500
параллельных real `SELECT 1` через один child-owned loop и bounded asyncpg pool.
Все 1000 операций завершились без cross-loop ошибки; был использован один loop.
Два helper-набора дополнительно проверяют loop-local Redis clients и их reset.

Regression-набор `test_agent_budget.py + test_agent_runtime.py +
test_agent_trace.py`: `39 passed`. До замены ownership policy этот же процесс
создал `pool-16`, исчерпал PostgreSQL clients и завершился как `1 failed,
35 passed, 5 errors`; после исправления накопления connections нет.

Frozen quality gate phase 0 не менялся: graders/health дают `22 passed,
3 xfailed`; xfail соответствуют заранее зафиксированным planner regressions и
не относятся к runtime. Ни retrieval, ни prompts, ни answer schema не менялись.
Расширенная freeze-команда с budget tests: `28 passed, 3 xfailed`.
Расширенный сфокусированный набор `test_agent_* + workspace_graph + runtime
helpers + health`: `168 passed, 3 xfailed`.
После добавления versioned embedding fingerprint расширенный agent/RAG набор:
`216 passed, 3 xfailed`.

Docker verification после включения multiprocess exporter:

| Target | `agent_worker_ready` | Prometheus target |
|---|---:|---|
| `celery-worker:9108` | 2 | `up` |
| `celery-heavy-worker:9108` | 1 | `up` |

Regression запускает отдельный процесс с `PROMETHEUS_MULTIPROC_DIR`, форкает
child, проверяет агрегацию counter/gauge и подтверждает, что
`mark_process_dead` удаляет live gauge, но сохраняет накопленный counter.
Локальный microbenchmark 100 000 пар `Counter.inc` + `Histogram.observe` дал
83.9 ms in-memory и 139.8 ms в multiprocess mode: добавка около 0.28 мкс на
одну metric operation. Scrape занимал 12-21 ms вне task/request path.

Локальный benchmark на одном и том же disk cache и модели:

| Измерение | До прогрева | После прогрева |
|---|---:|---:|
| query embed | 1035.2 ms | 7.2 ms |
| standalone process: model load + real embed | 1.86 s | выполняется до ready |
| полный child init hook | 1326.4 ms | до приёма task |

Это local measurement, не production SLO. Исторический production trace phase
0 относил 25-30 s к первой инициализации embeddings. Теперь эта работа находится
до `ready` interactive child, поэтому не входит в первый принятый task. Новый
production p50/p95/p99 можно сравнить только после rollout и накопления traces.

## Exit criteria

| Критерий | Результат |
|---|---|
| 1000 последовательных/параллельных runs без `different loop` | Выполнено фазовым stress-test: 1000 DB-backed runtime operations, один loop, bounded pool |
| retry rate по этой причине равен нулю | Выполнено детерминированно: cross-loop exception bypasses `self.retry`; regression test проверяет zero retry calls |
| warm run не инициализирует embeddings | Выполнено: единственный warmup hook находится в child init; task path его не вызывает; warm embed 7.2 ms против first 1035.2 ms |
| cold penalty не попадает в первый accepted interactive task | Выполнено архитектурно: child init блокирует до real embed; failed warmup оставляет `ready=false` и task отклоняется без retry |

## Оставшиеся риски и handoff

- Проверен реальный asyncpg stress и Celery prefork lifecycle contract, но полный
  Docker worker/broker soak на 1000 полных LLM runs не запускался: он требует
  provider quota и production-like deployment.
- Prometheus prefork aggregation реализована через `MultiProcessCollector`:
  каждый Celery worker поднимает merged exporter на `:9108`, а Prometheus
  скрапит interactive и heavy targets отдельно. `PROMETHEUS_MULTIPROC_DIR`
  намеренно не шарится между контейнерами из-за независимых PID namespaces;
  entrypoint очищает его до импорта Celery, штатный child shutdown вызывает
  `mark_process_dead`. При SIGKILL остаются
  stale live-gauge files до перезапуска контейнера, поэтому alerting должен
  учитывать scrape health и worker readiness.
- Autoscaling должен учитывать до 90 s warmup и не направлять interactive queue
  на worker без успешного runtime health.
- Для нескольких replicas одного worker service static scrape targets нужно
  заменить на Docker/Kubernetes service discovery, чтобы Prometheus скрапил
  каждый replica, а не только service endpoint.
- Старые local embeddings остаются в таблице как неиспользуемые версии до
  отдельной housekeeping-очистки; retrieval выбирает только новый fingerprint.
- Полный backend suite прошёл прежнюю точку `pool-16` и дал `1075 passed`,
  но остаётся красным из-за unrelated config/.env, stale RAG mocks и Telegram
  network fixtures. Redis lifecycle cascade (`46 NameError`) исправлен и
  соответствующие helper tests проходят; остальные baseline failures не
  маскируются и не исправлялись вне scope phase 1.
- Phase 2 (`78441314`, `ebb6bce`) сохранена без изменений: exporter не меняет
  `TargetContract`/`TurnContract`, bootstrap, planner или retrieval behavior.
  Следующая фаза может опираться на стабильный runtime и доступные agent
  counters/histograms; это исправление не реализует её scope.
