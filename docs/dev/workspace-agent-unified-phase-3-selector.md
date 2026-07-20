# Единый план: фаза 3 — один полный Context Selector

**Статус:** план  
**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фаза 2

## Цель

Убрать смешение visibility и relevance и оставить один проверяемый semantic
decision между discovery и materialization.

## Реализация

1. Расширить selector schema до assessments всех visible refs и source
   dispositions.
2. Превратить candidate registry в typed `CandidateEnvelope` с `origin`,
   nullable `semantic_score`, parent, source IDs и available fidelity.
3. Сохранить ambient candidates в registry отдельным inclusion rule.
4. Удалить второй semantic assessment path: action planner не переоценивает
   те же candidates после Selector.
5. Детерминированно проверить:
   - каждый visible ref оценен ровно один раз;
   - неизвестные и duplicate refs отклонены;
   - `irrelevant` не materialize-ится;
   - role/resolution согласованы;
   - source disposition согласуется с assessments;
   - cardinality соблюдена.
6. Заменить select-all fallback на exact-only + bounded retry + explicit gap.
7. Для complete semantic source не менять `irrelevant` на `direct`: complete
   относится к исследованию и assessment корпуса.
8. Для structural source Selector не вызывается.

## Безопасный fallback

При timeout/schema error:

- сохранить authoritative exact targets;
- не добавлять ambient/semantic candidates без положительного assessment;
- разрешить один bounded retry;
- после retry вернуть `selector_failed`/partial gap;
- не выбирать слабый hit ради source representation.

## Основные файлы

- `backend/app/services/agent/research/planner_decision.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/material_plan.py`;
- `backend/app/services/agent/research/prefetch.py`;
- `backend/app/services/ai/rag_tools.py`;
- selector schema, replay и fallback tests.

## Тесты

- relevant/irrelevant ambient note;
- no_relevant_candidate для required discovery с `min=0`;
- optional source не блокирует ready;
- invalid JSON и duplicate refs;
- parent post виден, но не materialize-ится автоматически;
- semantic complete оценивает весь corpus batch-ами;
- exact target сохраняется при Selector failure.

## Exit criteria

- `fallback_select_all_rate=0`;
- `required_source_forced_selection_rate=0`;
- один semantic LLM call на registry pass;
- assessment completeness проверяется без semantic эвристик в Python;
- baseline relevant recall не ухудшился.

## Откат

Выключить `unified_selector`; вернуть предыдущий selector projection только для
shadow comparison. Не смешивать новый assessment schema со старым select-all
fallback в одном enabled path.
