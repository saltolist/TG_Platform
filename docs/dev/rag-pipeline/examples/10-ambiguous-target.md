# 10 — Ambiguous target

- Given: несколько постов одинаково подходят под описание.
- When: verifier не может подтвердить единственную цель.
- Then: result `partial`, unresolved содержит ambiguity, mutation не предлагается.
- Reject: произвольный выбор target.
