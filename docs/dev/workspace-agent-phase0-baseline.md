# Workspace Agent phase 0: baseline и quality freeze

**Снимок:** 2026-07-18 19:43:37 UTC  
**План:** [workspace-agent-intelligence-performance-plan.md](workspace-agent-intelligence-performance-plan.md)  
**Фаза:** 0, без перехода к фазе 1

## Набор сценариев

Зафиксированы 32 анонимизированных production-like trace:

- 3 последовательных turn чата `b9a1ff2d-4fae-47f3-9217-b0b9423c60be`;
- 29 стратифицированных runs: completed latency quantiles, failed, interrupted,
  cancelled и незавершённые;
- split: 24 `golden`, 8 `held_out`;
- raw user/answer/reasoning/summary/query и все прочие chat/run/object ID удалены;
  сохранены hashes, длины, tokenized refs, trajectory, timings и структурные поля.

Источник истины для воспроизведения:

- fixture: `backend/tests/fixtures/agent_baseline/v1/scenarios.json`;
- schema/aggregator: `backend/app/services/agent/runtime/baseline.py`;
- read-only exporter: `backend/scripts/export_agent_phase0_baseline.py`;
- report CLI: `backend/scripts/agent_phase0_report.py`.

```bash
cd backend
PYTHONPATH=. .test-venv/bin/python scripts/agent_phase0_report.py
PYTHONPATH=. .test-venv/bin/pytest -q tests/test_agent_phase0_baseline.py
```

## Latency baseline

Полная population-оценка по 207 runs с `completed_at` в текущей БД:

| Метрика | p50 | p95 | p99 | Среднее |
|---|---:|---:|---:|---:|
| total latency | 39.310 с | 106.113 с | 184.407 с | 53.602 с |

Стратифицированный fixture set не является frequency-weighted production
выборкой. Его total latency (p50 9.023 с, p95 119.061 с, p99 1339.780 с)
используется для regression replay, а не как SLO estimate.

Per-phase timing по доступным durable events fixture set:

| Фаза | N | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| startup: run created -> graph started | 28 | 0.436 с | 4.769 с | 5.176 с |
| bootstrap: graph started -> workspace decision | 10 | 1.555 с | 2.680 с | 2.733 с |
| research: workspace decision -> answer start/terminal | 9 | 29.629 с | 88.257 с | 90.136 с |
| answer: answer start -> terminal event | 13 | 0.002 с | 5.635 с | 6.791 с |

Низкий `answer` p50 отражает старые traces без partial-stream boundary: для них
доступны только почти соседние final answer и terminal event. Sample size
сохраняется рядом с percentile, чтобы это ограничение нельзя было скрыть.

## Cold и warm

Проблемный чат даёт сопоставимый cold/warm срез одного диалога:

| Turn | Класс | Total | Startup | Bootstrap | Research | Answer | Planner | Inferred LLM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | cold | 102.667 с | 4.810 с | 2.600 с | 90.606 с | 4.671 с | 7 | 9 |
| 2 | warm | 3.372 с | 0.206 с | 1.335 с | 0.619 с | 1.217 с | 0 | 2 |
| 3 | warm | 34.456 с | 0.107 с | 1.550 с | 25.724 с | 7.080 с | 4 | 6 |

Turn 1 подтверждён worker log: два retry `Future attached to a different loop`
и локальная инициализация embedding model. Остальные production runs имеют
`temperature=unknown`: старые события не содержат worker-generation/warmup ID,
поэтому приписывать им cold/warm постфактум нельзя.

## Calls, tokens и targets

По 207 runs: planner calls p50/p95/p99 = `4/11/13`, tool calls = `2/9/11.9`;
зафиксировано 115 вызовов `FinishRetrieval`.

