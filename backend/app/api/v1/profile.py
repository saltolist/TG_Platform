from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.deps import CurrentUser, CurrentWriter, DbSession
from app.core.config import get_settings
from app.db.models import Profile
from app.core.constants import DEMO_CHANNEL_TITLE
from app.schemas.requests import RevealAiModelApiKeyRequest, RevealAiModelApiKeyResponse
from app.services.demo_channel import import_demo_kanal_posts, is_demo_channel_handle
from app.services.ai.summary_catalog import (
    catalog_from_profile,
    ensure_initial_global_version,
    register_global_summary_version,
)
from app.services.profile_defaults import (
    empty_ai_profile,
    empty_channel_profile,
    empty_telegram_profile,
)
from app.services.ai.byok_profile import (
    encrypt_profile_keys,
    mask_profile_keys,
    reveal_model_api_key_from_profile,
)

router = APIRouter(prefix="/profile", tags=["Profile"])


async def _get_or_create(session: DbSession, user_id) -> Profile:
    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)
        await session.flush()
    return profile


@router.get("/channel/")
async def get_channel(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = await session.get(Profile, user.id)
    if profile and profile.channel:
        return profile.channel
    return empty_channel_profile()


@router.put("/channel/")
async def put_channel(
    payload: dict[str, Any], user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await _get_or_create(session, user.id)
    catalog = catalog_from_profile(profile)
    telegram = profile.telegram if profile.telegram else empty_telegram_profile()
    updated_catalog, _version = register_global_summary_version(
        catalog,
        channel=payload,
        telegram=telegram,
    )
    profile.channel = payload
    profile.summary_catalog = updated_catalog
    await session.commit()
    return payload


@router.get("/ai/")
async def get_ai(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = await session.get(Profile, user.id)
    stored = profile.ai if profile and profile.ai else empty_ai_profile()
    return mask_profile_keys(stored, get_settings())


@router.post("/ai/reveal-key/", response_model=RevealAiModelApiKeyResponse)
async def reveal_ai_model_api_key(
    payload: RevealAiModelApiKeyRequest,
    user: CurrentUser,
    session: DbSession,
) -> RevealAiModelApiKeyResponse:
    profile = await session.get(Profile, user.id)
    stored = profile.ai if profile and profile.ai else {}
    settings = get_settings()
    api_key = reveal_model_api_key_from_profile(
        stored,
        model_id=payload.model_id,
        field=payload.field,
        settings=settings,
    )
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found for this model")
    return RevealAiModelApiKeyResponse(api_key=api_key)


@router.put("/ai/")
async def put_ai(payload: dict[str, Any], user: CurrentWriter, session: DbSession) -> dict[str, Any]:
    profile = await _get_or_create(session, user.id)
    previous = profile.ai or {}
    encrypted_payload = encrypt_profile_keys(payload, previous_profile=previous)
    profile.ai = encrypted_payload
    await session.commit()
    return mask_profile_keys(encrypted_payload, get_settings())


@router.get("/telegram/")
async def get_telegram(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = await session.get(Profile, user.id)
    if profile and profile.telegram:
        return profile.telegram
    return empty_telegram_profile()


@router.put("/telegram/")
async def put_telegram(
    payload: dict[str, Any], user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await _get_or_create(session, user.id)
    previous = profile.telegram or {}
    was_connected = previous.get("channelStatus") == "connected"

    profile.telegram = payload

    if (
        not was_connected
        and payload.get("channelStatus") == "connected"
        and is_demo_channel_handle(str(payload.get("channel", "")))
    ):
        count = await import_demo_kanal_posts(session, user.id)
        payload = {
            **payload,
            "importedPosts": count,
            "channelTitle": DEMO_CHANNEL_TITLE,
        }
        profile.telegram = payload

    channel = profile.channel if profile.channel else empty_channel_profile()
    telegram = profile.telegram if profile.telegram else empty_telegram_profile()
    catalog = ensure_initial_global_version(
        catalog_from_profile(profile),
        channel=channel,
        telegram=telegram,
    )
    if catalog.get("global") and catalog != catalog_from_profile(profile):
        profile.summary_catalog = catalog

    await session.commit()
    return payload
