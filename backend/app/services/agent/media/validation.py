"""Media asset validation."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class AssetValidationResult:
    ok: bool
    mime_type: str
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    error: str | None = None


ALLOWED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
ALLOWED_VIDEO_MIMES = frozenset({"video/mp4", "video/webm"})


def validate_image_bytes(data: bytes, *, declared_mime: str = "") -> AssetValidationResult:
    if not data:
        return AssetValidationResult(ok=False, mime_type=declared_mime, error="empty_bytes")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = str(image.format or "").lower()
            width, height = image.size
    except Exception:
        return AssetValidationResult(
            ok=False,
            mime_type=declared_mime,
            error="invalid_image_bytes",
        )
    mime = declared_mime or f"image/{image_format}"
    if mime not in ALLOWED_IMAGE_MIMES:
        return AssetValidationResult(ok=False, mime_type=mime, error="unsupported_image_mime")
    return AssetValidationResult(ok=True, mime_type=mime, width=width, height=height)


def validate_video_bytes(
    data: bytes,
    *,
    declared_mime: str,
    max_duration_sec: float | None = None,
    duration_sec: float | None = None,
) -> AssetValidationResult:
    if not data:
        return AssetValidationResult(ok=False, mime_type=declared_mime, error="empty_bytes")
    if declared_mime not in ALLOWED_VIDEO_MIMES:
        return AssetValidationResult(ok=False, mime_type=declared_mime, error="unsupported_video_mime")
    if declared_mime == "video/mp4" and b"ftyp" not in data[:64]:
        return AssetValidationResult(ok=False, mime_type=declared_mime, error="invalid_video_bytes")
    if declared_mime == "video/webm" and not data.startswith(b"\x1a\x45\xdf\xa3"):
        return AssetValidationResult(ok=False, mime_type=declared_mime, error="invalid_video_bytes")
    if max_duration_sec and duration_sec and duration_sec > max_duration_sec:
        return AssetValidationResult(
            ok=False,
            mime_type=declared_mime,
            duration_sec=duration_sec,
            error="duration_exceeds_limit",
        )
    return AssetValidationResult(ok=True, mime_type=declared_mime, duration_sec=duration_sec)
