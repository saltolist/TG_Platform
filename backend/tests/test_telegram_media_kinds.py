"""Tests for Telegram media kind classification and storage."""

from __future__ import annotations

import gzip
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from app.core.config import get_settings
from app.services.telegram.media_kinds import (
    classify_telegram_media,
    normalize_tgs_to_lottie_json,
)
from app.services.telegram.media_storage import save_message_media


def _document_media(
    *,
    mime: str = "video/mp4",
    attributes: list | None = None,
    size: int = 1024,
) -> MessageMediaDocument:
    doc = SimpleNamespace(
        id=99,
        access_hash=1,
        file_reference=b"",
        mime_type=mime,
        size=size,
        attributes=attributes or [],
    )
    return MessageMediaDocument(document=doc, nopremium=False, spoiler=False)


def _message_with_media(msg_id: int, media: object, *, mime: str = "video/mp4") -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        media=media,
        file=SimpleNamespace(mime_type=mime, name="file.bin", size=1024),
    )


def test_classify_video_note() -> None:
    media = _document_media(
        mime="video/mp4",
        attributes=[DocumentAttributeVideo(round_message=True, w=240, h=240, duration=5)],
    )
    message = _message_with_media(10, media, mime="video/mp4")
    assert classify_telegram_media(message) == "video_note"


def test_classify_static_sticker() -> None:
    media = _document_media(
        mime="image/webp",
        attributes=[DocumentAttributeSticker(alt="🔥", stickerset=SimpleNamespace(id=1, access_hash=1))],
    )
    message = _message_with_media(11, media, mime="image/webp")
    assert classify_telegram_media(message) == "sticker"


def test_classify_animated_sticker() -> None:
    media = _document_media(
        mime="application/x-tgsticker",
        attributes=[DocumentAttributeSticker(alt="😀", stickerset=SimpleNamespace(id=1, access_hash=1))],
    )
    message = _message_with_media(12, media, mime="application/x-tgsticker")
    assert classify_telegram_media(message) == "animated_sticker"


def test_classify_photo() -> None:
    message = _message_with_media(13, MessageMediaPhoto(spoiler=False, photo=SimpleNamespace()))
    assert classify_telegram_media(message) == "image"


def test_classify_voice_message() -> None:
    media = _document_media(
        mime="audio/ogg",
        attributes=[DocumentAttributeAudio(duration=12, voice=True)],
    )
    message = _message_with_media(14, media, mime="audio/ogg")
    assert classify_telegram_media(message) == "voice"


def test_classify_non_voice_audio_as_document() -> None:
    media = _document_media(
        mime="audio/mpeg",
        attributes=[DocumentAttributeAudio(duration=180, voice=False, title="Track")],
    )
    message = _message_with_media(15, media, mime="audio/mpeg")
    assert classify_telegram_media(message) == "document"


def test_normalize_tgs_to_lottie_json() -> None:
    payload = gzip.compress(json.dumps({"v": "5.5.7", "fr": 60, "layers": []}).encode("utf-8"))
    decoded = normalize_tgs_to_lottie_json(payload)
    assert json.loads(decoded.decode("utf-8"))["v"] == "5.5.7"


@pytest.mark.asyncio
async def test_save_message_media_converts_tgs_to_json(tmp_path) -> None:
    user_id = uuid4()
    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path)})
    lottie = {"v": "5.5.7", "fr": 60, "layers": []}
    tgs_bytes = gzip.compress(json.dumps(lottie).encode("utf-8"))

    media = _document_media(
        mime="application/x-tgsticker",
        attributes=[DocumentAttributeSticker(alt="🎉", stickerset=SimpleNamespace(id=1, access_hash=1))],
    )
    message = _message_with_media(42, media, mime="application/x-tgsticker")

    async def fake_download(_message: object, *, file: str) -> str:
        with open(file, "wb") as handle:
            handle.write(tgs_bytes)
        return file

    client = SimpleNamespace(download_media=fake_download)
    saved = await save_message_media(client, message, user_id, settings)
    assert saved is not None
    assert saved["kind"] == "animated_sticker"
    assert saved["type"] == "application/json"
    assert saved["url"].endswith("/42.json")
    assert (tmp_path / str(user_id) / "42.json").is_file()


@pytest.mark.asyncio
async def test_save_message_media_stores_voice_with_duration(tmp_path) -> None:
    user_id = uuid4()
    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path)})
    media = _document_media(
        mime="audio/ogg",
        attributes=[DocumentAttributeAudio(duration=9, voice=True)],
    )
    message = _message_with_media(55, media, mime="audio/ogg")

    async def fake_download(_message: object, *, file: str) -> str:
        with open(file, "wb") as handle:
            handle.write(b"voice")
        return file

    client = SimpleNamespace(download_media=fake_download)
    saved = await save_message_media(client, message, user_id, settings)
    assert saved is not None
    assert saved["kind"] == "voice"
    assert saved["type"] == "audio/ogg"
    assert saved["durationSeconds"] == 9
    assert saved["url"].endswith("/55.ogg")
