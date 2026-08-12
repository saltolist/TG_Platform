# 15 — Dialog ledger invalidation

- Given: source artifact изменился после сохранённого turn.
- When: следующий run сверяет resource version.
- Then: stale evidence не используется, artifact гидратируется заново.
- Reject: grounded claim по устаревшему content.
