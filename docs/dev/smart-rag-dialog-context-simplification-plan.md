# План: упрощение диалогового контекста и возврат к Smart RAG

## Решение

Агентная система остаётся умным RAG:

```text
текущий запрос + диалог + компактные материалы прошлых ответов
        -> planner решает, нужен ли поиск
        -> existing research/tools
        -> EvidencePack
        -> финальная генерация
```

Агент не разрешает русские анафоры и не назначает DB-объектом то, что
пользователь мог иметь в виду только в тексте предыдущего ответа.

Связь между текущей фразой и диалогом понимают planner и финальная LLM.
Код проверяет только реальные последствия: доступность источника, revision,
tenant, ownership и параметры конкретного tool call.

Этот документ supersede-ит для обычного read/generate-пути план
`dialog-context-manifest-and-semantic-references-plan.md`. Часть его идей
остаётся полезной для provenance, freshness и EvidencePack, но отдельный
semantic referent resolver больше не является целевой архитектурой.

## Корень проблемы

В текущем runtime смешаны четыре разных уровня:

1. Текст сообщения ассистента, где может находиться предложенная тема, которой
   нет в БД.
2. Источники, реально использованные для подготовки этого сообщения.
3. Внутренние discovery cards, search hits, catalog и planner transcript.
4. DB-объект, над которым разрешено выполнить tool call.

`TargetContract`, словари анафор и `candidate_envelope` пытались заранее
превратить уровни 1-3 в уровень 4. Поэтому в чате `ff37a126-e2f2-4157-aa03-a3cedefae7f5`
пять источников из EvidencePack стали равноправными кандидатами на значение
«этого поста», а уточнение «Какой именно объект использовать?» позднее было
сохранено как `post_draft`.

Корневое исправление — не расширять словарь анафор, а убрать саму обязанность
кода разрешать анафору до LLM.

## Что сохраняем без изменений

### Research и EvidencePack

Выбранные semantic cards уже гидратируются до авторитетных `post_text` и
`note_chunk` в
`backend/app/services/agent/research/graph.py:_hydrate_selected_semantic_cards`.

Финальная модель уже получает full text через
`backend/app/services/agent/runtime/workspace_graph.py:_render_verified_pack`.
Это сохраняется. Финальному ответу нужны full text для точных фактов, цитат,
сравнений и написания поста.

### `used_context_refs`

Финальная модель уже возвращает `used_context_refs`, а
`validate_answer_output` ограничивает их источниками, реально переданными в
EvidencePack. Это остаётся источником истины для материалов конкретного
ответа.

### `message_context_manifest`

Новый schema создавать не нужно. Текущий
`workspace.message-context/v1` уже содержит подходящие поля:

- `context_refs` — использованные пользовательские источники;
- `considered_context` — внутренняя информация о переданном EvidencePack;
- `artifacts` — provenance самого ответа ассистента;
- `stale_refs` — недоступные или изменившиеся источники.

Меняется роль этих полей, а не общий формат.

## Целевой контракт контекста

### Внутренний EvidencePack текущего хода

Передаётся финальной модели как сейчас:

```text
EvidencePack item:
  id: внутренний evidence id
  citation_path
  title
  content: full text
  source_ref
  fidelity: full_text
  evidence_role
  provenance/revision
```

### Материалы сообщения

Сохраняются в `message_context_manifest.context_refs` только источники,
которые финальная модель указала в `used_context_refs`:

```json
{
  "ref": "note:4935205",
  "kind": "note",
  "title": "Интерактивные возможности",
  "summary": "Короткая semantic card этой заметки",
  "revision": 12,
  "source_turn_id": "run-id",
  "role": "used_context",
  "provenance": "exact",
  "route": "/note/global/4935205/"
}
```

`ref` обязательно содержит реальный ID. `context_refs` не являются target,
не являются порядком выбора и не означают, что пользователь говорит именно об
одном из них.

### Текст будущего диалога

Planner и финальная генерация получают общий компактный блок:

```text
Диалог:
Пользователь: Про что написать следующий пост?
Ассистент: Следующий пост стоит написать про каскадный обход пространства...

Материалы, использованные при подготовке предыдущего ответа:
- note:4935205 — Интерактивные возможности — Короткая semantic card
- note:0489593 — Серия постов — Короткая semantic card
- post:5490950 — Название поста — Короткая semantic card

Текущий запрос:
Напиши мне текст этого поста
```

В блок не добавляются `TargetContract`, `target`, `candidate_ids`,
`referent_resolution`, `reference_sets` и внутренний planner transcript.

## Изменения по этапам

### Этап 0. Зафиксировать инварианты и включить наблюдение

Перед изменениями добавить/уточнить метрики и trace-поля:

- route: `finish`, `read`, `reuse_context`, `tool_call`;
- число новых SearchNodes/SearchObjectChunks;
- число повторно открытых известных refs;
- количество `used_context_refs`;
- fidelity финального EvidencePack;
- количество clarification и старых resolver-срабатываний;
- mismatch между источниками EvidencePack и message context.

