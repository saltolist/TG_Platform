"""Import @demochannel feed snapshot when a fresh account connects the demo channel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Post
from app.db.seed_ids import user_scoped_entity_uuid

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
DEMO_KANAL_FIXTURE = "demo-kanal"


def is_demo_channel_handle(channel: str) -> bool:
    handle = channel.removeprefix("@").lower()
    return handle in {"demochannel", "demokanal", "demo_kanal"}


def _load_demo_kanal_posts() -> list[dict[str, Any]]:
    path = FIXTURES_DIR / f"{DEMO_KANAL_FIXTURE}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing fixture {path}. Run: npm run export-seed-fixtures -w tg-platform-frontend"
        )
    fixture = json.loads(path.read_text(encoding="utf-8"))
    return list(fixture.get("posts", []))


async def import_demo_kanal_posts(session: AsyncSession, user_id: UUID) -> int:
    """Replace account posts with the @demochannel Telegram feed snapshot."""
    posts = _load_demo_kanal_posts()
    await session.execute(delete(Post).where(Post.user_id == user_id))
    for index, post in enumerate(posts):
        seed_id = str(post["id"])
        session.add(
            Post(
                id=user_scoped_entity_uuid(user_id, "post", seed_id),
                user_id=user_id,
                position=index,
                data=post,
            )
        )
    await session.flush()
    return len(posts)


__all__ = ["import_demo_kanal_posts", "is_demo_channel_handle"]
