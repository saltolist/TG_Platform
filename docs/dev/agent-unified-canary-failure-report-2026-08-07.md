# TG Platform: отчет по проваленным канарейкам и передача в новую сессию

Дата фиксации: 2026-08-07  
Рабочая директория: `/Users/konstantinkuznecov/TG_Platform`  
Последний прогон: аккаунтный live-прогон `v174` через UI платформы.

## Цель

Нужно довести универсальную агентную систему до прохождения всех 21 формальных сценариев. Система должна каждый раз вызывать агентный контур, но передавать в финальную генерацию только материалы, которые действительно помогают ответить на конкретный запрос:

- заметки, посты и вложения выбираются по смыслу запроса и связям между объектами;
- полный текст открывается только для отобранных объектов;
- несколько независимых частей ответа не должны схлопываться в одну широкую заметку;
- заметка о серии связывается с соответствующими постами только когда это следует из запроса и данных;
- отсутствие подходящих материалов должно приводить к пустому evidence-окну, а не к случайным последним постам/заметкам;
- финальный генератор пока не меняется: корректность контекста должна обеспечиваться агентной системой.

Нельзя решать проблему костылями под одну заметку, тип документа, конкретную формулировку запроса или `normative_value=false`. Нужна универсальная механика для каналов с разными темами, заметками, постами и вложениями.

## Конфигурация последнего прогона

Манифест: `backend/tests/fixtures/agent_unified_phase6/v174/formal_canary_manifest.json`  
Версия: `2026-08-06-account-live-v174`  
Провайдер/модель профиля: `OpenAI / gpt-4.1-mini`  
Web Search: `Нет`  

В контейнеры были переданы флаги:

```text
AGENT_UNIFIED_CATALOG_V1_ENABLED=1
AGENT_TYPED_REQUIREMENTS_V1_ENABLED=1
AGENT_UNIFIED_SELECTOR_V1_ENABLED=1
AGENT_VERIFIED_PACK_BOUNDARY_V1_ENABLED=1
AGENT_PLANNER_POLICY_V1_ENABLED=1
AGENT_UNIFIED_DEFAULT_ON=0
```

Важно: `AGENT_UNIFIED_DEFAULT_ON=0` означает, что текущий rollout включался явными флагами. При проверке новой версии нужно убедиться, что backend и celery-worker используют одну и ту же конфигурацию.

## Результаты

В последней серии повторно прогнаны все ранее проваленные сценарии, включая сценарий 4. Код сценария 4 перед этим не изменялся.

| Сценарий | Запрос | Результат | Формальная причина |
|---:|---|---|---|
| 4 | `Про что написать следующий пост?` | FAIL | Нужные посты не материализованы; выбран лишний материал; precision не вызывался |
| 8 | `Собери сквозной рабочий процесс автора: как подготовить и опубликовать пост без переключения между сервисами и какие возможности платформы это обеспечивают?` | FAIL | `precision_confirmation.schema_result=provider_error`, все подтверждения пусты |
| 9 | `Из двух вариантов поставки какой подходит для реальной работы с каналом и своими данными, и почему не второй?` | FAIL | `provider_error`, критическая заметка дематериализована |
| 10 | `Как в TG Platform связаны структура контента и действия автора внутри платформы?` | FAIL | `provider_error`, независимые заметки не подтверждены |
| 11 | `В материалах сказано, что AI знает весь канал, но при этом не загружает весь архив. Есть ли здесь противоречие и как это устроено на практике?` | FAIL | `provider_error`, нужные посты и заметка дематериализованы |
| 12 | `Какие опубликованные материалы подтверждают, что TG Platform уже обеспечивает двустороннюю работу с Telegram в едином интерфейсе?` | FAIL | `provider_error`, нужные опубликованные посты не переданы |
| 14 | `Проверь все заметки и отдели заметки со знаниями о продукте TG Platform от посторонних или тестовых материалов.` | FAIL | `provider_error`, полный inventory заметок потерян |
| 15 | `Сопоставь план серии постов с уже опубликованными материалами: какие запланированные темы уже раскрыты и какими постами?` | FAIL | `provider_error`, заметка серии и посты не переданы |
| 16 | `За счёт какого механизма AI в TG Platform уже знает канал, но не переносит весь архив в каждый запрос?` | FAIL | `provider_error`, критический пост не передан |
| 17 | `Что потеряет автор, если убрать единый кабинет и двустороннюю связь с Telegram, даже если Agentic RAG и база знаний останутся?` | FAIL | `provider_error`, нужные посты не переданы |
| 18 | `Составь краткий маршрут знакомства с TG Platform: от выбора рабочего контура и развёртывания до понимания интерфейса и пространственной модели.` | FAIL | `provider_error`, заметки о поставке и интерактивной системе потеряны |
| 19 | `Entre la démo GitHub Pages et le produit Docker, laquelle faut-il choisir pour travailler réellement avec sa chaîne et ses données, et pourquoi?` | FAIL | `provider_error`, критическая заметка не передана |
| 20 | `Map the creator's main workflow problems to the TG Platform mechanisms that solve them: context retrieval, one workspace, and Telegram synchronization.` | FAIL | `provider_error`, нужные посты и заметка не переданы |
| 21 | `Сформулируй архитектурный тезис TG Platform: как иерархия знаний, интерактивное пространство, агенты, каскадный поиск и двусторонняя связь складываются в одну систему?` | FAIL | `provider_error`, критические заметки/пост не переданы |

