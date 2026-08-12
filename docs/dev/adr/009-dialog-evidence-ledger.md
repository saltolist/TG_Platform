# ADR-009: Dialog Evidence Ledger — multi-turn referents в agentic RAG

## Статус
✅ **Принято — v1 + v1.5** (PostgreSQL ledger, artifact resolver, referent router,
dialog_seed, deterministic dialog plan; turn 3 fast-path на чате `0671925c`)

> Дополняет [ADR-008: Agentic Graph RAG](008-agentic-graph-rag.md) (каскад L0→L2,
> post resolver, plan alignment). Здесь — **второй класс referent'ов**: ссылки на
> evidence из **истории чата**, а не только «пост про X» по каталогу.
> Примеры трассировки — [Сценарий: Agentic Graph RAG](../agentic-rag-scenario.md)
> (секция «Dialog follow-up», после реализации).

## Контекст

После внедрения **target post resolver** (`rag_target_resolver.py`) named-post
запросы в global chat disambiguate корректно: «приветственный пост» → `post_id=3`,
«пост про переключений» → `721c63fe…`. Plan alignment и `cross_post=deny` не дают
planner'у подтянуть media чужого поста без binding.

Остаётся **другой класс ошибок** — multi-turn referent на **артеfact из диалога**:

| Turn | Запрос | Ожидание |
|------|--------|----------|
| 1 | «Какое изображение welcome-посту?» | post 3, нет media → рекомендации по тексту |
| 2 | «А для поста про переключений?» | post 721, vision по PNG |
| 3 | «А как же картинка с девушками?» | PNG из turn 2 (anime) vs welcome post 3 |

**Фактическое поведение turn 3** (чат `da4841f9`, до ADR-009):

- Brief: `task=visual`, **без** `named_post_query` → post resolver не запускается.
- L1 top hit — note «Пространственная система», не PNG с turn 2.
- Planner: `OpenPost(3)` + `OpenNote` с чужим note_id, `HydrateAttachment(ref=null)`.
- Stop: `evidence_gap_on_target`; контекст — только текст post 3.
- Ответ assistant опирается на **историю диалога**, а не на повторный vision по PNG.

Корневая причина — **разрыв referential integrity между turn'ами**: retrieval brief
и resolver знают «какой пост», но не знают «**какой артеfact** из прошлых ответов
имеет в виду пользователь».

Требования:

1. Follow-up «та картинка», «второй вариант», «тот баннер» должен резолвиться в
   **конкретные ref/id**, уже собранные или явно процитированные в чате.
2. Механизм **универсален** — не только PNG и не хардкод под welcome/721; любой
   entity type графа (post, note, attachment, analytics, comments).
3. **Cross-post read** разрешён только для **explicitly resolved** refs из ledger,
   не для «открой любую note с картинками».
4. Ответ после L2 должен опираться на **повторно гидратированный evidence**, а не
   только на prose assistant в history.

## Связь с ADR-008

| ADR-008 (есть / в работе) | ADR-009 (этот документ) |
|---------------------------|-------------------------|
| RetrievalBrief, evidence_needed | + `referent_type`, `dialog_entities[]` |
| Target **post** resolver | + **artifact** resolver |
| `resolved_target_post_id`, `cross_post=deny` | + narrow `cross_post=allow_for_resolved_refs` |
| Plan alignment (L1 note, hydrate order) | + alignment по dialog refs |
| Decision ledger (`7. rag.L2.*`) | + ledger **между turn'ами** (session) |
| Stop evaluator | + stop по N dialog attachment refs |

ADR-008 не заменяется — ADR-009 добавляет слой **dialog memory** поверх того же
L2 executor и tools (`OpenPost`, `HydrateAttachment`, …).

## Рассмотренные варианты

**Откуда брать «ту картинку»**

- A. Полагаться на **history в промпте** answer model — уже так частично работает,
  но без vision rerun и без гарантий; planner L2 history не видит структурно.
- B. **Regex/keywords** («девушки» → anime PNG) — не масштабируется.
- C. **(выбран)** **Dialog Evidence Ledger** — после каждого L2-turn записывать
  структурированный snapshot того, что executor **фактически** открыл/гидратировал;
  на следующем turn **artifact resolver** (LLM + ledger) matчит запрос к записям.

**Где хранить ledger**

- A. Только in-memory trace buffer — теряется при restart; достаточно для v1 dev.
- B. In-memory per `chatId` + восстановление из последнего trace при miss.
- C. **(v1, реализовано)** Persist в БД (`dialog_evidence_turns`) для долгих сессий и restart-safe dev.

**Cross-post для dialog artifact**

