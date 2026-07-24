# Единый план: фаза 0 — baseline, fixtures и safety freeze

**Статус:** завершена 2026-07-24, без runtime-изменений
**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)

## Цель

Зафиксировать, что именно означает «не сделать хуже», и получить воспроизводимый
rollback point до изменения контрактов, каталогов и Selector.

## Что фиксируем

- текущие ответы и evidence для существующих golden/held-out fixtures;
- latency p50/p95/p99, planner/tool calls и context tokens;
- текущие `TurnContract`, `material_plan`, `EvidencePack`, search ledger;
- успешные fast/exact/mutation flows;
- near-miss сценарии с ambient note, слабым required hit и image count;
- checkpoint/resume и interrupted/cancelled runs.

## Артефакты

1. Анонимизированные snapshots: contract, candidate registry, selector input,
   material plan, final pack, sufficiency и trace.
2. Golden cases:
   - одна note с двумя изображениями;
   - note внутри post;
   - irrelevant ambient note;
   - external relevant note + unrelated parent post hit;
   - invalid selector output;
   - catalog >8 и >100 objects.
3. Baseline report с доступностью каждой метрики. Не подменять отсутствующие
   данные нулем.
4. Feature flag и documented rollback command/config.

## Основные файлы

- `backend/tests/fixtures/agent_planner_phase5/` и новые обезличенные fixtures;
- `backend/app/services/agent/runtime/baseline.py`;
- `backend/app/services/agent/runtime/replay.py`;
- `backend/app/services/agent/runtime/graders.py`;
- `backend/scripts/` для read-only export/report;
- `backend/tests/test_agent_phase5_planner.py` и unified-plan tests.

## Нельзя делать в этой фазе

- менять prompt, schema или fallback;
- исправлять production behavior «по пути»;
- обновлять expected results без отдельного regression note.

## Проверки выхода

- все текущие тесты проходят;
- replay повторяем минимум дважды;
- snapshots не содержат пользовательские тексты и реальные IDs;
- rollback возвращает идентичный старый path;
- quality floors записаны в master plan.

## Откат

Фаза не имеет runtime-отката: удаляется только незадействованный fixture/report
код. Rollback point: `128a96497416bc40d5d019ad3be97866ad094394`.

Для просмотра исходного пути без изменения текущей ветки:

```bash
git switch --detach 128a96497416bc40d5d019ad3be97866ad094394
```

Для конфигурационного rollback все зарезервированные флаги остаются `0`:

```text
AGENT_UNIFIED_CATALOG_V1_ENABLED=0
AGENT_TYPED_REQUIREMENTS_V1_ENABLED=0
AGENT_UNIFIED_SELECTOR_V1_ENABLED=0
AGENT_VERIFIED_PACK_BOUNDARY_V1_ENABLED=0
AGENT_PLANNER_POLICY_V1_ENABLED=0
AGENT_UNIFIED_DEFAULT_ON=0
```

В фазе 0 эти флаги не имеют runtime consumers. Тест safety freeze запрещает
подключать их к runtime до реализации соответствующей фазы.

## Результат

- добавлен полностью синтетический обезличенный fixture
  `agent_unified_phase0/v1` из 10 golden и 3 held-out scenarios;
- зафиксированы contract, candidate registry, selector input, material plan,
  final pack, sufficiency, search ledger, checkpoint и trace;
- обязательные near-miss cases покрыты, включая каталоги из 9 и 101 объектов;
- старые baseline и planner fixtures не переписаны и защищены SHA-256;
- read-only отчет объединяет существующие 32 trace scenarios с новым safety
  freeze и показывает availability каждой метрики;
- replay дал одинаковый digest
  `4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`
  на двух последовательных запусках;
- baseline latency: p50 `9022.5 ms`, p95 `119061.25 ms`, p99
  `1339780.39 ms`; context-token telemetry отсутствует в 32 из 32 runs и
  записана как `null`, а не как ноль;
- fast/exact/mutation, checkpoint/resume, interrupted и cancelled flows
  сохранены отдельными scenarios.

## Проверки

```bash
cd backend
.venv/bin/python scripts/agent_unified_phase0_report.py --repeat 2 --check
.venv/bin/pytest -q tests/test_agent_unified_phase0.py \
  tests/test_agent_phase0_baseline.py tests/test_agent_phase5_planner.py \
  tests/test_config.py
```

На фазовом прогоне: `56 passed, 3 xfailed`. Три strict xfail существовали в
исходном baseline и документируют повторный `FinishRetrieval` и duplicate
`OpenNote`; expected results не менялись.

## Exit criteria

- [x] текущий baseline/planner/config/unified набор тестов проходит;
- [x] replay повторен минимум дважды с идентичным digest;
- [x] snapshots валидируются на отсутствие пользовательских текстов, UUID,
  email и URL;
- [x] все rollout flags выключены и не имеют runtime consumers, поэтому старый
  path идентичен baseline;
- [x] quality floors и недоступность метрик записаны в master plan;
- [x] prompts, рабочие schemas, runtime fallbacks и production behavior не
  менялись.

## Остаточные риски

- synthetic fixtures фиксируют наблюдаемое baseline-поведение, но не заменяют
  shadow replay на реальном трафике в фазе 6;
- selector и structural quality metrics частично недоступны до появления typed
  catalogs/obligations; это явная недоступность, а не успешный нулевой результат;
- старый production-like baseline содержит один ранее явно разрешенный chat UUID;
  новый unified fixture полностью обезличен, старый файл не переписывался ради
  сохранения frozen expected results;
- полный backend suite не является фазовым gate: по явному решению проверяется
  релевантный baseline/planner/config/unified набор.
