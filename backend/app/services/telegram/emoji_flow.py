"""Fetch Telegram emoji catalogs and custom-emoji previews via user MTProto session."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings
from app.db.models import Profile
from app.services.telegram.media_kinds import TGS_MIME_TYPES, normalize_tgs_to_lottie_json
from app.services.telegram.net import (
    TelegramAuthError,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.writer_session import open_outbound_telegram_client

logger = logging.getLogger(__name__)

_CATALOG_TTL_SECONDS = 300
_CATALOG_SCHEMA_VERSION = 4
_catalog_cache: dict[UUID, tuple[float, int, dict[str, Any]]] = {}
_catalog_inflight: dict[UUID, asyncio.Task[dict[str, Any]]] = {}
_PREVIEW_BATCH_SIZE = 100


def _str_id(value: Any) -> str | None:
    if value in (None, "", 0):
        return None
    return str(value)


def _unicode_collection(group: Any, *, prefix: str, index: int) -> dict[str, Any] | None:
    emoticons = list(getattr(group, "emoticons", None) or [])
    if not emoticons:
        return None
    title = str(getattr(group, "title", None) or "Эмодзи").strip() or "Эмодзи"
    return {
        "id": f"{prefix}-{index}",
        "title": title,
        "kind": "unicode",
        "iconDocumentId": _str_id(getattr(group, "icon_emoji_id", None)),
        "items": [{"type": "unicode", "char": char} for char in emoticons if char],
    }


def _merge_unicode_groups(groups: list[Any]) -> dict[str, Any] | None:
    """Merge Telegram unicode categories into one standard picker collection."""
    items: list[dict[str, str]] = []
    seen_chars: set[str] = set()
    for group in groups:
        emoticons = list(getattr(group, "emoticons", None) or [])
        if not emoticons:
            continue
        for char in emoticons:
            if not char or char in seen_chars:
                continue
            seen_chars.add(char)
            items.append({"type": "unicode", "char": char})
    if not items:
        return None
    return {
        "id": "standard",
        "title": "Смайлы",
        "kind": "unicode",
        "items": items,
    }


def _is_document_empty(document: Any) -> bool:
    return type(document).__name__ == "DocumentEmpty"


def _is_custom_emoji_document(document: Any) -> bool:
    if _is_document_empty(document):
        return False
    for attr in list(getattr(document, "attributes", None) or []):
        if type(attr).__name__ == "DocumentAttributeCustomEmoji":
            return True
    return False


def _sticker_set_meta(sticker_set: Any) -> Any:
    return getattr(sticker_set, "set", None) or sticker_set


def _resolve_pack_document(documents: list[Any], by_id: dict[int, Any], ref: int) -> Any | None:
    """Resolve stickerPack.documents entry — Telegram uses document IDs (index fallback for tests)."""
    if ref in by_id:
        return by_id[ref]
    if 0 <= ref < len(documents):
        candidate = documents[ref]
        if not _is_document_empty(candidate):
            return candidate
    return None


def _collection_from_sticker_set(
    collection_id: str,
    title: str,
    sticker_set: Any,
) -> dict[str, Any] | None:
    documents = list(getattr(sticker_set, "documents", None) or [])
    if not documents:
        return None

    by_id: dict[int, Any] = {}
    for document in documents:
        if _is_document_empty(document):
            continue
        doc_key = int(getattr(document, "id", 0) or 0)
        if doc_key:
            by_id[doc_key] = document

    alt_by_id: dict[int, str] = {}
    document_ids: list[int] = []
    seen: set[int] = set()

    def add_document(document: Any, alt: str) -> None:
        if not _is_custom_emoji_document(document):
            return
        doc_key = int(getattr(document, "id", 0) or 0)
        if not doc_key or doc_key in seen:
            return
        seen.add(doc_key)
        document_ids.append(doc_key)
        alt_by_id.setdefault(doc_key, alt or "⭐")

    def alt_from_document(document: Any, fallback: str) -> str:
        for attr in list(getattr(document, "attributes", None) or []):
            alt_value = getattr(attr, "alt", None)
            if alt_value:
                return str(alt_value)
        return fallback

    for pack in list(getattr(sticker_set, "packs", None) or []):
        emoticon = str(getattr(pack, "emoticon", None) or "⭐")
        for ref in list(getattr(pack, "documents", None) or []):
            document = _resolve_pack_document(documents, by_id, int(ref))
            if document is not None:
                add_document(document, alt_from_document(document, emoticon))

    for document in documents:
        add_document(document, alt_from_document(document, "⭐"))

    return _custom_collection(collection_id, title, document_ids, alt_by_id=alt_by_id)


def _custom_collection(
    collection_id: str,
    title: str,
    document_ids: list[int],
    *,
    alt_by_id: dict[int, str] | None = None,
) -> dict[str, Any] | None:
    items: list[dict[str, str]] = []
    alt_map = alt_by_id or {}
    for doc_id in document_ids:
        doc_key = int(doc_id)
        items.append(
            {
                "type": "custom",
                "documentId": str(doc_key),
                "alt": alt_map.get(doc_key) or "⭐",
            }
        )
    if not items:
        return None
    return {
        "id": collection_id,
        "title": title,
        "kind": "custom",
        "items": items,
    }


async def _fetch_standard_unicode_collection(client: Any) -> dict[str, Any] | None:
    from telethon.tl.functions.messages import GetEmojiGroupsRequest

    try:
        result = await client(GetEmojiGroupsRequest(hash=0))
    except Exception:
        logger.debug("GetEmojiGroups failed", exc_info=True)
        return None
    groups = list(getattr(result, "groups", None) or [])
    return _merge_unicode_groups(groups)


async def _fetch_installed_custom_collections(client: Any) -> list[dict[str, Any]]:
    """User-installed custom emoji sticker sets — one picker tab per set."""
    from telethon.tl.functions.messages import GetEmojiStickersRequest, GetStickerSetRequest
    from telethon.tl.types import InputStickerSetID

    try:
        result = await client(GetEmojiStickersRequest(hash=0))
    except Exception:
        logger.debug("GetEmojiStickers failed", exc_info=True)
        return []

    sets = list(getattr(result, "sets", None) or [])

    async def load_collection(index: int, sticker_set: Any) -> dict[str, Any] | None:
        meta = _sticker_set_meta(sticker_set)
        set_id = getattr(meta, "id", None)
        access_hash = getattr(meta, "access_hash", None)
        title = str(getattr(meta, "title", None) or "Набор").strip() or "Набор"
        if set_id is None or access_hash is None:
            return None
        try:
            full = await client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetID(id=int(set_id), access_hash=int(access_hash)),
                    hash=0,
                )
            )
        except Exception:
            logger.debug("GetStickerSet failed for installed set %s", title, exc_info=True)
            return None
        return _collection_from_sticker_set(f"custom-installed-{index}", title, full)

    loaded = await asyncio.gather(
        *(load_collection(index, sticker_set) for index, sticker_set in enumerate(sets)),
        return_exceptions=True,
    )

    collections: list[dict[str, Any]] = []
    for item in loaded:
        if isinstance(item, Exception) or item is None:
            continue
        collections.append(item)
    return collections


async def _fetch_emoji_catalog(client: Any) -> dict[str, Any]:
    collections: list[dict[str, Any]] = []

    standard = await _fetch_standard_unicode_collection(client)
    if standard is not None:
        collections.append(standard)

    collections.extend(await _fetch_installed_custom_collections(client))

    if not collections:
        collections.append(
            {
                "id": "unicode-fallback",
                "title": "Смайлы",
                "kind": "unicode",
                "items": [
                    {"type": "unicode", "char": char}
                    for char in ["😀", "😂", "❤️", "👍", "🔥", "🎉", "🙏", "✨"]
                ],
            }
        )

    return {"collections": collections}


async def fetch_emoji_catalog_for_user(
    profile: Profile, user_id: UUID, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    telegram = profile.telegram or {}
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

    cached = _catalog_cache.get(user_id)
    if cached is not None:
        cached_at, schema_version, cached_catalog = cached
        if (
            schema_version == _CATALOG_SCHEMA_VERSION
            and time.monotonic() - cached_at < _CATALOG_TTL_SECONDS
        ):
            return cached_catalog

    inflight = _catalog_inflight.get(user_id)
    if inflight is not None:
        return await inflight

    async def _load_catalog() -> dict[str, Any]:
        async with open_outbound_telegram_client(profile, user_id, settings) as (client, _telegram):
            return await with_timeout(_fetch_emoji_catalog(client), settings)

    task = asyncio.create_task(_load_catalog())
    _catalog_inflight[user_id] = task
    try:
        catalog = await task
    finally:
        _catalog_inflight.pop(user_id, None)

    _catalog_cache[user_id] = (time.monotonic(), _CATALOG_SCHEMA_VERSION, catalog)
    custom_count = sum(1 for c in catalog.get("collections", []) if c.get("kind") == "custom")
    logger.info(
        "Emoji catalog loaded for user %s: %s collections (%s custom)",
        user_id,
        len(catalog.get("collections", [])),
        custom_count,
    )
    return catalog


_PREVIEW_CACHE_SCHEMA = 3


def _preview_cache_path(user_id: UUID, document_id: str, settings: Settings) -> Path:
    root = Path(settings.media_storage_root) / str(user_id) / f"emoji-cache-v{_PREVIEW_CACHE_SCHEMA}"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{document_id}.bin"


def _preview_cache_valid(user_id: UUID, document_id: str, settings: Settings) -> bool:
    cache_path = _preview_cache_path(user_id, document_id, settings)
    if not cache_path.is_file():
        return False
    try:
        _preview_payload_from_bytes(cache_path.read_bytes())
        return True
    except ValueError:
        cache_path.unlink(missing_ok=True)
        return False


async def _cache_document_preview(
    client: Any, user_id: UUID, settings: Settings, document: Any
) -> None:
    doc_id = int(getattr(document, "id", 0) or 0)
    if not doc_id:
        return
    document_id = str(doc_id)
    if _preview_cache_valid(user_id, document_id, settings):
        return

    mime = str(getattr(document, "mime_type", None) or "")
    data = await client.download_media(document, bytes)
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError(f"empty preview for emoji {doc_id}")

    payload, _content_type = _preview_payload_from_bytes(bytes(data), mime)
    cache_path = _preview_cache_path(user_id, document_id, settings)
    cache_path.write_bytes(payload)


async def _warm_custom_emoji_previews(
    client: Any, user_id: UUID, settings: Settings, document_ids: list[int]
) -> None:
    if not document_ids:
        return

    from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest

    missing = [
        doc_id
        for doc_id in dict.fromkeys(document_ids)
        if not _preview_cache_valid(user_id, str(doc_id), settings)
    ]
    if not missing:
        return

    for offset in range(0, len(missing), _PREVIEW_BATCH_SIZE):
        batch = missing[offset : offset + _PREVIEW_BATCH_SIZE]
        try:
            documents = await client(GetCustomEmojiDocumentsRequest(document_id=batch))
        except Exception:
            logger.debug("GetCustomEmojiDocuments batch failed", exc_info=True)
            continue

        docs_by_id = {
            int(getattr(document, "id", 0)): document
            for document in documents
            if not _is_document_empty(document) and getattr(document, "id", None)
        }
        for doc_id in batch:
            document = docs_by_id.get(doc_id)
            if document is None:
                continue
            try:
                await _cache_document_preview(client, user_id, settings, document)
            except Exception:
                logger.debug("preview cache failed for %s", doc_id, exc_info=True)


def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if data[:1] == b"{":
        return "application/json"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"GIF"):
        return "image/gif"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "application/octet-stream"


def _preview_payload_from_bytes(raw: bytes, mime: str = "") -> tuple[bytes, str]:
    normalized_mime = mime.lower()
    if normalized_mime in TGS_MIME_TYPES or raw[:2] == b"\x1f\x8b":
        try:
            return normalize_tgs_to_lottie_json(raw), "application/json"
        except ValueError:
            logger.debug("Failed to decode TGS custom emoji preview", exc_info=True)
            raise
    if normalized_mime.startswith("video/"):
        return raw, normalized_mime
    if normalized_mime.startswith("image/"):
        return raw, normalized_mime
    if normalized_mime == "application/json":
        return raw, "application/json"

    guessed = _guess_mime(raw)
    if guessed == "application/gzip":
        try:
            return normalize_tgs_to_lottie_json(raw), "application/json"
        except ValueError:
            logger.debug("Failed to decode TGS custom emoji preview", exc_info=True)
            raise
    if guessed != "application/octet-stream":
        return raw, guessed
    return raw, normalized_mime or guessed


async def fetch_custom_emoji_preview_bytes(
    profile: Profile, user_id: UUID, document_id: str, settings: Settings | None = None
) -> tuple[bytes, str]:
    settings = settings or get_settings()
    telegram = profile.telegram or {}
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

    try:
        doc_id = int(document_id)
    except ValueError as exc:
        raise TelegramAuthError("Некорректный emoji id", 400) from exc

    cache_path = _preview_cache_path(user_id, document_id, settings)
    if _preview_cache_valid(user_id, document_id, settings):
        return _preview_payload_from_bytes(cache_path.read_bytes())

    async with open_outbound_telegram_client(profile, user_id, settings) as (client, _telegram):
        from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest

        documents = await with_timeout(
            client(GetCustomEmojiDocumentsRequest(document_id=[doc_id])), settings
        )
        if not documents:
            raise TelegramAuthError("Эмодзи не найден", 404)
        document = documents[0]
        await _cache_document_preview(client, user_id, settings, document)

    return _preview_payload_from_bytes(cache_path.read_bytes())


__all__ = [
    "fetch_custom_emoji_preview_bytes",
    "fetch_emoji_catalog_for_user",
]
