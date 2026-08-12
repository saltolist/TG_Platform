# Workspace Agent phase 4: discovery summaries и contextual hybrid retrieval

Фаза 4 реализована поверх SearchIntentLedger из фазы 3. Изменения ограничены
retrieval/indexing; compact planner, deterministic sufficiency и output contracts
фазы 5–6 не изменялись.

## Что добавлено

- Migrations `020_discovery_context` и `021_discovery_keywords` добавляют к
  `note_embeddings`: `search_text`, `object_title`, `object_status`,
  `index_revision` и normalized `keywords`.
- `note_summary` и `post_summary` индексируются существующим async embedding
  worker. Summary — bounded extractive fallback (`title + leading text`, до
  160 символов), поэтому путь работает без дополнительного LLM call.
- Оригинальный `chunk_text` сохраняется для citation/evidence. В embedding и
  PostgreSQL FTS используется отдельный contextual prefix (`Document`, `Section`),
  поэтому retrieval-контекст не меняет первоисточник.
- Discovery выполняется на object summaries и contextual chunks с rank fusion;
  максимум 5 object candidates. `SearchObjectChunks` принимает explicit
  `object_ids[]` и никогда не расширяет поиск за их пределы.
- Tenant/type/status/scope filters применяются до retrieval. Exact source
  revision из `SourceRequirement` прокидывается в search и отбрасывает stale
  index rows.
- Summary nodes не проходят в `format_rag_context`, поэтому summary ID не может
  стать answer evidence. При удалении объекта удаляются и summary nodes.
- `AGENT_RETRIEVAL_PHASE4_ENABLED` (default `true`) возвращает agent SearchNodes
  на phase-3 single hybrid policy для rollback; async indexing остаётся
  совместимым с этим режимом.

## Quality/latency gate

Воспроизводимый fixture и CLI находятся в
`backend/tests/fixtures/agent_retrieval_phase4/v1/scenarios.json` и
`backend/scripts/agent_phase4_retrieval_report.py`.

| Метрика | Phase 3 baseline | Phase 4 | Изменение |
|---|---:|---:|---:|
| candidate recall@5 | 1.000 | 1.000 | 0 |
| evidence recall@3 | 1.000 | 1.000 | 0 |
| deep reads (8 scenarios) | 40 | 24 | −40.0% |
| irrelevant deep reads | 30 | 14 | −53.3% |
| rank-fusion CPU p50/p95 | n/a | ~0.004/~0.004 ms | новый bounded overhead |

Запуск gate:

```bash
cd backend
PYTHONPATH=. .test-venv/bin/python scripts/agent_phase4_retrieval_report.py --check
```

Это retrieval fixture и модель стоимости deep reads, а не production end-to-end
SLO. Реальные DB/provider p50/p95 пока не измерены на corpus нужного размера.

## Exit criteria

| Критерий фазы 4 | Результат |
|---|---|
| candidate recall@5 проходит threshold | Выполнено: `1.000 >= 0.95` на 8-case fixture |
| evidence recall не хуже baseline | Выполнено: `1.000`, delta `0` |
| irrelevant deep reads −30% или лучше | Выполнено: `−53.3%` |
| summary IDs не принимаются validator/evidence formatter | Выполнено: dedicated test; summary nodes skipped before cites |
| stale index revision обнаруживается | Выполнено: exact revision filter + dedicated test |
| object candidate limit 5 | Выполнено: hard cap in discovery/tool + test |
| chunks ищутся только в selected objects | Выполнено: `SearchObjectChunks` requires object IDs + SQL filters + test |
| tenant/type/status/scope filters aligned | Выполнено для vector/FTS paths; legacy rows use fallback `chunk_text` |

## Риски и handoff следующей фазы

1. Fixture не заменяет held-out production corpus. Следующей фазе нужны
   anonymized labels для target/evidence recall и DB/provider latency.
2. Fallback summary extractive, а не LLM-generated. Это сознательно сохраняет
   bounded cost; качество summary generation следует оценить отдельно, не
   смешивая с planner benchmark.
3. `index_revision` использует explicit object revision, а при его отсутствии
   stable content fingerprint. Источник должен перейти на единый revision field,
   если появится такой контракт.
4. Candidate discovery сейчас выполняет summary и contextual hybrid passes
   последовательно на одной async session. Фаза 5 может добавить parallel
   actions на уровне planner/runtime, не расширяя retrieval scope.
5. Migrations `020_discovery_context` и `021_discovery_keywords` должны быть
   применены до включения worker нового кода; rollback flag отключает phase4
   discovery, но не удаляет новые
   колонки/nodes.

Handoff для фазы 5: использовать `candidate=true`, `summary_only`,
`selected_object_ids`, `index_revision` и `SearchObjectChunks` как typed inputs
для compact `PlannerDecision`. Не превращать summary hits в EvidencePack и не
переносить в phase 5 новый свободный planner rationale.
