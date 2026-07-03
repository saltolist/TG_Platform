"""Tests for Telegram media fingerprinting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from app.services.telegram.media_fingerprint import (
    media_fingerprint,
    media_item_unchanged,
    media_message_id_from_item,
)

pytest.importorskip("telethon")


def test_media_fingerprint_photo() -> None:
    message = SimpleNamespace(
        id=42,
        media=MessageMediaPhoto(
            spoiler=False,
            photo=SimpleNamespace(id=1001, access_hash=1, file_reference=b""),
        ),
    )
    assert media_fingerprint(message) == "photo:1001"


def test_media_fingerprint_document() -> None:
    message = SimpleNamespace(
        id=43,
        media=MessageMediaDocument(
            document=SimpleNamespace(
                id=2002,
                access_hash=1,
                file_reference=b"",
                size=4096,
                mime_type="video/mp4",
            ),
        ),
    )
    assert media_fingerprint(message) == "doc:2002:4096:video/mp4"


def test_media_message_id_from_legacy_url() -> None:
    assert media_message_id_from_item({"url": "/media/uuid/55.webp"}) == "55"


def test_media_item_unchanged_with_matching_key(tmp_path) -> None:
    settings = SimpleNamespace(media_storage_root=str(tmp_path))
    user_id = "user-1"
    media_dir = tmp_path / user_id
    media_dir.mkdir()
    (media_dir / "10.jpg").write_bytes(b"x")

    existing = {
        "url": "/media/user-1/10.jpg",
        "mediaKey": "photo:999",
    }
    assert media_item_unchanged(existing, "photo:999", user_id, settings) is True
    assert media_item_unchanged(existing, "photo:1000", user_id, settings) is False


def test_media_item_unchanged_legacy_without_key_forces_refresh(tmp_path) -> None:
    settings = SimpleNamespace(media_storage_root=str(tmp_path))
    user_id = "user-1"
    media_dir = tmp_path / user_id
    media_dir.mkdir()
    (media_dir / "10.jpg").write_bytes(b"x")

    legacy = {"url": "/media/user-1/10.jpg"}
    assert media_item_unchanged(legacy, "photo:999", user_id, settings) is False
