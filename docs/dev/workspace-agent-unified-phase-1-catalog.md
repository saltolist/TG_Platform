# Единый план: фаза 1 — typed catalogs и deterministic aggregates

**Статус:** план  
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
