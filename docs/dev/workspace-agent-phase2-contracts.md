# Workspace Agent: Phase 2 Handoff

**Статус:** реализовано на ветке `cursor/per-post-analytics-foundation`  
**База:** commit `1db306b9297e439d08126fb7b233971392928d54`  
**Область:** typed TurnContract/TargetContract, deterministic bootstrap, multi-target/multi-source contracts

## Что сделано

- Добавлены immutable Pydantic-модели `TargetContract`, `TargetRef`, `CorpusRef`, `SourceRequirement`, `SourceBudget`, `RunBudget` и `TurnContractV2` (`workspace.target/v2`, `workspace.turn/v2`).
- Введена deterministic resolution для explicit links/IDs, текущего open object, recent note и dialog ledger. Semantic search hits в targets не поднимаются.
- Targets, corpora и candidates разделены: discovery остаётся evidence-кандидатом до отдельного `Open*`.
- Поддержаны наборы targets и ambiguity policy. Для равноправных ledger-кандидатов выдаётся один короткий вопрос, а retrieval не запускается.
- Source requirements разделены по `source_id`; каждый имеет `kind`, `role`, `required`, `query_goal`, `scope`, `freshness` и локальный budget. Schema validator проверяет сумму local budgets против общего budget.
- `execution_mode=fast` для exact/set paths имеет `planner_calls=0`; `workspace_agent_node` пропускает classifier. Seed открывает normalized targets по id.
- Контракт и resolution events сохраняются в `dialog_evidence_turns.turn_contract`; миграция additive: `019_turn_contract_v2`.
- Добавлен opt-in flag `AGENT_TURN_CONTRACT_V2_ENABLED` (по умолчанию `0`); phase-1 compatibility contract остаётся доступным для rollback/canary.
- На evidence boundary повторно проверяются source kind, target scope и freshness; `required_source_gap` блокирует `ready`, optional source gap не блокирует.

## Exit criteria

| Критерий фазы 2 | Результат | Проверка |
|---|---|---|
| Explicit IDs 100% correct | Выполнено для поддержанных explicit links/opaque IDs; короткие неоднозначные prose tokens не считаются authoritative | `test_explicit_links_are_authoritative_multi_targets_and_never_semantic_hits`, golden suite |
| Golden target accuracy >=95% | 20/20 = 100% deterministic cases | `test_phase2_golden_target_accuracy_is_at_least_95_percent` |
| Semantic hit не становится target без resolution event | Выполнено: targets создаются только resolver-ами и каждый имеет `resolution_events` | Pydantic validator + phase2 tests |
| Multi-target не теряется между nodes/turns | Выполнено: normalized state/checkpoint + ledger `turn_contract`, `source_turn_id`, `revision` | `test_ledger_multi_target_and_equal_candidate_ambiguity`, runtime/ledger tests |
| Required/optional source contracts | Выполнено: optional images не блокируют finish readiness; каждый source отдельный | `test_required_source_gap_blocks_ready_but_optional_gap_does_not` |
| Scope/freshness нельзя незаметно расширить | Выполнено на contract и evidence boundaries: kind/scope/freshness проверяются перед pack | `test_scope_and_freshness_are_rechecked_at_evidence_boundary` |
| Local/global budgets согласованы | Выполнено Pydantic model validator-ом | `test_schema_rejects_local_budget_overrun_and_mutation` |

## Quality and latency

Baseline phase 0 фиксировал `bootstrap p95=2680.3 ms` (включая classifier LLM). На phase-2 exact-link path classifier не вызывается: это проверено `mock_llm.assert_not_awaited()`; normalized seed выполняет typed `OpenNote/OpenPost`. Локальный benchmark 200x100 calls дал deterministic contract bootstrap `p50=0.0386 ms`, `p95=0.0403 ms`, `p99=0.0433 ms` на текущей машине. Это CPU-only measurement, не обещание production end-to-end latency.

Phase-2 deterministic golden set: `20/20` target resolutions (`100%`, выше floor `95%`). Agent runtime/ledger/phase-2 regression gate: `130 passed` (`test_agent_phase1_runtime.py`, `test_agent_phase2_contract.py`, research/runtime/workspace graph, dialog ledger и RAG query); baseline/golden graders: `23 passed`, `3 xfailed`.

Held-out production check (read-only, local source database): из 8 anonymized runs четыре были target-bearing (post-scope edits), четыре — corpus/recommendation/inventory без target. Для target-bearing runs expected target был выведен из сохранённого scope/current-object context, без использования semantic hits; phase-2 resolver дал `4/4 = 100%`. Raw user text и identifiers не добавлялись в репозиторий. Это подтверждает локальный release check, но не является автономным CI gate: воспроизводимость требует доступа к защищённому source database или отдельному согласованному label artifact.

Общий backend suite не используется как phase-2 acceptance gate после сужения scope до агентной системы. Последний широкий прогон показал failures в non-agent context/analytics/Telegram/seed областях; agent runtime/research/ledger/contract gate при этом полностью зелёный. Общий backend green остаётся отдельной задачей и не заявляется здесь.

## Остаточные риски

- Explicit prose IDs короче восьми символов намеренно остаются planner candidates; для таких формулировок нужен следующий resolution path или UI link context.
- Phase-1 compatibility path продолжает читать compatibility fields (`target`, `corpus`, `max_steps`), поэтому новые nested contracts пока дублируют часть state.
- Held-out target check измерен на локальных production traces (`4/4` target-bearing), но label artifact не коммитится из-за raw production content; перед внешним rollout нужен защищённый повторяемый annotation/eval job и canary сравнение target/evidence/latency.
- Общий backend suite не подтверждён зелёным; оставшиеся non-agent failures вынесены за пределы phase-2 agent release gate.

## Handoff в фазу 3

Следующий шаг: реализовать `SearchIntentLedger` поверх `source_requirements`, привязать каждый search к `source_id + intent_key + scope/freshness revision`, дедуплицировать повторные `Search/Open` и вычислять `exhausted` детерминированно. Нельзя менять target/source contracts или добавлять новый resolver layer; использовать уже сохранённые `resolution_events`, `revision`, budgets и source-boundary validator.
