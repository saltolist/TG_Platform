# Промпт для реализации phase-6 Selector reliability plan

Ниже приведен готовый промпт для новой Codex-сессии.

```text
Реализуй план исправления Selector reliability и окончательного закрытия фазы 6
Workspace Agent.

Workspace:
/Users/konstantinkuznecov/TG_Platform

Главный implementation plan:
- docs/dev/workspace-agent-unified-phase-6-selector-reliability-plan.md

Условный follow-up, который не надо реализовывать без измеренных false negatives:
- docs/dev/workspace-agent-recall-verifier-conditional-plan.md

Источники истины:
- docs/dev/workspace-agent-unified-integrity-counting-plan.md
- docs/dev/workspace-agent-unified-phase-6-rollout.md
- docs/dev/workspace-agent-unified-phase-6-closure.md
- текущий код, migrations, tests, fixtures и durable pilot telemetry

История реализации:
- исходная фаза 6: e6bb80c8c984534710e08d2c30514dbd5f7519e7
- closure implementation: 712e19b58fc5a96c64a76bc5fe53933bbb5ec7b9
- account backfill: 6b84695770d0521d5eaa7d12876850da7785c009
- текущий follow-up baseline при создании плана:
  51e2d22be5cfe800b36cb5c9058dcdd2a0f120a3

Сначала проверь pwd, HEAD, branch, указанные commits, git status и все
незакоммиченные изменения. Ожидаются намеренные новые документы:
- docs/dev/workspace-agent-unified-phase-6-selector-reliability-plan.md
- docs/dev/workspace-agent-unified-phase-6-selector-reliability-prompt.md
- docs/dev/workspace-agent-recall-verifier-conditional-plan.md

Сохрани их и включи в итоговый отдельный phase-6 remediation commit. Не
откатывай пользовательские или посторонние изменения.

Прочитай implementation plan полностью. Затем прочитай closure-план полностью и
разделы «Результат», «Exit criteria» и «Остаточные риски» фаз 0-6. Старые ADR и
roadmap используй только как исторический контекст.

Исходное фактическое состояние:
- strict report: 26/34 pass, 8 blocked;
- account pilot: 20 chats, 46 user messages, максимум 4 на chat;
- 16 Selector runs, 31 provider calls, 15 retries;
- canonical-valid 2/16, first-attempt-valid 1/16;
- phase-0 digest:
  4fe050b7d491861fd0b545471699f4d90c1151063140d7795ea4c16b3119f474;
- AGENT_UNIFIED_DEFAULT_ON=false.

Главная цель: устранить измеренный корень invalid_transport/invalid_canonical.
Не добавляй обязательный второй Selector или Recall Verifier в этой работе.
Post-answer semantic auditor также отложен. Если после исправления transport
размеченный replay докажет semantic false negatives, зафиксируй их как blocker
и рекомендацию для следующей фазы, но не добавляй скрытый второй вызов без
нового решения.

Обязательные архитектурные ограничения:
- не менять архитектуру фаз 1-5;
- не добавлять второй Selector или planner loop;
- semantic Context Selector call остается один, кроме одного bounded retry;
- provider/model transport должен быть универсальным и не зависеть от имени
  OpenAI, DeepSeek или конкретной модели;
- использовать capability negotiation: strict schema, tool/function calling,
  JSON mode, затем plain compact frame;
- все tiers декодируются в один canonical workspace.context-selector/v2;
- полный CandidateEnvelope остается в runtime/checkpoint/trace;
- title/summary остаются внутри untrusted-data boundary, forged frame/fence
  tokens neutralize-ятся;
- shadow Answer Model calls=0 и answer change rate=0;
- после final Selector failure Answer Model не вызывается и система не говорит,
  что workspace data отсутствует;
- planner policy работает только после verified canonical v2 и verified
  EvidencePack boundary;
- exact/structural paths не вызывают Selector;
- complete coverage нельзя сокращать через top-k;
- synchronous rollout ceiling остается 100;
- 101-256 не получают ready без explicit exhaustive flow или measured boundary
  canary;
- 257 refs всегда blocking incomplete с ready=false;
- unavailable/missing/inconclusive/not_measured/derived не считается pass;
- flags остаются default-off до measured pass всех mandatory gates.

Реализуй новый versioned compact transport, в котором модель возвращает только
позиционный assessment vector: relevance, reason code и дискретный confidence.
Index определяется позицией. Role, resolution, source dispositions, every-ref и
every-source completeness выводятся детерминированно. Добавь exact cardinality,
registry/request nonce и completion marker, чтобы truncated output нельзя было
принять за «все нерелевантно». Конкретную пунктуацию wire frame можно улучшить
только при наличии parser tests, подтверждающих более надежный вариант.

Decoder должен возвращать typed validation errors. Единственный retry получает
конкретные error codes, а не общее «schema validation failed». Не допускай
неограниченный fallback между capability tiers или дополнительные semantic
attempts.

Исправь metric boundary: gate <=1 относится к initial semantic Selector call, а
не к сумме classifier + Selector + Answer Model. Retry rate, first-attempt valid,
final valid, Answer Model calls и total provider calls измеряй отдельно. Это не
разрешение второго Selector.

Создай/расширь обезличенный frozen ground-truth cohort для relevant,
irrelevant, secondary-topic, ru/en/mixed, parent/source, nullable score,
exact/structural, complete и failure cases. Сравни compatibility baseline и
summary 120/160/240. Основной 160 разрешается только при non-inferior recall.
Critical required-evidence recall должен быть 1.0.

По решению rollout owner денежные mandatory gates ограниченного pilot заменены
измеряемым лимитом не более 20 chats и не более 4 user messages на chat. Не
помечай неизвестную стоимость pass: price/cost остается
availability=unavailable в telemetry, а strict report должен явно показать
замену mandatory risk-control gates, а не подмену результата.

После offline pass выполни формальный live canary через уже открытую и
авторизованную сессию платформы. Не сохраняй и не выводи credentials. Используй
не более 20 chats и не более 4 user messages в каждом. Заранее зафиксируй
expected refs/coverage, оценивай EvidencePack и ответ, а не только status
completed. Внешние DNS/provider failures учитывай отдельно.

Canary schema targets:
- final canonical-valid 20/20 Selector decisions;
- first-attempt canonical-valid >=19/20;
- retries <=1/20;
- unknown/duplicate/missing positions =0;
- false workspace-data-unavailable answers =0;
- Answer Model calls after final Selector failure =0;
- complete/classification required object coverage=1.0.

Выполни actual provider boundary measurement на 256 realistic multilingual
candidates с maximum dialog context. Зафиксируй input/cached/output/total tokens,
latency, retry, schema result и estimator delta. Gate total tokens p95 <=22000.
Не называй chars_div_4 provider usage.

Повтори rollback drill в canary для flags, resume, timeout, schema mismatch,
pack overflow, backfill interruption и compact decode failure. Проверь
сохранность user message, ledger, refs, evidence и checkpoint.

Добавь focused unit/integration/replay tests по полному списку implementation
plan. Прогони scoped regression фаз 0-6 и затронутых indexing/runtime/provider
адаптеров. Полный несвязанный suite можно не доводить до конца. Phase-0 report
должен дважды сохранить исходный digest.

Не выдумывай production/provider/canary результаты. Если traffic, ground truth,
provider usage или infrastructure реально недоступны, оставь соответствующий
gate unavailable/inconclusive, default-off и явно опиши blocker. При этом
заверши все безопасные локальные изменения, fixtures, scripts, telemetry и
tests.

После реализации:
- представь результат каждого исходного, замененного и дополнительного gate;
- обнови rollout/closure/remediation документы только фактическими данными;
- не отмечай фазу завершенной при любом непройденном gate;
- создай отдельный commit только с phase-6 Selector reliability/closure работой,
  включая два намеренных новых документа;
- сообщи commit hash, tests, measurements, live-canary sample sizes и blockers.

Не останавливайся на плане: реализуй, проверь, проведи разрешенный ограниченный
canary и закоммить все безопасно выполнимые части.
```
