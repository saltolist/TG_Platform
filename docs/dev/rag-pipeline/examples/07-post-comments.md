# 07 — Post comments

- Given: пользователь просит суммаризировать комментарии поста.
- When: retrieval открывает пост и comment evidence.
- Then: claims с фактами о комментариях ссылаются только на comment evidence ids.
- Reject: подмена комментариев текстом поста.
