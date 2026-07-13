# 05 — Direct post lookup

- Given: пользователь явно указывает post id.
- When: WorkspaceAgent вызывает `OpenPost`.
- Then: ответ использует `post_text` evidence и содержит `/post/{id}/`.
- Reject: чтение чужого post id или ответ без evidence id.
