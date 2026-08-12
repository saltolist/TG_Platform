# 17 — Research → draft → schedule (HITL)

| Поле | Значение |
|------|----------|
| **lanes** | `content` + `write` |
| **depth** | `agent` + `interrupt` |
| **scope** | `post` |

## Запросы

1. «Собери факты из заметок к этому посту и предложи черновик»
2. «Перепиши короче» *(без HITL — transient `PostDraftArtifact`)*
3. «Сохрани как черновик и запланируй на завтра 10:00»

## Ожидаемый pipeline

```mermaid
sequenceDiagram
  participant U as User
  participant A as WorkspaceAgent
  participant R as ResearchSubgraph
  participant P as ActionProposal
  participant E as Executor

  U->>A: turn 1
  A->>R: read tools + FinishRetrieval
  R->>A: evidence pack
  A->>U: draft in state (no DB write)
  U->>A: turn 2 rewrite
  A->>U: updated draft
  U->>A: turn 3 save+schedule
  A->>P: create + schedule proposals
  P->>U: AgentProposalCard (diff, warnings)
  U->>P: Approve
  P->>E: deterministic commands
  E->>U: post id + scheduled_at
```

## Acceptance

- [ ] Turn 1–2: zero post mutations in DB
- [ ] Turn 3: `action_proposals` с payload hash; approve идемпотентен
- [ ] Reject → agent продолжает диалог
- [ ] Concurrent edit → `resource_version` conflict
- [ ] Audit event на approve/apply
