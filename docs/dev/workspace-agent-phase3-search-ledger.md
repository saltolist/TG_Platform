# Workspace Agent: Phase 3 SearchIntentLedger

**Статус:** реализовано на ветке `cursor/per-post-analytics-foundation`
**Область:** run-scoped search/read dedupe, bounded rewrites, validator-driven finish

## Что сделано

- Добавлен сериализуемый `search_ledger` в `AgentGraphState`; он проходит через
  seed, planner, tool и checkpoint state.
- `canonical_tool_signature` нормализует query/aliases/defaults и включает
  `source_requirement_id`, scope/freshness и target revision. На его основе
  строится semantic `intent_key`.
- Для intent поддерживаются `planned/running/satisfied/exhausted`; terminal
  entries несут `exhausted_reason`, summary, hits и record ids для run-local cache.
- Успешные reads и empty `SearchNodes` outcomes не вызывают provider повторно.
  Новый search intent допускается только как один gap-linked rewrite; второй
  rewrite получает `rewrite_limit_reached`.
- Legacy L1/hybrid results переиспользуются в seed. Это устраняет второй
  embedding/vector pass перед planner и согласует discovery с уже используемой
  `hybrid_prefetch -> retrieve_for_chat` политикой.
- После первой отклонённой попытки `FinishRetrieval` следующий такой emission
  преобразуется в `ValidatorEvent`; повторный LLM finish-loop не запускается.
- Tool observability теперь включает `intent_key`, source id, terminal state,
  `exhausted_reason` и `cached`, что позволяет измерять external calls отдельно
  от planner emissions.

## Exit criteria

| Критерий | Результат | Проверка |
|---|---|---|
| duplicate successful external calls = 0 | Выполнено для run-local terminal intents; cache hit не вызывает `_execute_tool` | `test_tool_node_does_not_repeat_successful_external_call` |
| intent не более двух исполнений с rewrite | Выполнено: initial + один gap-linked rewrite; третья попытка exhausted | `test_only_one_gap_linked_rewrite_is_allowed` |
| repeated `FinishRetrieval` отсутствует | Новый repair emission становится `ValidatorEvent`; legacy phase-0 fixture сохраняется как исторический baseline с 5 annotated loop failures | `test_second_finish_becomes_validator_event`, `test_agent_phase0_baseline.py` |
| planner получает `exhausted_reason` | Выполнено: ledger renderer добавляет reason в planner context и tool outcome | `test_ledger_caches_success_and_empty_search_outcomes` |
| quality floor/target-evidence accuracy не ухудшены | Phase-0 snapshot и phase-2 contract tests зелёные; production held-out label artifact не менялся | `test_agent_phase0_baseline.py`, `test_agent_phase2_contract.py` |
| problematic path имеет measurable gain | Synthetic run показывает 10 одинаковых reads -> 1 external call; rewrite budget 3 -> 2 calls. End-to-end provider latency требует canary trace | phase-3 ledger tests + benchmark ниже |

## Quality и latency

Локальный acceptance gate:

```text
phase-3 ledger tests: 6 passed
research/rag/workspace regression set: 84 passed
phase-0 quality freeze: 13 passed, 3 expected xfailed
```

Детерминированный benchmark ledger (без БД/LLM) показывает:

| Сценарий | До ledger | После ledger | Изменение |
|---|---:|---:|---:|
| 10 одинаковых successful reads | 10 external calls | 1 external + 9 cache hits | -90% external calls |
| search + rewrite + repeated rewrite | 3 external attempts | 2 external + 1 exhausted event | -1 provider round trip |
| rejected finish + repair finish | 2 LLM `FinishRetrieval` emissions | 1 LLM finish + 1 `ValidatorEvent` | -1 finish emission |

На текущей машине 1000x in-process benchmark дал для ledger policy `p50/p95/p99`
`0.1448/0.1707/0.2892 ms` на 10-read сценарии и
`0.0503/0.0545/0.0594 ms` на rewrite policy. Это control-flow/round-trip measurement, а не production SLO: фактические
milliseconds зависят от provider/DB/network. Phase-0 baseline остаётся
источником сравнения: problematic run p95 `119061.25 ms`, research p95
`88257.2 ms`; для end-to-end delta нужен anonymized canary trace с
`tool_outcomes.cached=false` и phase timings.

## Остаточные риски

- Source binding для planner-generated searches без явного
  `source_requirement_id` использует deterministic kind/scope fallback; при
  нескольких одинаковых corpora нужен отдельный held-out eval.
- Terminal cache живёт только внутри одного run/checkpoint; междучатовый cache
  намеренно не добавлен, чтобы не смешивать revisions/tenant scope.
- Legacy phase-0 golden fixture содержит исторические duplicate/finish-loop
  failures и не является replay нового runtime; rollout должен собрать новые
  traces на тех же сценариях.
- `hybrid_prefetch` и tool discovery теперь согласованы через L1 reuse, но
  ranking/recall quality hybrid path относится к фазе 4 и здесь не менялась.
- Ошибочный external tool outcome маркируется `exhausted` и cacheable; если
  provider transient failures нужно ретраить, это должно быть отдельной policy
  с явным budget, а не повтором того же intent planner-ом.

## Handoff в фазу 4

Сохранить ledger/source/revision invariants. Следующий шаг — discovery summaries
и contextual hybrid retrieval: candidate recall@5, evidence recall, object
candidate limit и selected deep-read limit. Использовать `search_ledger` как
границу между discovery и deep reads; summary IDs не считать evidence и не
ослаблять validator event/required-source gates.
