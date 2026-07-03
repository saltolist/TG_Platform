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


def test_normalize_post_for_api_preserves_existing_values() -> None:
    payload = {
        "id": "1",
        "status": "published",
        "text": "Hello",
        "rubric": "News",
        "notes": [{"id": "n1", "title": "T", "date": "d", "ai": False, "body": "b"}],
        "chats": [],
    }
    normalized = normalize_post_for_api(payload, db_id="db-fallback")
    assert normalized == payload