Итог повторной серии: **0/14** прошли (`4, 8-12, 14-21`).

Сценарии `1, 2, 3, 5, 6, 7, 13` не входят в этот повторный набор. По предыдущей промежуточной проверке были отмечены успешными `3` и `6`; это не заменяет новый полный immutable-прогон всех 21 сценариев после исправления.

### Полный gate из 21 сценария

Это рабочая матрица для следующей сессии. Статус `не обновлялся` означает, что сценарий не был частью последней серии `4, 8-12, 14-21`; его нужно включить в финальный полный прогон.

| № | Тип сценария из манифеста | Статус этой фиксации |
|---:|---|---|
| 1 | `delivery_contours` | не обновлялся |
| 2 | `root_object_taxonomy` | не обновлялся |
| 3 | `interface_zone_inventory` | ранее был PASS, повторить в полном прогоне |
| 4 | `implicit_next_artifact_planning` | FAIL, отдельный костыль запрещен |
| 5 | `feature_inventory` | не обновлялся |
| 6 | `general_advice_without_workspace_evidence` | ранее был PASS, повторить в полном прогоне |
| 7 | `system_layer_taxonomy` | не обновлялся |
| 8 | `implied_workflow_synthesis` | FAIL, `provider_error` |
| 9 | `anaphoric_contour_choice` | FAIL, `provider_error` |
| 10 | `cross_object_inference` | FAIL, `provider_error` |
| 11 | `apparent_contradiction_resolution` | FAIL, `provider_error` |
| 12 | `implicit_capability_evidence` | FAIL, `provider_error` |
| 13 | `near_topic_due_diligence` | не обновлялся |
| 14 | `complete_product_knowledge_classification` | FAIL, `provider_error` |
| 15 | `plan_vs_published_audit` | FAIL, `provider_error` |
| 16 | `implied_claim_mechanism` | FAIL, `provider_error` |
| 17 | `counterfactual_dependency_analysis` | FAIL, `provider_error` |
| 18 | `evidence_grounded_onboarding` | FAIL, `provider_error` |
| 19 | `multilingual_anaphoric_choice` | FAIL, `provider_error` |
| 20 | `multilingual_problem_mapping` | FAIL, `provider_error` |
| 21 | `implicit_architecture_thesis` | FAIL, `provider_error` |

## Что видно в трассировке

Для сценариев `8-21` картина практически одинаковая:

1. Кандидаты находятся: обычно `candidate_count` равен 8-11.
2. Первый selector-вызов имеет валидную схему (`schema_result=valid`), либо валидной является последующая evidence reassessment.
3. Precision confirmation вызывается и получает список первично выбранных кандидатов.
4. В trace появляется:

```json
{
  "precision_confirmation": {
    "called": true,
    "schema_result": "provider_error",
    "confirmed_refs": [],
    "demoted_refs": "all primary selected refs",
    "generated_obligation_mode": true
  }
}
```

5. После этого все выбранные материалы переводятся в `irrelevant/none`, evidence pack становится пустым, а финальный ответ сообщает, что данных нет. Это объясняет ответы UI вида «в рабочем пространстве отсутствует конкретная информация», хотя кандидаты и полные тексты до этого были доступны.

Для сценария 21 в `agent_events` подтверждено:

- `bootstrap.classifier`: OpenAI `gpt-4.1-mini`, success;
- `research.selector.context`: success, schema valid;
- `research.selector.context_evidence_reassessment`: success, schema valid;
- precision trace: `generated_obligation_mode=true`, `decision_obligations=[]`, `confirmed_refs=[]`, `schema_result=provider_error`;
- финальный ответ сгенерирован с `evidence_ids=[]` и `partial=true`.

