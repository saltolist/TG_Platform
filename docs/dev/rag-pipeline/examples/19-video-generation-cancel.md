# 19 — Video generation, cancel, reload/resume

| Поле | Значение |
|------|----------|
| **lanes** | `media` |
| **depth** | `interrupt` + `background` + `multi-turn` |
| **scope** | `post` |

## Запросы

1. «Сделай 15-секундный ролик по тезисам поста»
2. *(during job)* Cancel
3. Reload page → `GET /ai/runs/{id}` restores progress UI

## Ожидаемый pipeline

- Same as [18](18-image-generation.md) with longer lease/timeout
- Provider adapter: submit → poll/webhook → validate duration/MIME
- Cancel: update `media_jobs.status`, revoke worker, provider cancel if supported
- Resume: checkpointer + `agent_events` SSE `Last-Event-ID`

## Acceptance

- [ ] Job survives API/worker restart
- [ ] Cancelled job never attaches on late completion
- [ ] `GET /ai/runs/{id}` matches interrupted UI state
- [ ] Cost reservation vs actual logged in `media_jobs`
