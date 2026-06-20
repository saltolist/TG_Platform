"""Account-wide summary version catalog (global channel + per-post local bundles)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.ai.bundle import build_summary_bundle, bundle_fingerprint


def empty_summary_catalog() -> dict[str, Any]:
    return {"global": [], "local": {}}


def catalog_from_profile(profile: Any) -> dict[str, Any]:
    if profile is None:
        return empty_summary_catalog()
    if hasattr(profile, "summary_catalog"):
        return get_summary_catalog({"summary_catalog": getattr(profile, "summary_catalog", None)})
    if isinstance(profile, Mapping):
        return get_summary_catalog(profile)
    return empty_summary_catalog()


def normalize_catalog(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return empty_summary_catalog()
    if "global" in raw or "local" in raw:
        global_versions = raw.get("global")
        local_versions = raw.get("local")
        return {
            "global": list(global_versions) if isinstance(global_versions, list) else [],
            "local": dict(local_versions) if isinstance(local_versions, Mapping) else {},
        }
    return get_summary_catalog(raw)


def get_summary_catalog(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        return empty_summary_catalog()
    raw = profile.get("summary_catalog")
    if not isinstance(raw, Mapping):
        return empty_summary_catalog()
    global_versions = raw.get("global")
    local_versions = raw.get("local")
    return {
        "global": list(global_versions) if isinstance(global_versions, list) else [],
        "local": dict(local_versions) if isinstance(local_versions, Mapping) else {},
    }


def _latest_global(catalog: Mapping[str, Any]) -> Mapping[str, Any] | None:
    versions = catalog.get("global")
    if not isinstance(versions, list) or not versions:
        return None
    return versions[-1] if isinstance(versions[-1], Mapping) else None


def _local_versions(catalog: Mapping[str, Any], post_id: str) -> list[dict[str, Any]]:
    local = catalog.get("local")
    if not isinstance(local, Mapping):
        return []
    raw = local.get(post_id)
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def find_global_version(catalog: Mapping[str, Any], version: int) -> dict[str, Any] | None:
    for item in catalog.get("global") or []:
        if isinstance(item, Mapping) and int(item.get("version") or 0) == version:
            return dict(item)
    return None


def find_local_version(catalog: Mapping[str, Any], post_id: str, version: int) -> dict[str, Any] | None:
    for item in _local_versions(catalog, post_id):
        if int(item.get("version") or 0) == version:
            return item
    return None


def latest_global_version(catalog: Mapping[str, Any]) -> int:
    latest = _latest_global(catalog)
    if latest is None:
        return 0
    return int(latest.get("version") or 0)


def latest_local_version(catalog: Mapping[str, Any], post_id: str) -> int:
    versions = _local_versions(catalog, post_id)
    if not versions:
        return 0
    return int(versions[-1].get("version") or 0)


def register_global_summary_version(
    catalog: Mapping[str, Any] | None,
    *,
    channel: Mapping[str, Any] | None,
    telegram: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], int | None]:
    """Append a global bundle version when channel fingerprint changes. Returns (catalog, new_version|None)."""
    base = get_summary_catalog({"summary_catalog": catalog})
    text = build_summary_bundle(channel, telegram=telegram)
    fingerprint = bundle_fingerprint(channel, telegram=telegram)
    latest = _latest_global(base)
    if latest is not None and str(latest.get("fingerprint") or "") == fingerprint:
        return base, None

    next_version = latest_global_version(base) + 1
    entry = {
        "version": next_version,
        "text": text,
        "fingerprint": fingerprint,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    return {**base, "global": [*list(base.get("global") or []), entry]}, next_version


def register_local_summary_version(
    catalog: Mapping[str, Any] | None,
    *,
    post_id: str,
    channel: Mapping[str, Any] | None,
    telegram: Mapping[str, Any] | None,
    post: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], int | None]:
    """Append a post-scoped bundle version when post fingerprint changes."""
    base = get_summary_catalog({"summary_catalog": catalog})
    text = build_summary_bundle(channel, telegram=telegram, post=post)
    fingerprint = bundle_fingerprint(channel, telegram=telegram, post=post)
    versions = _local_versions(base, post_id)
    latest = versions[-1] if versions else None
    if latest is not None and str(latest.get("fingerprint") or "") == fingerprint:
        return base, None

    next_version = latest_local_version(base, post_id) + 1
    entry = {
        "version": next_version,
        "text": text,
        "fingerprint": fingerprint,
        "globalVersion": latest_global_version(base) or None,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    local = dict(base.get("local") or {})
    local[post_id] = [*versions, entry]
    return {**base, "local": local}, next_version


def resolve_bundle_text(
    catalog: Mapping[str, Any],
    *,
    scope: str,
    post_id: str | None,
    version: int,
) -> str:
    if version <= 0:
        return ""
    if scope == "post" and post_id:
        item = find_local_version(catalog, post_id, version)
    else:
        item = find_global_version(catalog, version)
    if item is None:
        return ""
    return str(item.get("text") or "").strip()


def latest_scope_version(
    catalog: Mapping[str, Any],
    *,
    scope: str,
    post_id: str | None,
) -> int:
    """Latest catalog version for the active scope (never mix global into post scope)."""
    if scope == "post" and post_id:
        return latest_local_version(catalog, post_id)
    return latest_global_version(catalog)


def ensure_post_local_catalog_current(
    catalog: Mapping[str, Any] | None,
    *,
    post_id: str,
    channel: Mapping[str, Any] | None,
    telegram: Mapping[str, Any] | None,
    post: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], int | None]:
    """Ensure ``local[post_id]`` reflects current channel+post bundle (lazy on AI reply)."""
    base = ensure_initial_global_version(
        normalize_catalog(catalog),
        channel=channel,
        telegram=telegram,
    )
    return register_local_summary_version(
        base,
        post_id=post_id,
        channel=channel,
        telegram=telegram,
        post=post,
    )


def ensure_initial_global_version(
    catalog: Mapping[str, Any] | None,
    *,
    channel: Mapping[str, Any] | None,
    telegram: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Guarantee at least global v1 exists before first AI reply."""
    base = normalize_catalog(catalog)
    if base.get("global"):
        return base
    updated, _ = register_global_summary_version(base, channel=channel, telegram=telegram)
    return updated