## Уже внесенные изменения

Текущий dirty worktree содержит большую серию изменений предыдущих итераций. Основные относящиеся к этой проблеме идеи находятся в:

- `backend/app/services/agent/research/graph.py`
- `backend/app/services/agent/research/material_plan.py`
- `backend/app/services/agent/research/selector_transport.py`
- `backend/app/services/agent/research/evidence.py`
- `backend/app/services/ai/semantic_chunking.py`
- `backend/tests/test_agent_unified_phase2_contract.py`
- `backend/tests/test_agent_unified_phase3_selector.py`

В `graph.py` были добавлены:

- generated atomic-obligation mode: precision-модель может разложить широкий запрос на source-neutral obligations с координатами `position:unit`;
- member-classification mode для inventory-запросов, чтобы каждый документ корпуса мог удерживаться отдельно;
- сохранение legacy mapping output для старых контрактов.

Фокусированные тесты до live-прогона проходили:

- `tests/test_agent_unified_phase2_contract.py`: `42 passed`;
- `tests/test_agent_unified_phase3_selector.py`: `120 passed, 1 deselected`;
- новые targeted-тесты для generated obligations/member classification: `4 passed`;
- `py_compile` для `research/graph.py`: успешно.

Эти результаты проверяют локальные контракты, но не доказывают прохождение live-канареек.

## Наиболее вероятные корневые причины

Это гипотезы для проверки, а не окончательный диагноз.

### 1. Ошибка precision-провайдера скрывается

В `_run_precision_confirmation` broad `except Exception` преобразует любую ошибку в `schema_result=provider_error` и вызывает `reject_unconfirmed()`. Исходный тип исключения, HTTP-код, тело ответа и имя проблемного поля не попадают в trace.

Первый шаг новой сессии: добавить безопасное структурированное наблюдение (`exception_type`, sanitized message, provider status/request id, transport tier, schema name), не записывая API-ключи и содержимое приватных материалов.

Нужно различать:

- provider/API error;
- unsupported structured-output schema;
- timeout/deadline;
- invalid JSON/transport;
- decode/semantic validation error.

### 2. Generated-obligation schema слишком строгая или несовместима с транспортом

В режиме `generated_obligation_mode` schema требует одновременно:

- полный набор `g`-ворот для каждой позиции;
- строгие ключи `v,n,r,g,o,b,k,done`;
- массив `o` из 1-12 obligations;
- точные координаты `position:unit`;
- валидные relation/value/member warrants.

У одного кандидата могут быть десятки единиц (в сценарии 21 registry unit counts включали `63`), поэтому prompt и structured schema становятся тяжелыми. Возможна ошибка провайдера при отправке/обработке JSON Schema или ответ, который транспорт принимает, но decoder отвергает.

Нужно воспроизвести тот же payload в focused-тесте и проверить отдельно structured и plain transport. Не следует сразу ослаблять проверку вслепую.

### 3. Семантическая ошибка при пустом precision-ответе

Сейчас любая ошибка precision приводит к демотированию всех первично выбранных материалов. Это безопасно против лишнего контекста, но превращает временную ошибку провайдера в гарантированную потерю recall.

Универсальный fallback должен быть ограниченным: если первичный selector валиден, provenance проверен и нет irrelevant/position/security violation, временный provider error precision не должен уничтожать уже валидный selected subset. Нужно явно пометить precision как degraded/skipped и сохранить проверенный baseline. Если baseline сам невалиден, материалы сохранять нельзя.

Такой fallback не должен:

- добавлять случайные последние посты;
- обходить tenant/provenance boundary;
- превращать semantic card в full text без открытия;
- скрывать реальную ошибку в telemetry.

### 4. Broad obligations все еще могут схлопываться

Даже после добавления generated obligations часть classifier contracts формулирует широкую обязанность вроде общего «архитектурного тезиса». Нужно проверить, что precision действительно сохраняет несколько независимых premises, а не выбирает одну широкую заметку. Для сценариев 10, 14, 15, 17-21 это критично.

### 5. Inventory и cross-record запросы требуют распределенного покрытия

Для «проверь все заметки», «сопоставь план серии с постами» и аналогичных запросов один документ не должен считаться достаточным доказательством всей коллекции. Member classification должен работать только при наличии typed complete/member requirement, а не включаться для каждого обычного запроса.

