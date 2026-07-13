# 12 — Unsupported attachment

- Given: заметка содержит неподдерживаемый attachment type.
- When: agent вызывает `HydrateAttachment`.
- Then: unresolved фиксирует тип, другие evidence остаются доступны.
- Reject: падение всего run или выдуманный текст вложения.
