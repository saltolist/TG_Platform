# Промпт для окончательного semantic closure фазы 6

Ниже приведен готовый промпт для новой Codex-сессии.

```text
Реализуй план окончательного semantic closure фазы 6 Workspace Agent.

Workspace:
/Users/konstantinkuznecov/TG_Platform

Главный implementation plan:
- docs/dev/workspace-agent-unified-phase-6-semantic-closure-plan.md

Связанный conditional design:
- docs/dev/workspace-agent-recall-verifier-conditional-plan.md

Источники истины:
- docs/dev/workspace-agent-unified-phase-6-selector-reliability-plan.md
- docs/dev/workspace-agent-unified-phase-6-rollout.md
- docs/dev/workspace-agent-unified-phase-6-closure.md
- docs/dev/workspace-agent-unified-integrity-counting-plan.md
- текущий код, migrations, tests, fixtures, provider replay и durable telemetry

Baseline при создании плана:
- HEAD: bd86b5b01639aa4e6f7944dff7a29cd358e10355
- branch: cursor/per-post-analytics-foundation
- strict report: 33/42 pass, 9 blocked
- phase-0 digest:
  4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474
- AGENT_UNIFIED_DEFAULT_ON=false

Сначала проверь pwd, HEAD, branch, baseline commit, git status и все
незакоммиченные изменения. Ожидаются намеренные новые документы:
- docs/dev/workspace-agent-unified-phase-6-semantic-closure-plan.md
- docs/dev/workspace-agent-unified-phase-6-semantic-closure-prompt.md

Сохрани их и включи в отдельный итоговый phase-6 final-closure commit. Не
откатывай пользовательские или посторонние изменения.

Прочитай главный план и conditional Recall Verifier plan полностью. Затем
прочитай актуальные remediation sections rollout/closure и код transport,
Selector runtime, strict gates, reports, tests и fixtures. Старые ADR используй
только как исторический контекст.

Фактическая исходная точка:
- основной summary 160 provider replay: 8/8 final valid, 8/8 first-attempt
  valid, 0 retries, 0 positional errors;
- required recall 8/9, compatibility baseline 8/9;
- critical required-evidence recall 7/8 при обязательном 1.0;
- irrelevant selection 1/7 при compatibility baseline 0/7;
- boundary 256 valid first-attempt, actual total 19982 <=22000 tokens;
- formal live canary еще не запускался: 0 chats, 0 messages, 0 decisions;
- staging/canary rollback unavailable;
- широкий DB regression был поврежден PostgreSQL recovery, focused tests
  прошли.

Главная цель: закрыть semantic, canary и rollback blockers фактическими
измерениями, не ослабляя quality и не выдавая unavailable за pass.

Сначала исправь два дефекта gate contract:
1. irrelevant selection при zero baseline должен проходить только при value=0;
   используй <=0/MAX 0, а не математически невозможное <0;
2. selector_schema_reliability_within_budget сделай composite=1 только если
   measured sample >=20, first-attempt >=0.95, final=1.0, retry<=0.05 и position
   errors=0. Все дочерние gates остаются отдельными mandatory строками.

До semantic изменений добавь scenario-level raw-safe attribution. Зафиксируй,
какой frozen critical ref пропущен и какой irrelevant ref выбран. Не сохраняй
raw provider output, source content, user content, credentials или account IDs.
Докажи boundary каждого miss: discovery, summary, Selector, materialization или
Answer Model. Recall Verifier разрешен только для canonical-valid Selector false
negative, когда required ref и достаточный signal уже присутствуют в immutable
CandidateEnvelope.

Раздели labeled data на calibration и untouched qualification. Qualification
должен содержать минимум 20 semantic scenarios, 20 critical refs и 20 irrelevant
refs, multilingual/secondary-topic/near-topic/parent/source/nullable-score cases.
Labels фиксируются до provider output и не меняются для получения pass.

Сначала реализуй primary-only semantic correction одного Context Selector.
Проверь prompt/reason definitions/query goal/summary 160 и 240 и, только при
необходимости, deterministic query-conditioned snippet с provenance. Не добавляй
forced required-source selection, select-all, второй primary attempt или
ground-truth hints. Выбирай самый короткий variant, который одновременно дает:
- critical recall 1.0;
- irrelevant selection 0 на zero-baseline cohort;
- relevant recall и final-pack precision не ниже baseline;
- pass provider token/latency ceilings.

Если primary-only path проходит calibration и untouched qualification, не
реализуй Recall Verifier и переходи к formal canary.

Если primary-only path после добросовестного измерения не проходит semantic
floors и attribution доказывает Selector-layer false negative, этот prompt и
главный план являются явным новым решением, разрешающим conditional Recall
Verifier. Реализуй его строго по
docs/dev/workspace-agent-recall-verifier-conditional-plan.md:
- отдельный default-off flag;
- только после canonical-valid primary decision;
- pure eligibility;
- один add-only provider call без retry;
- fixed positional transport и deterministic two-key admission;
- maximum one addition;
- invalid/timeout/provider failure возвращает exact primary baseline;
- no calls on exact/structural/complete/overflow;
- shadow сначала, active admission только после measured gates;
- primary Selector, Verifier и total provider metrics раздельны;
- no second Answer Model, no planner loop.

Обязательные verifier budgets, если он реализован:
- p95 total tokens <=2500;
- p95 latency overhead <=10000 ms;
- false promotions=0 на mandatory qualification cohort;
- primary removals=0;
- invalid/timeout result changes=0;
- shadow Answer Model calls=0 и answer change rate=0;
- retries=0, maximum additions=1.

Выполни offline qualification выбранного path минимум дважды на untouched
cohort. Повтори actual provider boundary-256 после изменения primary prompt или
summary. Никакой live canary до полного offline pass.

Для regression не используй нестабильный shared PostgreSQL. Создай отдельный
disposable test DB/compose project с отдельными database/volume/port, не удаляя
пользовательские данные. Прогони focused Selector/provider/runtime/indexing
tests, ранее затронутые recovery tests и scoped phases 0-6 serially. Полный
unrelated suite не нужен. Phase-0 report должен минимум дважды сохранить
исходный digest. Strict phase-6 report повтори минимум 50 раз.

После offline и regression pass проведи formal live canary через существующую
авторизованную платформенную сессию. Не читай, не сохраняй и не выводи
credentials. До сообщений создай versioned manifest с expected refs/coverage и
ровно 20 planned semantic Selector decisions. Не превышай 20 chats и 4 user
messages на chat. Оценивай durable CandidateEnvelope, canonical decision,
Verifier/admission при наличии, EvidencePack и ответ, а не только completed.

Canary targets:
- final canonical-valid primary decisions 20/20;
- first-attempt valid >=19/20;
- primary retries <=1/20;
- position errors=0;
- schema composite=1;
- critical required-evidence recall=1.0;
- irrelevant selection=0 на zero-baseline cases;
- complete/classification required-object coverage=1.0;
- false workspace-data-unavailable answers=0;
- Answer Model calls after final primary failure=0;
- exact/structural Selector и Verifier calls=0;
- false Verifier promotions=0 и primary removals=0, если Verifier active.

Внешние DNS/provider failures учитывай отдельно. Они не являются schema invalid
или pass и не разрешают превысить traffic ceiling.

Повтори canary rollback для staged flags, resume, primary timeout, schema
mismatch, pack overflow, backfill interruption, compact decode failure и
Verifier failure/admission rejection при наличии. Проверь сохранность user
message, ledger, refs, evidence, checkpoint и compatibility contract.

Не меняй архитектуру фаз 1-5. Сохрани primary Selector ceiling 100, explicit
guard 101-256 и blocking overflow 257. Не сокращай complete coverage через top-k.
Planner policy работает только после verified canonical decision и verified
EvidencePack. После final primary failure Answer Model не вызывается.

Не выдумывай provider/canary/staging результаты. При любом failed, unavailable,
inconclusive или insufficient-sample gate оставь default-off и фазу незакрытой,
но заверши все безопасные локальные артефакты.

После реализации:
- представь результат каждого исходного, исправленного и нового gate;
- обнови rollout, closure и semantic-closure plan только фактическими данными;
- сформируй offline, canary, rollback и strict attestations;
- не отмечай фазу закрытой, пока каждый mandatory gate не measured pass;
- создай отдельный commit только с phase-6 final closure работой и двумя новыми
  документами;
- сообщи commit hash, tests, provider measurements, exact live-canary sample,
  gate matrix и blockers.

Не останавливайся на анализе: реализуй, проверь, проведи разрешенный canary и
закоммить все безопасно выполнимые части.
```