### 6. Контракт конфигурации модели нужно проверить

Манифест live-прогона использует `OpenAI/gpt-4.1-mini`. Нельзя незаметно откатиться на DeepSeek или другой профильный ключ. Нужно подтвердить внутри backend и worker effective provider/model и убедиться, что selector, precision и final answer используют ожидаемые настройки профиля пользователя.

## Требования к исправлению

Исправление считается приемлемым только если оно универсально:

- агентный вызов присутствует всегда;
- материалы могут отсутствовать, если в базе нет ответа;
- релевантность определяется текущим запросом, связями, темами и интересами, а не только точными цитатами;
- серия/план связывается с постами, когда связь следует из данных, но отсутствие серии не ломает общий механизм;
- учитываются черновики, опубликованные и отложенные посты;
- для запросов на продолжение публикаций допускается ограниченный recent bias, но не слепой набор последних N;
- лимит материалов не обходится без доказанной необходимости; для серии можно удерживать не более текущего лимита (обычно до 5 постов);
- полный текст и вложения передаются только после обоснованного отбора;
- финальный генератор не используется как поисковик по всей базе;
- никакого `normative_value=false` под конкретную заметку;
- никакого prompt-костыля под русский, французский, английский или конкретный тип документа;
- при ошибке вспомогательного precision-вызова не теряется весь валидный baseline и сохраняется наблюдаемость деградации.

## План новой сессии

1. Прочитать этот отчет и текущую реализацию `_run_precision_confirmation`, `_decode_precision_confirmation` и selector transport.
2. Сначала добавить диагностические focused-тесты/telemetry для точного класса `provider_error`; не запускать полный suite.
3. Воспроизвести live-контракт сценария 21 локально с тем же количеством кандидатов и registry units. Проверить structured-output JSON Schema и plain transport.
4. Исправить протокол precision либо сделать надежный ограниченный fallback на валидный baseline. Не демонтировать safety/provenance проверки.
5. Добавить focused-тесты на:
   - provider exception в precision;
   - invalid transport/decode;
   - generated obligations с несколькими независимыми источниками;
   - member classification inventory;
   - пустую базу релевантных материалов;
   - заметку серии + связанные посты;
   - черновики/опубликованные/отложенные посты;
   - вложения только у действительно выбранного объекта.
6. Прогнать только затронутые тесты phase2/phase3/research, затем пересобрать backend и worker.
7. Повторить live-сценарии `4, 8-12, 14-21`, не останавливаясь на первом сбое.
8. После исправления провала провести один immutable полный прогон всех 21 сценариев. Цель: `21/21`, critical recall `100%`, irrelevant selection `0`, no position errors, no validation/provider errors и корректное пустое окно там, где evidence действительно нет.
9. Сценарий 4 не лечить отдельным правилом. Если после системного исправления он все еще падает, анализировать его вместе с общей моделью implicit-next-artifact planning.

## Команды для следующей сессии

Проверка локальных targeted-тестов:

```bash
cd /Users/konstantinkuznecov/TG_Platform/backend
.venv/bin/pytest -q \
  tests/test_agent_unified_phase2_contract.py \
  tests/test_agent_unified_phase3_selector.py
```

Пересборка:

```bash
cd /Users/konstantinkuznecov/TG_Platform
AGENT_UNIFIED_CATALOG_V1_ENABLED=1 \
AGENT_TYPED_REQUIREMENTS_V1_ENABLED=1 \
AGENT_UNIFIED_SELECTOR_V1_ENABLED=1 \
AGENT_VERIFIED_PACK_BOUNDARY_V1_ENABLED=1 \
AGENT_PLANNER_POLICY_V1_ENABLED=1 \
AGENT_UNIFIED_DEFAULT_ON=0 \
docker compose up -d --build --force-recreate backend celery-worker
```

Проверка отдельного сценария:

```bash
cd /Users/konstantinkuznecov/TG_Platform/backend
.venv/bin/python scripts/agent_unified_formal_canary_inspect.py \
  --manifest tests/fixtures/agent_unified_phase6/v174/formal_canary_manifest.json \
  --sequence 21
```

## Ограничения и гигиена worktree

Рабочее дерево уже было существенно изменено предыдущими итерациями и содержит множество fixture-директорий `v92-v174`. Не откатывать чужие изменения и не удалять fixtures без отдельной проверки происхождения. Перед новыми правками сначала определить, какие файлы относятся к текущему исправлению, и не смешивать диагностику с несвязанным рефакторингом.
