"""Tests for attachment byte resolution."""

from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.ai.attachment_fetch import resolve_attachment_bytes


@pytest.mark.asyncio
async def test_resolve_attachment_bytes_data_url() -> None:
    payload = base64.b64encode(b"hello").decode("ascii")
    url = f"data:text/plain;base64,{payload}"
    result = await resolve_attachment_bytes(url, uuid4(), Settings())
    assert result is not None
    data, mime = result
    assert data == b"hello"
    assert mime == "text/plain"


@pytest.mark.asyncio
async def test_resolve_attachment_bytes_local_media(tmp_path: Path) -> None:
    user_id = uuid4()
    media_root = tmp_path / "media"
    user_dir = media_root / str(user_id)
    user_dir.mkdir(parents=True)
    file_path = user_dir / "chart.png"
    file_path.write_bytes(b"\x89PNG")

    settings = Settings(media_storage_root=str(media_root))
    url = f"/media/{user_id}/chart.png"
    result = await resolve_attachment_bytes(url, user_id, settings)
    assert result is not None
    data, mime = result
    assert data == b"\x89PNG"
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_resolve_attachment_bytes_rejects_foreign_user() -> None:
    owner = uuid4()
    other = uuid4()
    result = await resolve_attachment_bytes(f"/media/{owner}/file.png", other, Settings())
    assert result is None


@pytest.mark.asyncio
async def test_resolve_attachment_bytes_rejects_path_traversal(tmp_path: Path) -> None:
    user_id = uuid4()
    settings = Settings(media_storage_root=str(tmp_path))
    result = await resolve_attachment_bytes(f"/media/{user_id}/../secret.png", user_id, settings)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_attachment_bytes_missing_file(tmp_path: Path) -> None:
    user_id = uuid4()
    settings = Settings(media_storage_root=str(tmp_path))
    result = await resolve_attachment_bytes(f"/media/{user_id}/missing.png", user_id, settings)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_attachment_bytes_https_unsupported() -> None:
    result = await resolve_attachment_bytes("https://example.com/file.pdf", uuid4(), Settings())
    assert result is None
