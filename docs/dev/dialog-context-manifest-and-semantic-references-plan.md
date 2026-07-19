# План: контекст сообщений, прикреплённые источники и семантические ссылки

## Статус и область

Документ описывает реализацию двух связанных требований в существующем
agent-runtime path:

1. к финальному сообщению ассистента должны быть прикреплены именно те
   объекты и артефакты, которые были использованы при его подготовке;
2. ссылки на предыдущие объекты должны разрешаться семантически, включая
   анафоры и эллиптические follow-up-запросы без явного местоимения.

Это план реализации, а не утверждение, что весь описанный контракт уже
существует.

План опирается на текущие компоненты:

- typed `TurnContract/TargetContract` в
  `backend/app/services/agent/runtime/turn_contract.py`;
- `dialog_evidence_turns` и существующий dialog ledger в
  `backend/app/services/ai/rag_dialog_ledger.py`;
- durable `AgentRun.snapshot` и append-only `agent_events`;
- typed `EvidencePack` и `workspace.answer/v1`;
- `AGENT_ADAPTIVE_EVIDENCE_DEPTH_V1_ENABLED=1`;
- chat history в `GlobalChat.data.history` и post-scoped chat history.

Новый отдельный memory/ledger subsystem не создаётся. Ledger, history и
checkpoint остаются существующими слоями с разными ролями:

- history хранит пользовательские и ассистентские сообщения;
- dialog ledger хранит структурированные сущности и provenance предыдущих
  ходов;
- checkpoint/snapshot хранит состояние конкретного запуска;
- message context manifest связывает результат запуска с конкретным сообщением.

## Корневые причины

### 1. Evidence не равен прикреплённым источникам

