# TG Platform — Web

Единая точка входа для web-версии TG Platform: продуктовая документация, UX-спецификация и **Next.js клиент**.

**Сейчас:** M3 widgets ~85%, M4 features + screens ~75%. **GitHub Pages demo (MSW):** https://saltolist.github.io/my/ — см. [deploy.md](./docs/engineering/deploy.md). **Чеклист:** [m3-m5-gate-checklist.md](./docs/engineering/m3-m5-gate-checklist.md). Roadmap — [08-roadmap.md](./docs/product/08-roadmap.md).

## Структура

```
web/
├── src/                  ← Next.js app (active codebase)
├── docs/
│   ├── product/          ← модель, roadmap
│   ├── ux/               ← pages, flows, wireframes, components, design-tokens
│   ├── engineering/      ← stack, data-model, API, testing, deploy
│   ├── glossary.md
│   └── doc-maintenance.md
├── e2e/                  ← Playwright smoke tests
└── README.md
```

## Быстрый старт

```bash
cd Docs_TG_Platform/web
npm install
npm run dev    # http://localhost:3020 (в сети: http://<ваш-LAN-IP>:3020)
npm run check  # typecheck + lint + test + build
```

**Preview как на GitHub Pages** (basePath `/my`, MSW):

```bash
NEXT_PUBLIC_BASE_PATH=/my NEXT_PUBLIC_USE_MSW=1 npm run build
npx serve out -p 3021   # → http://localhost:3021/my/
```

## Карта документации

→ [docs/README.md](./docs/README.md)

## Статус

| Слой | Статус |
|------|--------|
| Продукт (`docs/product/`) | complete |
| UX (`docs/ux/`) | complete — sync с `web-legacy` |
| Engineering (`docs/engineering/`) | complete |
| Код (`src/`) | M3 🟡 / M4 🟡 — see [parity.md](./docs/ux/parity.md) |

## Legacy-клиенты (вне `web/`)

| Путь | Роль |
|------|------|
| [`../web-legacy/`](../web-legacy/) | **reference UI** (read-only) |
| [`../frontend-v2/`](../frontend-v2/) | earlier reference scaffold |
| [`../frontend/`](../frontend/) | клиент v1 |

## Принципы

1. **UX из legacy** — [pages.md](./docs/ux/pages.md), wireframes
2. **Стек** — Next.js 16, FSD, MSW, TanStack Query — [stack.md](./docs/engineering/stack.md)
3. **Визуал** — legacy semantic CSS + `tokens.css`; Tailwind для layout
4. **Local-first** — [local-first.md](./docs/engineering/local-first.md)

## Быстрые ссылки

- [Glossary](./docs/glossary.md)
- [Parity tracker](./docs/ux/parity.md)
- [Navigation flows](./docs/ux/flows.md)
- [Data model](./docs/engineering/data-model.md)