- A. Полный `cross_post=deny` — turn 3 невозможен (PNG на 721, текст на 3).
- B. Свободный cross-post — регресс к «media с чужого поста».
- C. **(выбран)** **Allowlist**: `HydrateAttachment` / `OpenNote` только для
  `ref`/`note_id` из artifact resolution с `confidence ≥ medium`.

## Решение

### Dialog Evidence Ledger

После успешного L2 (или partial — до Stop) **append** snapshot turn'а:

```yaml
turn_id: uuid
recorded_at: ISO8601
user_text: "…"
target_post_id: "721c63fe…"          # если был bound
entities:
  - entity_type: post
    post_id: "721c63fe…"
    title: "Больше никаких переключений…"
  - entity_type: note
    note_id: ee175834…
    post_id: "721c63fe…"
    title: "Варианты изображений для поста"
  - entity_type: attachment
    ref: attachment:704a2ddd…
    post_id: "721c63fe…"
    note_id: ee175834…
    mime: image/png
    filename: "Снимок экрана…"
    vision_preview: "аниме, девушки, сезон 4…"
    hydrated: true
  - entity_type: attachment
    ref: attachment:04022610…
    vision_preview: "баннер ChatGPT…"
    hydrated: true
    recommended: true                  # optional: assistant явно рекомендовал
assistant_cites:                      # weak entries — из ответа без hydrate
  - path: /note/global/ee175834…/
    label: "Варианты изображений"
```

**Источники записей** (по убыванию надёжности):

1. `AgentState` после executor: `opened_posts`, `listed_image_attachment_refs`,
   blocks в `context_blocks`, `target_evidence_gap`.
2. Vision summaries из `HydrateAttachment`.
3. Cite-path / filename из **ответа assistant** (weak — для recovery v2).

Ledger **не** хранит выдуманные LLM id — только то, что прошло через tools или
явный cite.

### Referent Router

Перед planner (после или вместе с post resolver):

```
user_text + dialog_context + ledger + l1_results
        │
        ▼
   referent_type?
        ├─ named_post        → rag_target_resolver (ADR-008)
        ├─ dialog_artifact   → rag_artifact_resolver (ADR-009)
        ├─ dialog_compare    → artifact refs[] + compare_with_post_id
        ├─ post_followup     → post resolver + dialog visual upgrade (ADR-008)
        └─ generic           → без pre-resolution
```

### Artifact Referent Resolver

LLM-вызов (аналог post resolver), вход:

- вопрос пользователя;
- 2–3 последних turn'а диалога;
- ledger entities (strong + weak);
- опционально L1 hits.

Выход (JSON):

```json
{
  "referent_type": "dialog_artifact",
  "entity_refs": [
    {"entity_type": "attachment", "ref": "attachment:704a2ddd…"}
  ],
  "compare_with_post_id": "3",
  "confidence": "high",
  "rationale": "«картинка с девушками» → vision turn N: anime PNG"
}
```

Matч по: `vision_preview`, `filename`, `title` note/post, `recommended`,
ordinal («второй вариант» → rank в ledger), exclude («не баннер»).

### Расширение RetrievalBrief

```yaml
referent_type: dialog_artifact | dialog_compare | named_post | generic
dialog_entities:
  - entity_type: attachment
    ref: attachment:704a2ddd…
compare_with_post_id: "3"              # optional
evidence_needed: [post_text, vision]
constraints:
  - cross_post=deny
  - cross_post_allow_refs=[attachment:704a2ddd…]   # narrow allowlist
```

Planner prompt получает блоки (как catalog + post resolution в ADR-008):

- `format_ledger_for_planner(ledger, last_n_turns)`
- `format_artifact_resolution_for_planner(resolution)`

### Plan alignment (дополнения)

Reject plan если:

- brief содержит `dialog_entities[].ref`, но plan не включает
  `HydrateAttachment(ref)` (или соответствующий tool для entity_type);
- plan открывает `OpenNote`/`OpenPost` на post без refs, когда resolution уже дал ref;
- `OpenNote` на post с `ListPostNotes=0` при известном ref из ledger;
- Stop до hydrate всех required dialog refs.

### Binding policy (дополнения)

- `cross_post=deny` по умолчанию сохраняется.
- **Exception:** tool на `post_id ≠ resolved_target_post_id` разрешён, если
  `(tool, ref|note_id)` ∈ `cross_post_allow_refs` из artifact resolution.
- Binding target post для compare: `compare_with_post_id` из resolution.

### Stop evaluator (дополнения)

| referent_type | Stop OK когда |
|---------------|---------------|
| `dialog_artifact` | все `entity_refs` hydrated (+ optional compare post text) |
| `dialog_compare` | vision для **каждого** ref в resolution (аналог comparative visual) |
| `named_post` | без изменений (ADR-008) |

