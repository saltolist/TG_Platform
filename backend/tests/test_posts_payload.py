"""Tests for post API payload normalization."""

from app.services.posts_payload import normalize_post_for_api


def test_normalize_post_for_api_fills_missing_required_fields() -> None:
    normalized = normalize_post_for_api(
        {"status": "deleted", "notes": None, "chats": None},
        db_id="4ec8f99c-4adc-5cef-a28d-349befe9ff46",
    )
    assert normalized["id"] == "4ec8f99c-4adc-5cef-a28d-349befe9ff46"
    assert normalized["notes"] == []
    assert normalized["chats"] == []
    assert normalized["text"] == ""
    assert normalized["rubric"] is None


def test_normalize_post_for_api_preserves_existing_values_except_id() -> None:
    payload = {
        "id": "1",
        "status": "published",
        "text": "Hello",
        "rubric": "News",
        "notes": [{"id": "n1", "title": "T", "date": "d", "ai": False, "body": "b"}],
        "chats": [],
    }
    normalized = normalize_post_for_api(payload, db_id="db-fallback")
    assert normalized == {**payload, "id": "db-fallback"}


def test_normalize_post_for_api_id_always_reflects_uuid_pk() -> None:
    """``id`` must be the UUID PK even when data['id'] is a legacy numeric id —
    that legacy field stays the RAG partition key internally and must never
    leak to clients, or a stale value survives a Telegram re-sync and clients
    address a post no resolver can find (chat d395d1ef)."""
    normalized = normalize_post_for_api(
        {"id": "3", "status": "draft"},
        db_id="77c8aef2-d9d9-4578-8d3a-59eb5dbfbda7",
    )
    assert normalized["id"] == "77c8aef2-d9d9-4578-8d3a-59eb5dbfbda7"


def test_normalize_post_for_api_infers_sticker_kind_for_imported_webp() -> None:
    normalized = normalize_post_for_api(
        {
            "id": "1",
            "status": "published",
            "media": [
                {
                    "name": "42.webp",
                    "url": "/media/user/42.webp",
                    "type": "image/webp",
                }
            ],
        }
    )
    assert normalized["media"][0]["kind"] == "sticker"