У старых agent runs token coverage равен `0/32`: `ai_model_usage_events`
заканчиваются 2026-07-11 и не связаны с runs 2026-07-13..18. Нули не
подставляются: поля имеют `null` и `availability=not_recorded_by_agent_runtime`.
После фазы 0 каждый новый run получает durable `run_metrics` с call phase,
duration и prompt/completion token estimate (`chars_div_4_estimate`). Это
телеметрия, не token budget и не provider-billed usage.

Target accuracy доступна только для двух вручную проверенных factual turn
проблемного чата: `2/2 = 100%`, coverage `2/32 = 6.25%`. В БД структурированный
`turn_contract.target` есть лишь у 2 из 221 runs, поэтому общую production
target accuracy сейчас заявлять нельзя. Этот coverage gap является baseline,
а не заменяется эвристической разметкой по финальному ответу.

## Deterministic graders

| Grader | Pass | Fail | Quality floor |
|---|---:|---:|---:|
| no duplicate non-terminal tool call | 30 | 2 | >= 30/32 |
| valid `FinishRetrieval.evidence_ids` | 31 | 1 | >= 31/32 |
| no repeated `FinishRetrieval` | 27 | 5 | >= 27/32 |
| final output event schema | 32 | 0 | 32/32 |
| annotated target accuracy | 2 | 0 | 100% |

Grader implementation is pure and runs over durable events. Output schema
requires final `text: str`, `claims: [{text: str, evidence_ids: str[]}]` and
`evidence_ids: str[]`; failed/interrupted/cancelled/non-terminal traces do not
require an answer.

## Frozen regressions

`b9a1ff2d`:

- turn 1: `OpenNote -> OpenNote -> OpenPost -> FinishRetrieval x4`;
- turn 3: duplicate `OpenNote` и `FinishRetrieval x2`;
- turn 2: все четыре formal graders проходят.

В остальных traces: ещё один duplicate `ListPosts`, три finish-loop сценария и
один invalid finish-evidence trajectory. Каждый failure хранит trace,
`known_failures`, текущий grader result и желаемый quality floor.

Три проверки проблемного чата оформлены как `strict xfail`: они остаются
видимыми failing regressions, но не делают baseline CI красным. XPASS будет
считаться ошибкой до явного обновления fixture/ожидания после исправления.

Отдельно обнаружены два ограничения test harness/runtime lifecycle:

- параллельные pytest-процессы очищают одну `tg_test` и конфликтуют по FK;
- даже последовательный полный `pytest -m "not golden" -x` на Python 3.14
  воспроизводимо дошёл до `pool-16` на 118-м тесте и упал в
  `ensure_checkpointer_ready()` с `psycopg_pool.PoolTimeout`: loop-keyed
  `AsyncPostgresSaver` pools накапливаются и исчерпывают PostgreSQL clients.

Второй failure относится к loop/pool ownership фазы 1 и в фазе 0 не исправлялся.
Изолированные gates зелёные: runtime `27 passed`; phase-0/trace/graders
`37 passed, 3 xfailed`; executable golden `3 passed`. Полный backend suite
остаётся красным baseline по указанной причине.

## Exit criteria фазы 0

| Критерий | Результат |
|---|---|
| Набор воспроизводится локально/в CI | Выполнено: static v1 fixture, DB-independent report CLI, отдельный CI pytest gate |
| Каждый известный failure имеет trace и ожидаемый результат | Выполнено для formal graders и `b9a1ff2d`; runtime/cold failures размечены отдельно |
| Есть p50/p95/p99 и per-phase timing | Выполнено; рядом хранится N и ограничения старых event boundaries |
| Единый scenario fixture format | Выполнено: `workspace-agent-scenario/v1` |
| Cold/warm разделены | Выполнено для подтверждённого чата; неизвестные runs не классифицированы выдуманно |
| Quality floor зафиксирован | Выполнено численными pass counts и target accuracy floor |
| Calls/tokens зафиксированы | Calls восстановлены; historical token gap зафиксирован, новые runs получают `run_metrics` estimates |

Фаза 1 не начата: async loop ownership, worker warmup, pool-after-fork и retry
поведение не изменялись.
