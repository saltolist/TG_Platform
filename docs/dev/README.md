# Документация для разработчика

Техническая документация по проекту **TG Platform Web**.

## Разделы

- [Старт проекта](setup.md) — установка, запуск, переменные окружения
- [Архитектура](architecture.md) — FSD, слои, паттерны, потоки данных
- [Режимы работы](runtime-modes.md) — презентация / демо / реальный аккаунт, ключи, overlay
- [Сборка контекста для AI-чатов](ai-context-assembly.md) — слои промпта, bundle, rolling summary, ветки
- [Роадмап: Agentic Graph RAG](roadmap-agentic-rag.md) — приоритеты реализации graph RAG и будущих агентных действий
- [Каталог примеров RAG-пайплайна (ADR-011)](rag-pipeline/README.md) — golden scenarios research/actions/media
- [Unified Agent Runtime (ADR-012)](adr/012-unified-agent-runtime.md) — LangGraph runs, HITL, media jobs
- [Baseline metrics (pre-migration)](agent-baseline-metrics.md) — legacy L2 пороги для canary
- [Workspace Agent phase 0 baseline](workspace-agent-phase0-baseline.md) — production traces, p50/p95/p99, graders и quality freeze
- [Workspace Agent phase 1 runtime](workspace-agent-phase1-runtime.md) — event-loop ownership, fork-safe pools, worker warmup и queue isolation
- [Workspace Agent phase 2 contracts](workspace-agent-phase2-contracts.md) — typed targets/sources, multi-target bootstrap, budgets и handoff
- [Workspace Agent phase 3 search ledger](workspace-agent-phase3-search-ledger.md) — dedupe intent/read, bounded rewrites, validator finish и metrics
- [Workspace Agent current limitations](workspace-agent-current-limitations.md) — текущие ограничения, release blockers, фаза 3 и оставшиеся работы
- [Сценарий: Agentic Graph RAG (legacy)](agentic-rag-scenario.md) — deprecated, legacy L2
- [Сценарий: сводки, ветки и окно LLM](summary-branch-scenario.md) — эталонное поведение при форках и 3+ поколениях bundle
- [Метки сводок `1-2-3`](summary-version-labels.md) — каталог версий и метки на сообщениях
- [API-контракты](api-contracts.md) — эндпоинты, Zod-схемы, типы
- [Тестирование](testing.md) — стратегия, инструменты, примеры
- [Деплой / CI/CD](deploy.md) — сборка, окружения, публикация
- [ADR — архитектурные решения](adr/README.md) — зафиксированные решения

← [Вернуться к главной](../README.md)
