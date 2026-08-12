# Единый план: фаза 1 — typed catalogs и deterministic aggregates

**Статус:** завершена 2026-07-24, rollout flag по умолчанию выключен
**Главный план:** [workspace-agent-unified-integrity-counting-plan.md](workspace-agent-unified-integrity-counting-plan.md)  
**Зависимость:** фаза 0

## Цель

Сделать каталог авторитетным источником структурных фактов, не меняя semantic
selection и финальный prompt.

## Реализация

1. Ввести versioned internal catalog snapshot builder для notes/posts.
2. Использовать его в `ListPosts`, `ListGlobalNotes`, `ListPostNotes`, полном
   note inventory и current-post ambient catalog.
3. Для каждого item возвращать явные `file_count`, `image_count`,
   `has_files`, `has_images`, parent relation, revision и visibility.
4. MIME классифицировать только по нормализованному `mime_type`/типу файла;
   имя файла является display metadata, но не доказательством image.
5. Возвращать aggregates backend-ом. Не считать подмножества Answer Model.
6. Разделить global notes, post-owned notes, direct post media и note media.
7. Убрать искусственные semantic `score=1.0`; для ambient origin score равен
   `null`.
8. Сделать members durable/paged. `limit` отображения не должен менять
   `total_members` и `members_complete`.

## Совместимость

- Старый текстовый summary остается для planner и trace.
- Новая structured metadata добавляется рядом с ним.
- Старые catalogs без properties читаются как `unknown`, а не backfilled false.
- Existing citation paths и refs не меняются.

## Основные файлы

- новый внутренний catalog snapshot builder рядом с research/rag services;
- `backend/app/services/ai/rag_tools.py`;
- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/evidence.py`;
- `backend/app/services/agent/runtime/state.py`;
- `backend/tests/test_rag_tools.py` и catalog schema tests.

## Тесты

- нули и positive attachment counts;
- один note с двумя images;
- global + post-owned union без double count;
- direct media отдельно от note files;
- deleted/hidden/tenant isolation;
- MIME без расширения и расширение без MIME;
- >100 members и paging;
- ambient candidate с `semantic_score=null`.

## Exit criteria

- backend aggregate совпадает с независимым test oracle во всех fixtures;
- отсутствие поля нигде не становится false/0;
- search/selector traces еще идентичны baseline по selection;
- latency не ухудшилась выше согласованного порога;
- feature flag позволяет вернуть старый catalog projection.

## Откат

Выключить `unified_catalog`; оставить новый snapshot builder только в shadow
режиме. Не удалять старую metadata projection до завершения фазы 6.

## Результат

- добавлен internal schema `workspace.catalog-snapshot/v1` с typed members,
  property coverage, backend aggregates, `total_members`, page cursor и
  `source_requirement_id`;
- один builder используется для posts, global notes, post-owned notes, полного
  note inventory и current-post ambient catalog;
- legacy summary, citation paths, refs и `ToolOutcome.items` сохранены, typed
  snapshot добавляется рядом в evidence metadata только при
  `AGENT_UNIFIED_CATALOG_V1_ENABLED=1`;
- отсутствие `files`/`media`, malformed records и неизвестный MIME сохраняются
  как `null` + `omitted_properties`; доказанный пустой список дает явные нули и
  `false`;
- MIME нормализуется только из `mime_type`/`mimeType`/`type`; filename и
  extension не участвуют в image classification;
- note aggregates и post direct/nested/union aggregates считаются backend-ом;
  global и post-owned notes объединяются по стабильному `note:<id>` без
  двойного счета;
- catalog revision учитывает attachment/media structure, если источник не дал
  явный положительный `revision`/`syncRevision`;
- tenant overlay post notes используются в `OpenPost`, `ListPosts` и полном note
  inventory; deleted/hidden/inaccessible members исключаются до snapshot;
- ambient candidates при включенном флаге имеют
  `origin=ambient_current_post`, `semantic_score=null` и больше не получают
  искусственный `score=1.0`; legacy path при выключенном флаге сохранен;
- страницы ограничены 100 members, но aggregates и `total_members` считаются по
  полному отфильтрованному corpus; display `limit` на это не влияет.

## Проверки

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_agent_unified_phase1_catalog.py tests/test_rag_tools.py \
  tests/test_agent_research.py tests/test_agent_adaptive_evidence_depth.py \
  tests/test_agent_phase6.py tests/test_agent_unified_phase0.py \
  tests/test_agent_phase5_planner.py tests/test_config.py \
  tests/test_agent_phase2_contract.py tests/test_turn_contract.py \
  tests/test_message_context_manifest.py tests/test_agent_runtime.py \
  tests/test_workspace_graph.py tests/test_rag.py tests/test_rag_query.py \
  tests/test_rag_retrieval_policy.py tests/test_agent_phase4_retrieval.py \
  tests/test_agent_listing.py tests/test_agent_e2e.py
.venv/bin/python scripts/agent_unified_phase0_report.py --repeat 2 --check
```

Результат: `346 passed, 1 warning`. Warning относится к изменению pooling в
`fastembed` и существовал вне этой фазы. Phase-0 replay дважды вернул прежний
digest `4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474`;
protected fixture hashes и baseline gates не изменились.

In-memory benchmark builder-а для 101 notes с двумя файлами на 200 повторах:
p50 `1.193 ms`, p95 `1.275 ms`, max `1.344 ms`. Дополнительных DB, planner или
LLM calls builder не создает.

## Exit criteria

- [x] backend aggregates совпадают с независимыми expected oracles для notes,
  direct post media, nested note media и union;
- [x] missing property и unknown MIME нигде не превращаются в `false`/`0`;
- [x] planner/search/selector baseline не изменил selection: relevant suites
  прошли, frozen replay digest идентичен фазе 0;
- [x] snapshot overhead измерен отдельно и не добавляет I/O или model calls;
- [x] `AGENT_UNIFIED_CATALOG_V1_ENABLED=0` сохраняет legacy projection, а
  включенный flag добавляет typed metadata рядом;
- [x] schema, MIME, zero/positive counts, two-image note, global/post union,
  direct/nested media, tenant/status guards, 101-member paging и ambient
  nullable score покрыты тестами.

## Остаточные риски

- flag остается default-off до shadow/canary проверки на production-like data в
  фазе 6;
- legacy objects без attachment arrays и файлы без доказуемого MIME увеличат
  `catalog_property_unknown_rate`; это намеренный unresolved факт, а не ноль;
- offset cursor детерминирован для конкретного source revision, но concurrent
  mutation между запросами страниц должна обнаруживаться по item revisions;
  snapshot-level revision/checkpoint enforcement относится к фазам 2/4;
- structural fast path, semantic selection policy и post-pack verifier этой
  фазой намеренно не менялись, поэтому использование aggregates для готового
  ответа включается последующими фазами.