Добавить feature flags с безопасным rollback:

- `agent_dialog_context_v2` — общий контекст диалога и карточек;
- `agent_referent_resolution_legacy` — временное включение старого resolver;
- `agent_finish_without_research` — прямой finish-путь.

Новые флаги сначала включаются только для golden fixtures и проблемного чата.

### Этап 1. Исправить message context, не меняя agent handoff

Точка: `backend/app/services/agent/runtime/message_context.py`.

1. Вынести выбор отображаемого summary в маленькую локальную функцию:

   ```text
   metadata.card_text
   -> metadata.preview
   -> item.content[:240]
   ```

2. Не брать summary из full text, если в metadata доступна исходная card.
3. Сохранять `ref`, `kind`, `title`, `revision`, `route`.
4. Оставлять в `context_refs` только `used_context_refs` и валидные claim refs.
5. Если финальный ответ цитирует authoritative catalog, разворачивать его
   структурированные `members` в карточки реальных post/note объектов.
6. Не создавать `context_refs` для внутренних discovery hits, которые не вошли
   в финальный использованный набор.
7. Оставить `considered_context` внутренним provenance-полем; UI и следующий
   диалоговый контекст не должны использовать его как список объектов.
8. Оставить `artifacts` как hash ответа для внутренней provenance, но не
   показывать его как источник и не использовать для выбора DB-объекта.

Тесты:

- hydrated full text остаётся в EvidencePack;
- manifest summary берётся из `metadata.card_text`;
- manifest содержит реальный `note:id`/`post:id`;
- invented `used_context_refs` отбрасываются;
- catalog не становится отдельной карточкой.

### Этап 2. Оставить карточки внутренним контекстом AI

Точка: `frontend/src/widgets/chat-thread/ui/ChatAiMessage.tsx`.

1. Не показывать `context_refs`, `considered_context`, `artifacts` и `stale_refs`
   под сообщением ассистента.
2. Сохранять эти поля в сообщении и manifest как внутренний контекст следующих
   AI-ходов и для provenance/диагностики.
3. Не превращать внутренние материалы в кнопки, ссылки или action proposal.
4. `route` можно сохранять для внутренних инструментов, но обычный chat UI его
   не отображает.

### Этап 3. Собрать общий контекст для planner и final

Точки:

- `backend/app/services/ai/rag_query.py:build_planner_dialog_context`;
- `backend/app/services/agent/runtime/runs.py`;
- `backend/app/services/agent/runtime/context.py`;
- `backend/app/services/agent/runtime/workspace_graph.py`.

1. Загрузить recent message manifests как сейчас, но использовать только
   `context_refs` с ролями `used_context`/`claim_support`.
2. Добавить компактные карточки к тому же `dialog_context`, где уже находится
   история сообщений.
3. Не передавать полные тексты прошлых источников в planner.
4. Ограничить число ходов, карточек и символов существующими bounded-бюджетами.
5. Передавать один сериализованный базовый блок и planner, и final. Отличаться
   должны только инструкции и EvidencePack текущего хода.
6. Не включать в этот блок TargetContract и referent-resolution.

Проверка:

- planner prompt содержит предыдущий ответ и карточки;
- final prompt содержит тот же блок плюс текущий full-text EvidencePack;
- карточки не становятся инструкциями и не помечаются как «целевой объект».

### Этап 4. Отключить semantic resolver для read/generate

Точки:

- `backend/app/services/agent/runtime/runs.py`;
- `backend/app/services/agent/runtime/turn_contract.py`;
- `backend/app/services/agent/runtime/referent_resolution.py`;
- `backend/app/services/agent/runtime/workspace_graph.py`.

1. Для обычных answer/write/read ходов перестать передавать manifests и ledger
   в `build_turn_contract` для разрешения референтов.
2. Отключить `semantic_referent_enabled` в этом пути.
3. Убрать из критического пути `_POST_REFERENT_RE`, `_NOTE_REFERENT_RE`,
   `_is_referential_text` и списки follow-up слов.
4. Не создавать `dialog_artifact` для текста предыдущего ответа.
5. Не использовать `candidate_envelope` и `resolve_from_candidates` для
   обычного ответа.
6. Удалить/свести `TargetContract` до совместимости в snapshot, чтобы старые
   runs могли читаться, но новый read/generate путь не зависел от него.
7. Сохранить явные ID и open object только как данные конкретного tool call.

На этом этапе старый код не удалять физически. Сначала выключить его флагом,
проверить golden cases, затем удалить мёртвые ветки и resolver-specific tests.

### Этап 5. Разрешить planner выбирать finish без research

Сейчас `route_workspace_call()` всегда ведёт в `seed`, а V2 слишком широко
выставляет `requires_workspace`.

Изменить orchestration policy:

```text
planner type=finish -> answer
planner type=read   -> seed -> planner/tools -> pack -> answer
```

1. Не считать workspace обязательным для каждого обычного V2-хода.
2. Для follow-up, на который хватает диалога и ранее использованных материалов,
   разрешить `finish`.
