# 18 — Image generation + attach approval

| Поле | Значение |
|------|----------|
| **lanes** | `write` + `media` |
| **depth** | `interrupt` + `background` |
| **scope** | `post` |

## Запрос

«Сгенерируй обложку в стиле дайджеста и прикрепи к черновику»

## Ожидаемый pipeline

1. Research (optional) — tone/refs from notes
2. `MediaProposal` — prompt, model, variants, cost ceiling
3. **Cost interrupt** — user approves spend
4. `media_jobs` row + Celery `submit` → poll/webhook
5. Graph `interrupt(awaiting_job)` — API restart safe
6. Preview in `MediaJobCard` — private signed URL
7. **Attach interrupt** — separate `ActionProposal` to attach asset
8. Approve → `posts/commands` attach

## Acceptance

- [ ] No bytes in graph checkpoint — only `asset_id` / `job_id`
- [ ] Cancel revokes Celery + provider; late result not auto-attached
- [ ] Asset tenant-isolated in private bucket
- [ ] Regenerate = user choice, not agent loop