Финальное событие уже содержит `evidence_ids` и `claims[].evidence_ids`
([executor.py:645](../../backend/app/services/agent/runtime/executor.py#L645)), а
после запуска объекты попадают в dialog ledger
([rag_dialog_ledger.py:405](../../backend/app/services/ai/rag_dialog_ledger.py#L405)).
Но отсутствует нормализованный контракт уровня сообщения, который отвечает на
три разные вопросы:

- что было передано финальной модели;
- какие материалы реально поддержали claims;
- какие пользовательские объекты и артефакты нужно прикрепить к сообщению и
  использовать в следующем ходе.

`catalog` является служебным контейнером, `semantic_card` является производным
материалом, а пост, заметка или артефакт являются пользовательскими объектами.
Смешивание этих уровней приводит к неточным вложениям и неоднозначным ссылкам.

### 2. Анафора не является отдельной структурированной операцией

Текущий resolver использует детерминированные маркеры
([turn_contract.py:463](../../backend/app/services/agent/runtime/turn_contract.py#L463)),
а классификатор получает `dialog_context`
([workspace_graph.py:250](../../backend/app/services/agent/runtime/workspace_graph.py#L250)).
Классификатор не обязан возвращать соответствие «упоминание → конкретный
объект/множество/артефакт». Поэтому сохранённый в ledger набор может существовать,
но не стать авторитетным target для research.

Проблема не в отсутствии отдельных слов в словаре. Проблема в отсутствии
дискурсивного графа кандидатов и отдельного структурированного решения
референта.

### 3. Полнота и область поиска должны быть конечными

`complete` означает полноту относительно один раз полученного авторитетного
каталога, а не поиск новых semantic top-k совпадений.

Нормальный путь:

```text
ListPosts
  -> фиксированный каталог ID: post:a, post:b, post:c, ...
  -> exact loading semantic cards по этим ID
  -> full-text fallback только для известных ID
  -> sufficiency проверяет этот конечный набор
```

Если часть карточек отсутствует, открываются только соответствующие известные
ID. Новый поиск по similarity не расширяет и не сужает исходный каталог.

## Цели и нецели

### Цели

- First-class manifest для каждого нового сообщения ассистента.
- Точные ссылки на claims, target-объекты и использованные артефакты.
- Семантическое разрешение анафоры и эллипсиса из конечного набора допустимых
  кандидатов.
- Поддержка полного множества и его подмножеств.
- Проверка tenant, типа, revision, ownership и существования до retrieval.
- Один bounded planner/resolver цикл без бесконечного поиска.
- Сохранение текущей модели evidence depth: `catalog`, `semantic_card`,
  `full_text`.
- Обратная совместимость с существующей history, SSE и legacy сообщениями.

### Нецели

- Не добавлять ветки для конкретного чата, фразы или набора постов.
- Не расширять словарь анафор как основной способ решения.
- Не считать весь переданный `EvidencePack` автоматически использованным.
- Не превращать semantic card в замену оригиналу для точных утверждений.
- Не создавать второй независимый ledger или новый router на каждый intent.
- Не перезапускать semantic search до тех пор, пока не найдётся «достаточно
  похожих» объектов.

## Целевые контракты

### Message Context Manifest

Добавить версионированный объект `workspace.message-context/v1`. Он создаётся
после валидации финального ответа и сохраняется вместе с результатом run.

```json
{
  "schema": "workspace.message-context/v1",
  "message_id": "chat-message-uuid",
  "run_id": "run-uuid",
  "source_turn_id": "run-uuid",
  "considered_context": [
    {
      "evidence_id": "/post/uuid/",
      "kind": "post",
      "fidelity": "semantic_card",
      "revision": 12,
      "role": "context"
    }
  ],
  "cited_evidence": [
    "/post/uuid/"
  ],
  "context_refs": [
    {
      "ref": "post:uuid",
      "kind": "post",
      "title": "...",
      "revision": 12,
      "source_turn_id": "run-uuid",
      "role": "claim_support",
      "provenance": "exact"
    }
  ],
  "reference_sets": [
    {
      "ref": "set:run-uuid:posts",
      "kind": "post",
      "ordered_members": ["post:1", "post:2", "post:3"],
      "selected_members": ["post:1", "post:3"],
      "selection_mode": "explicit_subset",
      "source_turn_id": "run-uuid"
    }
  ],
  "artifacts": [
    {
      "ref": "artifact:sha256:...",
      "kind": "assistant_answer",
      "content_hash": "sha256:...",
      "source_turn_id": "run-uuid",
      "role": "derived_output"
    }
  ],
  "stale_refs": [],
  "provenance": "exact"
}
```

Смысл полей:

- `considered_context` — весь typed context, переданный финальному генератору;
- `cited_evidence` — только проверенные `claims[].evidence_ids`;
- `context_refs` — пользовательские объекты, прикрепляемые к сообщению;
- `reference_sets` — упорядоченные исходные множества и выбранные
  подмножества для выражений «первый», «эти два», «остальные»;
- `artifacts` — предыдущие ответы, черновики, файлы и прочие производные
  материалы, если они были входом или результатом операции;
- `stale_refs` — сохранённые ссылки на удалённые или изменённые источники.

Каталог не отображается как пост. Если ответ описывает каждый объект полного
набора, `context_refs` содержит все объекты, а каталог сохраняется как
служебная provenance-связь.

### Referent Resolution

Добавить версионированный результат семантического разрешения. Он является
частью `TargetContract`, а не свободным текстом в prompt:

```json
{
  "schema": "workspace.referent-resolution/v1",
  "references": [
    {
      "mention": "они",
      "target_type": "entity_set",
      "source_set_ref": "turn-1:posts",
      "target_ids": ["post:1", "post:2", "post:3"],
      "selection_mode": "all",
      "interpretation": "посты из предыдущего полного списка",
      "confidence": 0.94
    }
  ],
  "unresolved": [],
  "ambiguity": null
}
```

LLM может выбрать только из candidate refs, переданных приложением. Она не
может придумать новый ID, расширить tenant scope или заменить resolved target
новым semantic search.

### Полное множество и подмножество

Для запроса, который относится не ко всем объектам, сохраняются оба уровня:

```json
{
  "source_set_ref": "turn-1:posts",
  "selection": {
    "mode": "explicit_subset",
    "selected_ids": ["post:2", "post:4"],
    "interpretation": "второй и четвёртый посты",
    "confidence": 0.99
  }
}
```

Поддерживаемые режимы:

- `all` — все члены авторитетного набора;
- `explicit_subset` — позиции, конкретные ID или явно выделенные объекты;
- `predicate` — например, посты про ИИ; карточки проверяются только внутри
  исходного набора;
- `complement` — «остальные», то есть `source_set - selected_targets`;
- `ambiguous` — недостаточно данных, нужен уточняющий вопрос.

`coverage` в target contract описывает проверку исходного множества. Выбор
подмножества не должен превращать полный каталог в top-k поиск по workspace.

## Этапы реализации

### Этап 0. Baseline и наблюдаемость

**Задача:** зафиксировать текущее поведение до изменений.

1. Сохранить trace проблемного чата `7a0a9cd1-4550-4016-bb53-448a2fdb840d`
   как regression fixture без пользовательского сырого контента в открытом
   репозитории.
2. Для каждого run измерять:
   - `considered_evidence_count`;
   - `cited_evidence_count`;
   - `context_ref_count`;
   - `target_set_size` и `selected_target_size`;
   - `unresolved_reference_count`;
   - `resolver_confidence`;
   - planner calls, tool calls и latency p50/p95.
3. Добавить deterministic graders:
   - `claims ⊆ verified EvidencePack`;
   - `context_refs ⊆ supplied context`;
   - `target_ids` принадлежат candidate envelope;
   - `complete` проверяет весь зафиксированный каталог;
   - exhausted/partial содержит незакрытые ID.

**Точки:** `backend/tests/`, `agent_events`, существующие graders и trace
endpoint.

**Выход:** текущие failures воспроизводимы, а новая функциональность ещё не
включена глобально.

### Этап 1. Message manifest на backend

**Задача:** сделать связь «сообщение → использованные объекты» durable.

1. Добавить backend-модель/таблицу `dialog_message_context` с полями:
   - `message_id`, `run_id`, `user_id`, `ledger_key`;
   - `manifest_schema`, `manifest` JSONB;
   - `created_at`, `source_revision_digest`;
   - уникальность по `(user_id, ledger_key, message_id)`.
2. Добавить server-generated `assistant_message_id` в `AgentRun` либо закрепить
   эквивалентный one-to-one ID contract. Вернуть этот ID из `startAgentRun`,
   чтобы frontend создал streaming placeholder с тем же ID. Не связывать
   manifest с сообщением через «последнее видимое AI-сообщение».
3. Не дублировать весь объект workspace: в manifest хранить typed refs,
   revision, title/label, provenance и hash артефакта.
4. Сохранять manifest в той же транзакции, где фиксируются финальный answer
   event и завершённый `AgentRun.snapshot`.
5. Передавать manifest также в snapshot, чтобы resume и replay не зависели от
   клиентского состояния.
6. Расширить `build_snapshot_from_evidence_records()` так, чтобы он:
   - сохранял `semantic_card` с provenance на исходный post/note;
   - не путал `catalog` с пользовательским объектом;
   - сохранял notes/attachments, включая вложенные в пост;
   - создавал стабильный hash для assistant artifact.
7. Ввести `provenance=exact|inferred|legacy`.

**Точки:**

- `backend/app/db/models.py`;
- новая additive migration после `024_semantic_discovery_cards.py`;
- `backend/app/services/agent/runtime/executor.py`;
- `backend/app/services/ai/rag_dialog_ledger.py`;
- `backend/app/services/agent/research/evidence_pack.py`;
- `backend/app/services/agent/runtime/graders.py`.

Для старых history-записей, где невозможно узнать фактически использованные
материалы, manifest не реконструировать задним числом как точный. Их пометить
`legacy/inferred`.

### Этап 2. Строгая семантика финального ответа

**Задача:** строить вложения из проверенного результата, а не из всего
retrieval.

1. Расширить `workspace.answer/v1` полем `used_context_refs` только для
   объектов/артефактов, которые модель считает использованными.
2. Каноническим доказательством оставить `claims[].evidence_ids`.
3. После генерации проверить:
   - каждый claim evidence ID существует в verified pack;
   - каждый `used_context_ref` присутствует в supplied context;
   - semantic card используется только для `topic_only`/purpose claims;
   - exact/content claims требуют `full_text`;
   - ссылка принадлежит текущему tenant и разрешённому source scope.
4. Вывести manifest детерминированно:
   - claim-support refs из validated claims;
   - target refs для объектов, над которыми выполнялась операция;
   - artifact refs для редактируемого/созданного материала.
5. Если модель указала неподдержанную ссылку, удалить её из результата и
   записать validation issue; не принимать её молча.

**Точки:** `backend/app/services/agent/runtime/workspace_graph.py`,
`backend/app/services/agent/runtime/answer_stream.py`,
`backend/app/services/agent/runtime/graders.py`,
`backend/app/services/agent/research/evidence_pack.py`.

### Этап 3. Подключение manifest к chat history и API

**Задача:** сделать ссылки доступными следующему ходу и клиенту.

1. Расширить схему `ChatMessage` в
   `frontend/src/shared/api/schemas/post.ts` полями:
   - `messageId`;
   - `contextRefs`;
   - `citedEvidence`;
   - `artifacts`;
   - `staleRefs`;
   - `contextProvenance`.
2. Сохранять message-level metadata вместе с history entry для global chat и
   post chat, но authoritative copy держать на backend в manifest table.
3. Использовать `assistant_message_id` из ответа `startAgentRun` при создании и
   всех последующих обновлениях streaming message. Fallback на «последнее
   сообщение» оставить только для legacy history без IDs.
4. Расширить финальный SSE `answer` payload manifest или ссылкой на него.
5. После завершения stream frontend должен записывать answer text и manifest в
   одну видимую историю, как сейчас proposal state записывается через
   `patchGlobalChatHistory`/`patchPostChatHistory`.
6. Добавить API для получения manifest по message/run с ownership check.
7. В `ChatAiMessage` отрисовать компактный список кликабельных source chips:
   - post/note открывают существующий объектный маршрут;
   - artifact открывает сообщение/черновик;
   - stale ref показывает недоступность текущей версии;
   - технические UUID не показываются.

**Точки:**

- `backend/app/api/v1/agent_runs.py`;
- `backend/app/services/agent/runtime/events.py`;
- `frontend/src/shared/api/schemas/agentRun.ts`;
- `frontend/src/shared/api/agentRuns.ts`;
- `frontend/src/shared/api/schemas/post.ts`;
- `frontend/src/app/model/store/composer-store.tsx`;
- `frontend/src/app/model/store/agent-run-store.ts`;
- `frontend/src/widgets/chat-thread/ui/ChatAiMessage.tsx`.

### Этап 4. Семантическое разрешение референтов

**Задача:** заменить словарное gate-условие полноценным bounded semantic
решением.

1. До финализации `TargetContract` собрать candidate envelope только из:
   - manifests последних сообщений;
   - `entity_set` и entities dialog ledger;
   - target contract предыдущего хода;
   - текущего открытого объекта;
   - артефактов предыдущих ответов;
   - при необходимости — авторитетного каталога текущего source.
2. Для каждого кандидата передать только стабильный ref, тип, title, позицию,
   provenance, source turn, revision и короткую summary. Полный текст читать
   после выбора, а не для определения ID.
3. Встроить разрешение в уже существующий planner/classifier contract, когда
   это возможно. Не добавлять LLM-вызов на каждый обычный запрос.
4. Для явных ID, открытого поста и единственного однозначного кандидата
   использовать быстрый deterministic path.
5. Для анафоры, эллипсиса и выбора подмножества запрашивать structured
   `workspace.referent-resolution/v1`.
6. Подавать resolver'у:
   - текущий user text;
   - bounded recent dialogue и rolling summary;
   - manifests предыдущих ответов;
   - роли объектов: answer-to-question, selected subset, artifact being edited,
     comparison pair;
   - порядок и состав entity sets.
7. Валидировать результат кодом: tenant, type, existence, revision, source turn,
   allowed scope и отсутствие invented IDs.
8. При низкой уверенности или равных наборах вернуть один clarification
   question, не запускать retrieval.

Словари/regex остаются только оптимизацией для очевидных explicit cases. Они не
могут быть условием того, будет ли рассмотрен семантический referent resolver.

**Точки:**

- `backend/app/services/agent/runtime/turn_contract.py`;
- `backend/app/services/agent/runtime/workspace_graph.py`;
- `backend/app/services/ai/rag_dialog_ledger.py`;
- `backend/app/services/agent/runtime/state.py`;
- `backend/app/services/agent/runtime/runs.py`.

### Этап 5. Интеграция resolved target с retrieval

**Задача:** сделать resolved refs авторитетной областью исследования.

1. При `source_set_ref` сохранить исходный конечный набор и selection.
2. Для `all` использовать полный список ID из каталога.
3. Для `explicit_subset` читать только selected IDs.
4. Для `predicate` сначала проверить cards всех членов исходного набора, затем
   deep-read только выбранные объекты.
5. Для `complement` вычислять разность исходного набора и уже выбранных IDs;
   workspace semantic search не запускать.
6. Для complete-контракта sufficiency проверяет каждый обязательный ID
   каталога, а не количество совпадений.
7. Семантические карточки загружать exact-by-ID; отсутствующие/stale cards
   повышать до `OpenPost`/`OpenNote` по тому же ID.
8. После revision change revalidate и перечитать источник; при удалении
   сохранить `stale_ref` и объяснить недоступность.
9. Не считать служебный catalog отдельным пользовательским объектом в ответе и
   `context_refs`.

**Точки:**

- `backend/app/services/agent/research/graph.py`;
- `backend/app/services/agent/research/prefetch.py`;
- `backend/app/services/agent/research/material_plan.py`;
- `backend/app/services/agent/research/sufficiency.py`;
- `backend/app/services/agent/research/evidence_pack.py`;
- `backend/app/services/ai/rag_tools.py`.

### Этап 6. Bounded execution и отсутствие циклов

**Инварианты исполнения:**

- максимум один semantic resolver/planner interpretation на пользовательский
  ход;
- максимум один bounded research path после target resolution;
- batch full reads остаётся не более трёх параллельных действий;
- общий tool budget, planner-call budget и hard deadline остаются обязательными;
- повтор dispatcher допустим только для оставшихся известных pending IDs;
- повторный planner нужен только при настоящем semantic gap, а не для поиска
  новых similarity hits;
- после исчерпания бюджета состояние `partial/exhausted` содержит unresolved
  IDs и причину;
- clarification — это terminal outcome текущего хода, новый поиск начинается
  только после нового сообщения пользователя.

Цикл может выглядеть так:

```text
planner/resolve
  -> known catalog or resolved target set
  -> exact card/full-text batches
  -> sufficiency
  -> ready | partial/exhausted | clarification
```

Он конечен, потому что каждый проход уменьшает множество известных pending IDs.
Никакая ветка не может добавить в него новый объект из semantic top-k.

### Этап 7. Latency и стоимость

Целевой latency policy:

| Путь | Дополнительная работа |
|---|---|
| Новый вопрос без ссылок | нет дополнительного resolver-вызова |
| Явный ID/open object | deterministic CPU path |
| Анафорический или эллиптический follow-up | один bounded structured planner/resolver этап |
| Полный обзор | exact cards/full reads для зафиксированного набора |
| Manifest persistence | одна bounded DB запись/транзакция |
| UI attachment rendering | клиентская отрисовка уже полученных refs |

Чтобы не ухудшить p95 без необходимости:

- объединить referent resolution с уже существующим planner вызовом;
- передавать компактные manifests, а не полные тексты;
- пропускать LLM для deterministic exact paths;
- кэшировать resolution по hash `(user_text, candidate_manifest, revision_digest)`;
- повторно использовать exact refs предыдущего manifest;
- сначала использовать свежие semantic cards, а full text читать только по
  `evidence_granularity` и claims.

Снять до и после реализации p50/p95/p99 отдельно для bootstrap, resolver,
retrieval, answer generation, DB persistence и total time-to-final. Не считать
оценочные значения fixture benchmark производственным SLO.

### Этап 8. Тесты и golden cases

#### Backend unit/integration

- manifest строится только из validated claims/context refs;
- catalog не превращается в пользовательский объект;
- semantic card получает provenance на post/note;
- exact claim на одной semantic card отклоняется или повышается до full text;
- tenant/ownership и revision проверяются на каждой границе;
- старый manifest имеет `legacy/inferred` provenance;
- `all` закрывает весь каталог из пяти IDs;
- missing cards открываются по известным IDs, без нового search;
- budget exhaustion возвращает unresolved IDs;
- resolver не может вернуть invented ID;
- равные кандидаты приводят к clarification.

#### Referent golden set

- «Про что они?» после entity set из пяти постов;
- «Про что каждый из тех постов?»;
- «Первые два»;
- «Второй и четвёртый»;
- «Посты про ИИ» внутри исходной пятёрки;
- «Кроме приветственного»;
- «А теперь остальные»;
- «Сделай его короче» для предыдущего assistant artifact;
- «Сравни это с предыдущим»;
- implicit follow-up без явного местоимения;
- две равноправные entity sets и обязательное уточнение;
- source changed/deleted between turns;
- branch/history switch does not leak refs.

#### Frontend

- schema accepts/rejects manifest versions correctly;
- assistant message displays source chips in its own turn;
- click opens post/note/artifact;
- stale refs render an explicit unavailable state;
- reload preserves attachments;
- streaming answer gets final manifest after completion;
- proposal/artifact metadata remains attached to the correct message.

Проблемный чат `7a0a9cd1-4550-4016-bb53-448a2fdb840d` использовать как
регрессионный сценарий: первый ответ создаёт пять post refs, следующие ссылки
разрешаются в этот набор или его явное подмножество, а новый top-k search его не
подменяет.

### Этап 9. Rollout

Добавить независимые feature flags:

- `DIALOG_MESSAGE_CONTEXT_MANIFEST_V1`;
- `SEMANTIC_REFERENT_RESOLUTION_V1`.

`AGENT_ADAPTIVE_EVIDENCE_DEPTH_V1_ENABLED=1` оставить включённым отдельно: он
отвечает за глубину и полноту evidence, а не за message references.

Порядок rollout:

1. schema/migration и запись manifest в shadow mode;
2. trace comparison old/new без изменения ответа;
3. resolver для explicit deterministic paths;
4. resolver для semantic/elliptical follow-ups на canary;
5. API/frontend attachments;
6. включение strict target binding и запрет silent semantic fallback;
7. удаление compatibility paths только после replay и green regression gate.

Метрики canary:

- target resolution accuracy;
- exact vs inferred manifest rate;
- unresolved/clarification rate;
- invented/invalid ref rate (должен быть ноль);
- complete coverage rate;
- grounded claims rate;
- p50/p95 total latency и resolver latency;
- количество planner/research повторов;
- stale-reference rate.

## Definition of Done

Работа считается завершённой, когда одновременно выполнены условия:

1. Новое сообщение ассистента имеет durable message context manifest.
2. Вложенными считаются только проверенные объекты/артефакты, а не весь
   доступный EvidencePack.
3. Пользователь может открыть прикреплённый post/note/artifact из сообщения.
4. Следующий ход получает manifest и ledger как candidate context.
5. Анафора и эллипсис разрешаются семантически по конечному графу кандидатов,
   а словари не являются основным механизмом.
6. Подмножество исходного набора поддерживается отдельно от полного множества.
7. Complete закрывает конечный каталог ID; similarity search не расширяет его.
8. Missing/stale evidence приводит к exact re-read или явному partial/stale
   результату.
9. Низкая уверенность приводит к одному уточняющему вопросу, а не к циклу.
10. Ownership, tenant, type и revision проверяются до использования refs.
11. Golden/regression suite для проблемного чата зелёный.
12. p95 latency и token/tool budgets не выходят за согласованные SLO.
