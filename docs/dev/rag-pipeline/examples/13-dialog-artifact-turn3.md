# Пример 13 — Dialog artifact (turn 3)

← [Каталог](../README.md#13--dialog-artifact-turn-3)

**ADR-011:** multi-turn, ledger в context pack, seed без resolvers.

**Условные обозначения:** см. [пример 03](03-pdf-from-note.md).

---

## 1. Контекст

| Поле | Значение |
|------|----------|
| **Запрос (turn 3)** | «А как же картинка с девушками?» |
| **Scope** | `global` |
| **Линии** | content |
| **Chat** | `da4841f9` |

### История (turn 1–2, до RAG turn 3)

| Turn | Запрос | Что сделала система (кратко) |
|------|--------|------------------------------|
| 1 | «Какое изображение welcome-посту?» | L2 → OpenPost(3) → нет media → ответ по тексту |
| 2 | «А для поста про переключений?» | L2 → OpenPost(721) → HydrateAttachment PNG vision → **append_ledger** |

### Ledger на входе turn 3 (после действия 7)

```yaml
dialog_ledger:
  - turn: 2
    ref: attachment:704a2ddd-…
    post_id: "721"
    vision_summary: "anime-style illustration with female characters"
    hydrated: true
```

---

## 2. Последовательность действий

| # | Кто | Действие | LLM | Изменение в State |
|---|-----|----------|-----|-----------------|
| 1 | **Система** | Принять запрос turn 3, scope `global`, history содержит turn 1–2 | нет | `user_text`, `history` |
| 2 | **Система** | `rag_gate`: deixis-вопрос → pass | нет | `gate_passed=true` |
| 3 | **Система** | `l1_retrieve`: vector search (может hit чужую note — **не решает** ответ) | нет | `l1_hits` = secondary signal |
| 4 | **Система** | `need_agent`: `is_followup=true` + ledger не пуст → escalate | нет | `need_agent=true` |
| 5 | **Система** | `lane_router` → `lanes=[content]` | нет | не analytics |
| 6 | **Система** | `load_ledger`: PostgreSQL → snapshot turn 2 с attachment 704a | нет | `dialog_ledger` заполнен |
| 7 | **Система** | `context_pack`: **приоритет ledger** — ref, vision_summary, post_id 721; L1 hits вторичны; constraints cross_post allow refs из ledger | нет | agent видит «та картинка» = 704a |
| 8 | **Система** | `apply_seed`: `seed_hydrated_dialog_artifacts_from_ledger` — скопировать vision block из ledger в `context_blocks` **без** повторного vision API | нет | `context_blocks` += vision summary; `visited` += 704a; `vision_used=0` |
| 9 | **Агент** | `call_model` (шаг 1): контекст достаточен → `Stop(reason=sufficient)` | **да** | Stop (альтернатива: агент мог бы вызвать HydrateAttachment, но seed уже покрыл) |
| 10 | **Система** | `should_continue` → END | нет | `steps=1`, `stopped_reason=sufficient` |
| 11 | **Система** | `evidence_check`: deixis/visual + ledger ref в context → pass | нет | — |
| 12 | **Система** | `append_ledger`: snapshot turn 3 (reuse 704a) | нет | ledger обновлён |
| 13 | **Система** | `format_output` | нет | `rag_context` с vision block |
| 14 | **Ответная модель** | Ответ про anime PNG из turn 2, **не** про welcome post 3 | **да** | ответ пользователю |

**Итого LLM:** 1 agent + 1 answer = **2**.  
**Vision API:** 0 (replay из ledger).  
**Нет:** referent_router, artifact_resolver, structured plan.

---

## 3. Альтернативная ветка (если seed не покрыл)

Если ledger содержит ref, но не `hydrated: true`:

| # | Кто | Действие |
|---|-----|----------|
| 8b | **Система** | `apply_seed` пропускает unhydrated ref |
| 9b | **Агент** | `call_model`: `HydrateAttachment(ref=704a, mode=vision)` |
| 10b | **Инструмент** | vision API → summary в context; `vision_used=1` |
| 11b | **Агент** | `Stop(sufficient)` |

---

## 4. State после действия 8

```yaml
context_blocks:
  - "[ledger attachment:704a…] vision: anime-style illustration with female characters"
dialog_ledger:  # в context_pack, не дублировать в rag_context prose
  - ref: attachment:704a2ddd-…
    hydrated: true
visited: [attachment:704a2ddd-…]
vision_used: 0
```

---

## 5. Чего не происходит (контраст с legacy)

| Legacy (deprecated) | ADR-011 |
|---------------------|---------|
| `referent_router` → `dialog_artifact` | ledger в context_pack |
| `artifact_resolver` LLM | агент или seed |
| `OpenPost(3)` по ошибке | не открывать welcome без запроса |
| L1 note hit определяет ответ | ledger определяет artifact |
| `resolved_target_post_id` lock | нет target lock |

---

## 6. Acceptance criteria

1. Действие 6 (`load_ledger`) **до** context_pack и агента.
2. `vision_used` не увеличивается при hydrated ledger.
3. Ответ не сводится к OpenPost(3) only.
4. Не более 2 agent steps в типичном path.
