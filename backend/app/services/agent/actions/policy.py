"""Action policy — all post mutations require approval."""

from __future__ import annotations

POST_MUTATION_COMMANDS = frozenset(
    {
        "create_post",
        "edit_post",
        "schedule_post",
        "publish_post",
        "cancel_schedule",
        "delete_post",
        "restore_post",
        "attach_media",
    }
)


def requires_approval(command: str) -> bool:
    return command in POST_MUTATION_COMMANDS
