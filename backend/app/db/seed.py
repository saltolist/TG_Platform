"""Idempotent database seeder for presentation and demo-full accounts."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.config import Settings, get_settings
from app.core.constants import DEMO_EMAIL, LEGACY_PRESENTATION_EMAIL, PRESENTATION_EMAIL
from app.core.security import hash_password
from app.db.models import GlobalChat, GlobalNote, Post, Profile, User
from app.db.seed_ids import seed_entity_uuid
from app.db.session import SessionLocal
from app.services.ai.model_catalog import build_seed_ai_profile

logger = logging.getLogger("tg.seed")

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
DEMO_PASSWORD = "Demo!2026"


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing fixture {path}. Run: npm run export-seed-fixtures -w tg-platform-frontend"
        )
    return json.loads(path.read_text(encoding="utf-8"))


async def _clear_user_content(session, user_id) -> None:
    await session.execute(delete(Post).where(Post.user_id == user_id))
    await session.execute(delete(GlobalChat).where(GlobalChat.user_id == user_id))
    await session.execute(delete(GlobalNote).where(GlobalNote.user_id == user_id))
    await session.execute(delete(Profile).where(Profile.user_id == user_id))


async def _seed_content(
    session,
    user_id,
    fixture: dict[str, Any],
    *,
    fixture_name: str,
    settings: Settings | None = None,
) -> None:
    for index, post in enumerate(fixture.get("posts", [])):
        seed_id = str(post["id"])
        session.add(
            Post(
                id=seed_entity_uuid("post", seed_id),
                user_id=user_id,
                position=index,
                data=post,
            )
        )

    for chat in fixture.get("globalChats", []):
        seed_id = str(chat["id"])
        session.add(
            GlobalChat(
                id=seed_entity_uuid("global_chat", seed_id),
                user_id=user_id,
                data=chat,
            )
        )

    for note in fixture.get("globalNotes", []):
        seed_id = str(note["id"])
        session.add(
            GlobalNote(
                id=seed_entity_uuid("global_note", seed_id),
                user_id=user_id,
                data=note,
            )
        )

    profile_data = dict(fixture.get("profile") or {})
    channel = profile_data.get("channel")
    ai = profile_data.get("ai")
    telegram = profile_data.get("telegram")
    if ai:
        ai = build_seed_ai_profile(fixture_name, ai, settings or get_settings())
    if channel or ai or telegram:
        session.add(
            Profile(
                user_id=user_id,
                channel=channel or None,
                ai=ai or None,
                telegram=telegram or None,
            )
        )


async def _upsert_seed_user(
    session,
    *,
    email: str,
    password: str | None,
    fixture_name: str,
    settings: Settings | None = None,
) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None and email == PRESENTATION_EMAIL:
        legacy = await session.execute(
            select(User).where(User.email == LEGACY_PRESENTATION_EMAIL)
        )
        user = legacy.scalar_one_or_none()
        if user is not None:
            user.email = PRESENTATION_EMAIL
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password or "seed-no-login"),
            is_seed=True,
        )
        session.add(user)
        await session.flush()
    else:
        user.is_seed = True
        if password:
            user.password_hash = hash_password(password)

    await _clear_user_content(session, user.id)
    await _seed_content(
        session,
        user.id,
        _load_fixture(fixture_name),
        fixture_name=fixture_name,
        settings=settings,
    )
    return user


async def run_seed(session=None, settings: Settings | None = None) -> None:
    """Seed presentation and demo accounts. Pass a session in tests to reuse the test engine."""

    async def _run(s) -> None:
        seed_settings = settings or get_settings()
        await _upsert_seed_user(
            s,
            email=PRESENTATION_EMAIL,
            password=None,
            fixture_name="presentation",
            settings=seed_settings,
        )
        await _upsert_seed_user(
            s,
            email=DEMO_EMAIL,
            password=DEMO_PASSWORD,
            fixture_name="demo-full",
            settings=seed_settings,
        )
        await s.commit()

    if session is not None:
        await _run(session)
    else:
        async with SessionLocal() as s:
            await _run(s)
    logger.info("Seed accounts ready: %s, %s", PRESENTATION_EMAIL, DEMO_EMAIL)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