3. Для фактического вопроса, поиска, подсчёта и новой информации оставить
   существующий read/research path.
4. Сохранить текущие budget/deadline/verification gates для read.
5. Не заставлять planner возвращать `search_query`, если он выбрал finish.

Для `ff37...` ожидаемый маршрут:

```text
Про что написать следующий пост?
  -> existing research
  -> answer + used_context_refs

Напиши мне текст этого поста
  -> planner видит текст ответа + карточки
  -> finish или reuse_context
  -> без clarification
  -> финальная модель пишет текст темы
```

### Этап 6. Добавить reuse известных источников без semantic search

Карточки с ID сами по себе не содержат full text. Если новый запрос требует
деталей уже использованных источников:

1. Planner видит карточки и понимает, что источники уже доступны.
2. Он выбирает reuse/read-known-context, а не semantic search.
3. Агент открывает известные `note:id`/`post:id` exact-by-ID существующими
   `OpenNote`/`OpenPost` или эквивалентным reader path.
4. Открытые записи проходят обычную revision/ownership проверку.
5. Они попадают в обычный EvidencePack и снова гидратируются до full text для
   final.

Это не отдельный resolver и не target graph. Это повторное использование
проверенных источников по уже сохраненному provenance.

Если source revision устарела или объект удалён, записать `stale_ref` и не
подменять источник semantic top-k результатом.

### Этап 7. Освободить ledger от роли дискурсивного resolver

`dialog_evidence_turns` можно сохранить для provenance, attachment replay и
диагностики, но он больше не должен решать «что означает этот пост».

1. Сохранять реальные post/note/attachment evidence.
2. Не использовать `assistant_answer` как target-кандидата.
3. Не классифицировать clarification «Какой именно объект использовать?» как
   `post_draft` для будущего хода.
4. В новых turns хранить текст ответа в history, а источники — в
   `message_context_manifest.context_refs`.
5. Старые ledger rows не переписывать; новый runtime просто не использует их
   для referent resolution.

### Этап 8. Удалить старые контракты после canary

После прохождения тестов и проблемного чата:

1. Удалить feature flag legacy resolver.
2. Удалить semantic referent settings и resolver-only поля из нового пути.
3. Удалить regex/словарные тесты, которые проверяют языковую интерпретацию.
4. Оставить тесты на явные ссылки, tool-call ID, ownership и revision.
5. Обновить `docs/dev/README.md` и пометить старый semantic-reference plan как
   superseded.

## Тестовая матрица

### Контекст и handoff

- selected semantic card превращается в full text для final;
- исходный `card_text` сохраняется в message card;
- manifest содержит только `used_context_refs`;
- каждый ref содержит настоящий ID;
- full text не попадает в UI карточку;
- UI не показывает assistant answer hash как источник.

### Диалог

- `ff37...`: тема предыдущего ответа не заменяется постом «апвап»;
- предыдущий ответ может описывать тему, которой нет в БД;
- `Напиши мне текст этого поста` использует текст предыдущего ответа и
  материалы, а не случайный attached post;
- clarification не становится следующим `post_draft`;
- `Сделай короче`, `Перепиши`, «на другом тоне» не запускают новый поиск;
- `Найди другой пост` остаётся обычным поиском с диалогом, без target resolver;
- явный `/post/{id}` открывается по ID и проходит проверки.

### Research и безопасность

- read-путь не теряет существующие planner/tool/sufficiency gates;
- reuse известных refs не создаёт SearchNodes;
- stale/deleted source не заменяется другим semantic hit;
- invented refs от финальной модели отбрасываются;
- tenant/ownership/revision проверяются перед каждым exact read/tool call;
- hard deadline и tool budgets продолжают работать.

## Порядок внедрения

1. Добавить метрики и feature flags.
2. Исправить summary в `context_refs` и UI-карточки с ID.
3. Добавить общий компактный dialog context для planner/final.
4. Включить его на golden fixtures без удаления старого resolver.
5. Отключить resolver для read/generate под флагом.
6. Реализовать `finish` без seed и reuse известных refs.
7. Прогнать backend unit/integration и frontend contract tests.
8. Проверить `ff37...` и сравнить traces old/new path.
9. Включить новый путь по умолчанию.
10. Удалить legacy resolver и обновить документацию.

## Критерии готовности

Работа завершена, когда:

- агент занимается поиском, открытием и упаковкой данных, а не анафорами;
- final продолжает получать full text без изменения EvidencePack handoff;
- planner и final видят один и тот же компактный диалоговый контекст;
- `message_context_manifest` содержит только использованные источники с ID,
  title, semantic summary и revision;
- обычный текст предыдущего ответа не превращается в искусственный DB object;
- найденный source не становится автоматически referent;
- follow-up `ff37...` проходит без clarification и без выбора «апвап»;
- повторное использование известных материалов не запускает semantic search;
- старые данные читаются безопасно, но не управляют новым resolver-путём;
- в обычном read/generate пути нет обязательного отдельного механизма русских
  анафор.
