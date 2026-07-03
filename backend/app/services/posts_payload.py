"""Normalize post JSON blobs before API responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.telegram.comments_flow import normalize_post_comments


def normalize_post_for_api(
    data: Mapping[str, Any],
    *,
    db_id: str | None = None,
) -> dict[str, Any]:
    """Ensure required Post fields exist so clients can parse the payload reliably."""
    result = dict(data)
    if not result.get("id") and db_id:
        result["id"] = db_id
    if result.get("notes") is None:
        result["notes"] = []
    if result.get("chats") is None:
        result["chats"] = []
    if result.get("text") is None:
        result["text"] = ""
    if "rubric" not in result:
        result["rubric"] = None
    if isinstance(result.get("comments"), list):
        result["comments"] = normalize_post_comments(result["comments"])
    return result


__all__ = ["normalize_post_for_api"]
