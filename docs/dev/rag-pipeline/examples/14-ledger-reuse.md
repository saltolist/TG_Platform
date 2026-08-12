# 14 — Dialog ledger reuse

- Given: предыдущий turn сохранил hydrated attachment evidence.
- When: следующий вопрос относится к тому же artifact.
- Then: ledger seed повторно использует artifact без лишней hydration.
- Reject: потеря provenance или повторный fetch без необходимости.