При `confidence=low` и нескольких candidates — **не** guess; Stop с
`needs_clarification` (v3.5).

### Trace (новые фазы)

При `AI_CONTEXT_LOG=1`:

| Фаза | Содержание |
|------|------------|
| `7. rag.L2.ledger_snapshot` | entities записанные после turn |
| `7. rag.L2.referent_router` | referent_type |
| `7. rag.L2.artifact_resolver` | entity_refs, confidence, rationale |
| (остальное) | brief, plan_align, ledger — как ADR-008 |

### Жизненный цикл (turn N+1)

```
POST /ai/reply/
  → L0 → L1 (query + dialog_context)
  → Tier A/B → L2 escalate
  → load ledger[chatId]
  → build RetrievalBrief
  → referent router
       ├─ post resolver (if named_post)
       └─ artifact resolver (if dialog referent)
  → compose_retrieval_plan(catalog + resolutions + ledger)
  → plan alignment → execute → stop
  → append ledger snapshot
  → answer LLM
```

## Roadmap реализации

| Версия | Scope | Статус |
|--------|-------|--------|
| **v1** | Ledger persist, artifact resolver, dialog_seed, dialog plan, turn 3 fast-path | ✅ |
| **v1 acceptance** | Turn 3 стабилен после restart; тесты agent/ledger/resolver/binding | ✅ |
| **v1.5** | Referent router (non-exclusive gates); `dialog_compare` one post | ✅ |
| **v2** | Weak ledger + recovery search если ref не hydrate в чате | ☐ |
| **v2.5** | Deixis: «второй», «тот что рекомендовал», exclude | ☐ |
| **v3** | Multi-entity в одном вопросе | ☐ |
| **v3.5** | `confidence=low` → clarification | ☐ |
| **v4** | ~~Persist ledger в БД~~ → done in v1 | ✅ |
| **v5–v7+** | Non-visual entities; Tier A fast path; write-actions | ☐ |

v1 закрывает регрессию turn 3; v1.5 — «сравни artifact с одним welcome post».

## Принципы (не нарушать)

1. **No entity-specific hardcodes** — нет mapping «приветствую→3», «девушки→ref X».
2. **Facts over prose** — ledger только из executor/cite, не из free-text planner.
3. **Narrow cross-post** — allowlist refs, не «любая note с PNG».
4. **Same tools** — новые модули в routing/brief/alignment; executor tools те же.
5. **Fail closed** — при ambiguous referent лучше спросить, чем открыть post 3.

## Последствия

**Плюсы**

- Multi-turn visual/compare становится **проверяемым** (trace + tests).
- Меньше «умных ответов без evidence» на follow-up.
- Единая модель для PNG, PDF, note, post, analytics (поэтапно).

**Минусы / costs**

- +1 LLM-вызов (artifact resolver) на dialog-referent turn.
- Память per chat (ledger); нужен cap (например последние 10 turn / 50 entities).
- Сложнее alignment и stop; больше регрессионных сценариев.

**Зависимости**

- Target post resolver и plan alignment (ADR-008) должны быть стабильны.
- `AI_CONTEXT_LOG` и trace buffer — для отладки ledger/resolver.

**Тесты (минимум для v1 + v1.5)**

| # | Требование | Покрытие |
|---|------------|----------|
| 1 | Turn 3 dialog artifact (seed, без re-hydrate) | `test_run_agentic_loop_turn3_dialog_artifact_resolver` |
| 1b | `dialog_compare` one-post (seed + OpenPost compare) | `test_run_agentic_loop_dialog_compare_seeded_opens_compare_post` |
| 2 | Cross-post blocked/allowed | `test_rag_binding_policy.py`, `test_rag_plan_alignment.py` |
| 3 | Planner misbind → alignment reject | `test_rag_plan_alignment.py` |
| 4 | Stop без hydrate → reject | `test_rag_stop_evaluator.py` |
| — | Ledger persist/restart | `test_ledger_survives_session_reopen` |
| — | Referent router gates | `test_rag_referent_router.py` |

## Ссылки

- [ADR-008: Agentic Graph RAG](008-agentic-graph-rag.md)
- [Сценарий: Agentic Graph RAG](../agentic-rag-scenario.md)
- [Роадмап: Agentic Graph RAG](../roadmap-agentic-rag.md)
- Код (ADR-008, реализовано): `rag_target_resolver.py`, `rag_retrieval_brief.py`,
  `rag_plan_alignment.py`, `rag_binding_policy.py`
- Код (ADR-009, v1 + v1.5): `rag_dialog_ledger.py`, `rag_artifact_resolver.py`,
  `rag_referent_router.py`, `build_dialog_evidence_plan`, `seed_hydrated_dialog_artifacts_from_ledger`
