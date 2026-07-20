# Единый план: фаза 0 — baseline, fixtures и safety freeze

**Статус:** подготовка, без runtime-изменений  
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
код. До прохождения этой фазы следующие флаги запрещены.
