# 06 — Direct note lookup

- Given: запрос содержит точную ссылку на заметку.
- When: research вызывает `OpenNote`.
- Then: evidence имеет kind `note_chunk`, canonical cite path и непустой content.
- Reject: citation на неоткрытую заметку.
