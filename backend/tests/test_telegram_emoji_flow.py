"""Unit tests for Telegram emoji catalog mapping."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.telegram.emoji_flow import (
    _collection_from_sticker_set,
    _custom_collection,
    _merge_unicode_groups,
    _unicode_collection,
)


class DocumentAttributeCustomEmoji:
    def __init__(self, alt: str = "") -> None:
        self.alt = alt


def _custom_emoji_doc(doc_id: int, *, alt: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id,
        attributes=[DocumentAttributeCustomEmoji(alt=alt)] if alt else [DocumentAttributeCustomEmoji()],
    )


def test_unicode_collection_mapping() -> None:
    group = SimpleNamespace(title="Смайлы", emoticons=["😀", "😃"], icon_emoji_id=42)
    mapped = _unicode_collection(group, prefix="emoticons", index=0)
    assert mapped is not None
    assert mapped["id"] == "emoticons-0"
    assert mapped["title"] == "Смайлы"
    assert mapped["kind"] == "unicode"
    assert mapped["iconDocumentId"] == "42"
    assert mapped["items"] == [
        {"type": "unicode", "char": "😀"},
        {"type": "unicode", "char": "😃"},
    ]


def test_unicode_collection_skips_empty_groups() -> None:
    group = SimpleNamespace(title="Empty", emoticons=[], icon_emoji_id=None)
    assert _unicode_collection(group, prefix="emoticons", index=1) is None


def test_custom_collection_mapping() -> None:
    mapped = _custom_collection(
        "premium-pack",
        "Премиум",
        [100, 200],
        alt_by_id={100: "🔥"},
    )
    assert mapped is not None
    assert mapped["kind"] == "custom"
    assert mapped["items"] == [
        {"type": "custom", "documentId": "100", "alt": "🔥"},
        {"type": "custom", "documentId": "200", "alt": "⭐"},
    ]


def test_merge_unicode_groups_deduplicates_chars() -> None:
    groups = [
        SimpleNamespace(emoticons=["😀", "😃"]),
        SimpleNamespace(emoticons=["😃", "😄"]),
    ]
    merged = _merge_unicode_groups(groups)
    assert merged is not None
    assert merged["id"] == "standard"
    assert merged["kind"] == "unicode"
    assert merged["items"] == [
        {"type": "unicode", "char": "😀"},
        {"type": "unicode", "char": "😃"},
        {"type": "unicode", "char": "😄"},
    ]


def test_collection_from_sticker_set_maps_documents() -> None:
    documents = [
        _custom_emoji_doc(5368712345001, alt="🔥"),
        _custom_emoji_doc(5368712345002),
        _custom_emoji_doc(5368712345003),
    ]
    sticker_set = SimpleNamespace(
        packs=[SimpleNamespace(emoticon="🔥", documents=[0, 1])],
        documents=documents,
    )
    mapped = _collection_from_sticker_set("custom-0", "My Pack", sticker_set)
    assert mapped is not None
    assert mapped["title"] == "My Pack"
    assert mapped["kind"] == "custom"
    assert [item["documentId"] for item in mapped["items"]] == [
        "5368712345001",
        "5368712345002",
        "5368712345003",
    ]
    assert mapped["items"][0]["alt"] == "🔥"


def test_collection_from_sticker_set_resolves_document_ids_in_packs() -> None:
    documents = [
        _custom_emoji_doc(5368712345001, alt="🔥"),
        _custom_emoji_doc(5368712345002, alt="😎"),
    ]
    sticker_set = SimpleNamespace(
        packs=[SimpleNamespace(emoticon="🔥", documents=[5368712345002, 5368712345001])],
        documents=documents,
    )
    mapped = _collection_from_sticker_set("custom-1", "IDs Pack", sticker_set)
    assert mapped is not None
    assert [item["documentId"] for item in mapped["items"]] == [
        "5368712345002",
        "5368712345001",
    ]


def test_preview_payload_from_tgs_returns_json() -> None:
    import gzip
    import json

    from app.services.telegram.emoji_flow import _preview_payload_from_bytes

    payload = gzip.compress(json.dumps({"v": "5.5.7", "fr": 30, "layers": []}).encode("utf-8"))
    data, mime = _preview_payload_from_bytes(payload, "application/x-tgsticker")
    assert mime == "application/json"
    assert json.loads(data.decode("utf-8"))["v"] == "5.5.7"


def test_preview_payload_from_webm_bytes() -> None:
    from app.services.telegram.emoji_flow import _preview_payload_from_bytes

    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
    data, mime = _preview_payload_from_bytes(webm)
    assert mime == "video/webm"
    assert data == webm


def test_preview_payload_from_cached_lottie_json() -> None:
    import json

    from app.services.telegram.emoji_flow import _preview_payload_from_bytes

    payload = json.dumps({"v": "5.5.7", "fr": 30, "layers": [{}]}).encode("utf-8")
    data, mime = _preview_payload_from_bytes(payload)
    assert mime == "application/json"
    assert json.loads(data)["layers"]
