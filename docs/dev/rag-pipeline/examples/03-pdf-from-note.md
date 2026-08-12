# Пример 03 — PDF из заметки

← [Каталог](../README.md#03--pdf-из-заметки)

**ADR-011:** content lane, pre-seeded ReAct.

**Условные обозначения в последовательности:**

| Кто | Значение |
|-----|----------|
| **Система** | детерминированный node графа, без LLM |
| **Агент** | node `call_model` — orchestrator LLM выбирает tool или Stop |
| **Инструмент** | node `tools` — выполнение выбранного tool |
| **Ответная модель** | финальная генерация текста пользователю |

---

## 1. Контекст

| Поле | Значение |
|------|----------|
| **Запрос** | «Какая была точная доходность в отчёте?» |
| **Scope** | `post` (post chat, открыт `post-1`) |
| **Линии** | content |
| **История** | нет |
| **Ledger** | пустой |
| **Фикстуры** | [post-1](../README.md#пост-post-1-мартовский-дайджест-published), note `n1`, attachment `f1` |

**Предусловия:** `note_chunk` для `n1` в индексе; `attachment_text` для `f1` **ещё нет**.

---

## 2. Последовательность действий

| # | Кто | Действие | LLM | Изменение в State |
|---|-----|----------|-----|-----------------|
| 1 | **Система** | Принять HTTP-запрос `/ai/reply/`, собрать bundle + историю чата | нет | `user_text`, `scope=post`, `post_id=post-1` |
| 2 | **Система** | `rag_gate`: проверить, есть ли предметный вопрос | нет | `gate_passed=true` |
| 3 | **Система** | `l1_retrieve`: embed запроса → pgvector search → top-k hits | нет | `l1_hits[0]` = note_chunk n1, sim 0.81, `referenced_attachment_ids=[f1]` |
| 4 | **Система** | `need_agent` (Tier A): known_ref `attachment:f1`, pointer phrase, answer_type_mismatch (нужны цифры, в чанке их нет) | нет | `need_agent=true`, `tier_a_seed_ref=attachment:f1` |
| 5 | **Система** | `lane_router`: запрос про контент отчёта → только content lane | нет | `lanes=[content]` |
| 6 | **Система** | `context_pack`: собрать prompt-пакет для агента (L1 hits, scope, seed hint, constraints) | нет | `context_pack` заполнен |
| 7 | **Система** | `load_ledger`: загрузить dialog ledger из PostgreSQL | нет | `dialog_ledger=[]` |
| 8 | **Система** | `apply_seed`: выполнить `HydrateAttachment(ref=attachment:f1, mode=text)` — скачать PDF, извлечь текст, записать в `attachment_text` | нет | `context_blocks` += note preview + PDF text; `visited` += f1; `vision_used=0` |
| 9 | **Агент** | `call_model` (шаг 1): прочитать context pack + transcript → вызвать tool `Stop(reason=sufficient)` | **да** | `messages` += assistant tool_call Stop |
| 10 | **Система** | `should_continue`: tool_calls пусты после Stop → выход из subgraph | нет | `steps=1`, `stopped_reason=sufficient` |
| 11 | **Система** | `evidence_check`: вопрос про цифры → в context есть attachment text → pass | нет | — |
| 12 | **Система** | `append_ledger`: записать snapshot (n1, f1 hydrated) в PostgreSQL | нет | ledger turn сохранён |
| 13 | **Система** | `format_output`: собрать `rag_context` + cites из `context_blocks` | нет | `rag_context` готов |
| 14 | **Ответная модель** | Сгенерировать ответ пользователю на основе bundle + history + `rag_context` | **да** | текст ответа с цифрами из PDF |

**Итого LLM-вызовов до ответа пользователю:** 1 (агент Stop) + 1 (ответная модель) = **2**.  
**Инструментов агента:** 0 (hydrate был в seed, не через agent).  
**Agent budget:** 1 из 4 steps.

---

## 3. State (ключевые точки)

### После действия 3 (retrieve)

```yaml
l1_hits:
  - node_type: note_chunk
    note_id: n1
    similarity: 0.81
    referenced_attachment_ids: [f1]
tier_a_seed_ref: attachment:f1
need_agent: true
```

### После действия 8 (seed)

```yaml
context_blocks:
  - "[note n1] Полные результаты доходности… См. приложенный отчёт."
  - "[attachment f1] …текст PDF с точной доходностью 12.4%…"
visited: [note:n1, attachment:f1]
```

### После действия 13 (format_output)

```yaml
stopped_reason: sufficient
rag_context: "<note>…</note>\n<attachment>…</attachment>"
```

---

## 4. Чего не происходит

- Не вызываются: `referent_router`, `artifact_resolver`, `compose_retrieval_plan`, `plan_alignment`
- Analytics lane не активируется
- Агент **не** вызывает `OpenNote` / `HydrateAttachment` — seed уже сделал hydrate
- Tier B LLM не вызывается (Tier A дал fast-path)

---

## 5. Acceptance criteria

1. Действие 8 (`apply_seed`) выполняет hydrate **до** агента.
2. `rag_context` содержит note chunk и текст PDF.
3. Не более 1 agent step.
4. `attachment_text` для `f1` закэширован — см. [пример 07](07-cached-attachment-l1.md).
