"""Template summary bundle for AI context (no LLM)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _section(title: str, body: str) -> str:
    text = body.strip()
    if not text:
        return ""
    return f"## {title}\n{text}"


def _format_rubrics(rubrics: Any) -> str:
    if not isinstance(rubrics, list) or not rubrics:
        return ""
    lines: list[str] = []
    for item in rubrics:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title and not description:
            continue
        if title and description:
            lines.append(f"- {title}: {description}")
        elif title:
            lines.append(f"- {title}")
        else:
            lines.append(f"- {description}")
    return "\n".join(lines)


def _format_post_metrics(metrics: Mapping[str, Any]) -> str:
    views = str(metrics.get("views") or "").strip()
    reposts = metrics.get("reposts")
    reactions = metrics.get("reactions")
    lines: list[str] = []
    if views:
        lines.append(f"Просмотры: {views}")
    if isinstance(reposts, int):
        lines.append(f"Репосты: {reposts}")
    if isinstance(reactions, list) and reactions:
        reaction_bits: list[str] = []
        for item in reactions:
            if not isinstance(item, Mapping):
                continue
            emoji = str(item.get("emoji") or "").strip()
            count = item.get("count")
            if emoji and isinstance(count, int):
                reaction_bits.append(f"{emoji} {count}")
        if reaction_bits:
            lines.append("Реакции: " + ", ".join(reaction_bits))
    return "\n".join(lines)


def build_summary_bundle(
    channel: Mapping[str, Any] | None,
    *,
    telegram: Mapping[str, Any] | None = None,
    post: Mapping[str, Any] | None = None,
) -> str:
    """Assemble channel/post summary template for the hidden primer block."""
    channel = channel or {}
    core = channel.get("core") if isinstance(channel.get("core"), Mapping) else {}
    voice = channel.get("voice") if isinstance(channel.get("voice"), Mapping) else {}
    rules = channel.get("rules") if isinstance(channel.get("rules"), Mapping) else {}

    sections: list[str] = []

    channel_lines: list[str] = []
    if isinstance(telegram, Mapping):
        title = str(telegram.get("channelTitle") or "").strip()
        handle = str(telegram.get("channel") or "").strip()
        if title:
            channel_lines.append(f"Название: {title}")
        if handle:
            channel_lines.append(f"Канал: {handle}")
    if isinstance(core, Mapping):
        for label, key in (
            ("Тема", "topic"),
            ("Аудитория", "audience"),
            ("Обещание", "promise"),
            ("Угол", "angle"),
            ("Автор", "author"),
        ):
            value = str(core.get(key) or "").strip()
            if value:
                channel_lines.append(f"{label}: {value}")
    channel_block = _section("Канал", "\n".join(channel_lines))
    if channel_block:
        sections.append(channel_block)

    voice_lines: list[str] = []
    if isinstance(voice, Mapping):
        for label, key in (("Тон", "tone"), ("Формат", "format"), ("Обращение", "phrases")):
            value = str(voice.get(key) or "").strip()
            if value:
                voice_lines.append(f"{label}: {value}")
    voice_block = _section("Голос", "\n".join(voice_lines))
    if voice_block:
        sections.append(voice_block)

    rules_lines: list[str] = []
    if isinstance(rules, Mapping):
        must = str(rules.get("must") or "").strip()
        avoid = str(rules.get("avoid") or "").strip()
        if must:
            rules_lines.append(f"Обязательно: {must}")
        if avoid:
            rules_lines.append(f"Избегать: {avoid}")
    rules_block = _section("Правила", "\n".join(rules_lines))
    if rules_block:
        sections.append(rules_block)

    rubrics_block = _section("Рубрики", _format_rubrics(channel.get("rubrics")))
    if rubrics_block:
        sections.append(rubrics_block)

    if isinstance(post, Mapping):
        post_lines: list[str] = []
        post_text = str(post.get("text") or "").strip()
        if post_text:
            post_lines.append(post_text)
        metrics = post.get("metrics")
        if isinstance(metrics, Mapping):
            metrics_text = _format_post_metrics(metrics)
            if metrics_text:
                post_lines.append("")
                post_lines.append(metrics_text)
        post_block = _section("Пост", "\n".join(post_lines))
        if post_block:
            sections.append(post_block)

    if not sections:
        return "Контекст канала пока не заполнен."
    return "\n\n".join(sections)


def post_content_fingerprint(post: Mapping[str, Any] | None) -> str:
    """Post-only fingerprint — local catalog versions bump on post edits, not channel changes."""
    payload = {
        "text": (post or {}).get("text"),
        "metrics": (post or {}).get("metrics"),
        "rubric": (post or {}).get("rubric"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def bundle_fingerprint(
    channel: Mapping[str, Any] | None,
    *,
    telegram: Mapping[str, Any] | None = None,
    post: Mapping[str, Any] | None = None,
) -> str:
    """Stable hash for bundle versioning."""
    payload = {
        "channel": channel or {},
        "telegram": telegram or {},
        "post": {
            "text": (post or {}).get("text"),
            "metrics": (post or {}).get("metrics"),
            "rubric": (post or {}).get("rubric"),
        }
        if post
        else None,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
