"""normalize post data["id"] from Telegram message_id (small int) to UUID PK

Revision ID: 018_normalize_post_uuid_ids
Revises: 017_agent_run_timezone
Create Date: 2026-07-01

Historically, posts synced from / published to Telegram stored the Telegram
message_id (a small integer like "5") in data["id"]. That collided with
authorial numbering inside note bodies ("Пост 2", "серия до 6-го"): the agent
read those numbers as real tech_ids and fabricated OpenPost calls that 404'd.

The canonical id is the opaque UUID primary key (which was always derived
deterministically from the message_id via user_scoped_entity_uuid). The
Telegram number is preserved untouched in telegramMessageId. This migration
realigns data["id"] to str(post.id) and re-keys the RAG embeddings.

Forward-only: downgrade would reintroduce the collision, so it is a no-op.
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_normalize_post_uuid_ids"
down_revision: Union[str, None] = "017_agent_run_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Every post whose data["id"] diverges from its UUID PK. Covers Telegram
    # posts (data["id"] == telegramMessageId) and any legacy rows seeded with a
    # small-int id. (user_id, old_id) is unambiguous: no user has two posts
    # sharing one small-int id, so embedding re-keying is 1:1.
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id, data->>'id' AS old_id "
            "FROM posts "
            "WHERE data ? 'id' AND data->>'id' IS DISTINCT FROM id::text"
        )
    ).fetchall()

    for row in rows:
        new_id = str(row.id)
        old_id = str(row.old_id or "")
        uid = str(row.user_id)
        if not old_id or old_id == new_id:
            continue

        # 1. Realign data["id"] to the UUID PK (jsonb_set keeps every other key).
        bind.execute(
            sa.text(
                "UPDATE posts "
                "SET data = jsonb_set(data, '{id}', to_jsonb(CAST(:new_id AS text)), true) "
                "WHERE id = :pk"
            ),
            {"new_id": new_id, "pk": new_id},
        )

        # 2. Re-key existing RAG embeddings in place; vectors are preserved,
        # only the key changes.
        #   - scope='global': post_text/media_meta nodes are keyed by the post
        #     id in BOTH note_id and post_id -> re-key both.
        #   - scope='post': note_chunk rows carry the parent post id in post_id
        #     (note_id is the note's own id, a separate namespace -> leave it).
        # Guard against a pre-existing UUID row (none today) before re-key.
        bind.execute(
            sa.text(
                "DELETE FROM note_embeddings "
                "WHERE user_id = :uid AND scope = 'global' AND note_id = :new_id "
                "AND EXISTS (SELECT 1 FROM note_embeddings "
                "WHERE user_id = :uid AND scope = 'global' AND note_id = :old_id)"
            ),
            {"uid": uid, "new_id": new_id, "old_id": old_id},
        )
        bind.execute(
            sa.text(
                "UPDATE note_embeddings SET note_id = :new_id "
                "WHERE user_id = :uid AND scope = 'global' AND note_id = :old_id"
            ),
            {"uid": uid, "new_id": new_id, "old_id": old_id},
        )
        # post_id is the parent-post reference in every scope -> re-key all.
        bind.execute(
            sa.text(
                "UPDATE note_embeddings SET post_id = :new_id "
                "WHERE user_id = :uid AND post_id = :old_id"
            ),
            {"uid": uid, "new_id": new_id, "old_id": old_id},
        )

        # 3. Same re-key for any queued (not-yet-processed) embedding jobs.
        bind.execute(
            sa.text(
                "UPDATE embedding_jobs SET note_id = :new_id "
                "WHERE user_id = :uid AND note_id = :old_id"
            ),
            {"uid": uid, "new_id": new_id, "old_id": old_id},
        )
        bind.execute(
            sa.text(
                "UPDATE embedding_jobs SET post_id = :new_id "
                "WHERE user_id = :uid AND post_id = :old_id"
            ),
            {"uid": uid, "new_id": new_id, "old_id": old_id},
        )

        # 4. Drop the stale summary_catalog entry (nested under "posts") keyed
        # by the old id. It is rebuilt lazily on the next AI reply, no data lost.
        bind.execute(
            sa.text(
                "UPDATE profiles "
                "SET summary_catalog = summary_catalog #- ARRAY['posts', :old_id] "
                "WHERE user_id = :uid "
                "AND jsonb_exists(summary_catalog->'posts', :old_id)"
            ),
            {"uid": uid, "old_id": old_id},
        )

    # 5. Purge global post_text/media_meta embeddings still keyed by a small-int
    # id with no matching live post — orphans from posts deleted before this
    # migration. Post-scoped note_chunk rows are intentionally left untouched
    # (their note_id is the note's own id namespace).
    bind.execute(
        sa.text(
            "DELETE FROM note_embeddings ne "
            "WHERE ne.scope = 'global' AND ne.note_id ~ '^[0-9]+$' "
            "AND NOT EXISTS (SELECT 1 FROM posts p "
            "WHERE p.user_id = ne.user_id AND p.data->>'id' = ne.note_id)"
        )
    )


def downgrade() -> None:
    # Reverting would reintroduce the data["id"] = telegramMessageId collision
    # that this migration exists to remove. Intentional no-op.
    pass
