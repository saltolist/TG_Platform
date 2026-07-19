# Workspace Agent phase 5: compact planner и deterministic sufficiency

Фаза 5 реализована поверх typed TurnContract и SearchIntentLedger фаз 2–4.
Новый протокол включается при `AGENT_TURN_CONTRACT_V2_ENABLED=1` вместе с
`AGENT_PLANNER_PHASE5_ENABLED=1` и имеет rollback в старый planner без schema
migration. Для v1 contract graph намеренно остаётся на legacy planner: без typed
budgets/source requirements deterministic sufficiency не имеет достаточных данных.

## Что изменено

- `planner_decision.py` вводит строгие `PlannerDecision`, `PlannerAction` и
  конечный `DecisionCode`. В decision нет observations, rationale, полного plan
  или `FinishRetrieval`; допускается до трёх уникальных read actions и
  `state_updates` для выбранных candidates.
- Compact planner использует отдельный короткий system prompt и `max_tokens=450`.
  Невалидный JSON получает максимум одну schema-only retry; второй сбой становится
  deterministic `FINISH_PARTIAL`, а не новым repair loop.
- `sufficiency.py` проверяет после seed и каждого tool result required source,
  scope/freshness через существующий TurnContract matcher, primary evidence и
  terminal intent states. Summary nodes не считаются evidence. Результаты имеют
  `ready`, `follow_up_allowed`, `exhausted`, `invalid` и `allowed_next_intent_ids`.
- Graph routes modern path через `seed -> sufficiency` и `tool -> sufficiency`.
  Первый `ready` сразу пакуется; partial/exhausted завершает run с явными gaps.
  LLM больше не получает повторный finish ping-pong.
- Dynamic counters (`planner_calls_used`, `search_calls_used`, `deep_reads_used`,
  `tool_calls_used`) соблюдают budgets из TurnContract. Soft deadline переводит
  run в partial, hard deadline ограничивает provider call.
- Один compact decision может содержать до трёх независимых actions и выполняется
  одним tool node, поэтому между ними не возникает planner round trip. Независимые
  search/open/analytics actions получают forked state и отдельные DB sessions через
  `asyncio.gather`; dependent inventory/media-list actions остаются последовательными.

## Acceptance gate

```bash
cd backend
PYTHONPATH=. .test-venv/bin/pytest -q tests/test_agent_phase5_planner.py
PYTHONPATH=. .test-venv/bin/python scripts/agent_phase5_planner_report.py --check
```

На 8 воспроизводимых сценариях (`tests/fixtures/agent_planner_phase5/v1`):

| Метрика | До фазы 5 | Фаза 5 | Изменение |
|---|---:|---:|---:|
| invalid planner output | не зафиксирован как floor | 0/11 (`0%`) | ниже `<1%` |
| planner calls | 35 | 11 | `−68.6%` |
| wasted steps | 14 | 0 (`0%`) | ниже `<10%` |
| duplicate opens | 3 сценария | 0 | устранены в fixture |
| repeated FinishRetrieval emissions | 12 | 0 | устранены |
| planner output budget | 1500 tokens | 450 tokens | `−70%` |
| estimated latency p50/p95 | 20.75/26.25 s | 8.00/10.75 s | `−61.4%` / `−59.0%` |
| quality floor | 1.000 | 1.000 | `0` |

Latency здесь является прозрачной control-flow моделью (`5 s` planner call,
`250 ms` tool call), а не production SLO. Production canary должен заменить её
реальными trace durations и отдельно измерить DB/provider parallelism.

## Exit criteria

| Критерий | Результат |
|---|---|
| invalid planner output `<1%` | Выполнено: `0%` на phase-5 fixture; schema retry ограничен одной попыткой |
| planner calls соответствуют mode budgets | Выполнено: `0` нарушений; fast profile не вызывает planner |
| wasted planner steps `<10%` | Выполнено: `0%` |
| quality floor не ухудшился | Выполнено: fixture floor `1.000`; phase-2/3/4 regressions зелёные |
| problematic chat без duplicate open/finish loop | Выполнено в synthetic trajectory: duplicate opens `0`, finish emissions `0`; нужен canary trace для production подтверждения |

## Проверки и риски

- Фаза 5 не меняет answer model/output contracts фазы 6 и не утверждает
  groundedness semantic score. Summary/context invariants фазы 4 сохранены.
- Batch fan-out ограничен независимыми read tools и отдельными sessions; реальный
  wall-clock выигрыш зависит от pool/provider capacity и должен быть подтверждён
  canary trace. Dependent inventory/media-list calls остаются serial.
- `AGENT_PLANNER_PHASE5_ENABLED` rollback оставляет старые planner state fields;
  после canary требуется удалить legacy path и временный flag по rollout policy.
- Текущий synthetic gate не заменяет held-out semantic eval и production p95;
  rollout должен собрать те же поля из `planner_steps`, `tool_outcomes`,
  `validator_events` и `llm_metrics`.

## Handoff в phase 6

Сохранить `SufficiencyResult.evidence_ids` как единственный вход answer layer.
Следующий шаг — versioned `EvidencePack`, task-specific OutputSchema и
независимый выбор planner/answer models; format-only repair должен работать только
над уже проверенным pack и не запускать retrieval.
