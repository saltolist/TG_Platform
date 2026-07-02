"""Aggregate channel analytics from stored post metrics (Phase 3 / Step 5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.db.models import Post

VALID_PERIODS = frozenset({"24h", "7d", "30d", "90d", "all"})
_PERIOD_DAYS: dict[str, int | None] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}
_MAX_ALL_TIME_DAYS = 110


def parse_views_value(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return max(0, raw)
    cleaned = str(raw).replace(" ", "").replace("\xa0", "").strip()
    if not cleaned:
        return 0
    try:
        return max(0, int(cleaned))
    except ValueError:
        return 0


def sum_reactions(metrics: dict[str, Any] | None) -> int:
    if not metrics:
        return 0
    reactions = metrics.get("reactions") or []
    total = 0
    for item in reactions:
        if isinstance(item, dict):
            total += int(item.get("count") or 0)
    return total


def calc_er(views: int, reactions: int, comments: int) -> float:
    if views <= 0:
        return 0.0
    return round((reactions + comments) / views * 100, 1)


def post_title(text: str) -> str:
    line = (text.split("\n")[0] or "").strip() or "Без названия"
    if len(line) <= 72:
        return line
    return f"{line[:69]}…"


def _post_date(post: Post) -> date | None:
    raw = post.data.get("date")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def _published_posts(posts: list[Post]) -> list[Post]:
    return [post for post in posts if post.data.get("status") == "published"]


def _period_day_span(period: str, published: list[Post]) -> int:
    if period != "all":
        return _PERIOD_DAYS.get(period) or 30
    dates = [d for post in published if (d := _post_date(post)) is not None]
    if not dates:
        return 30
    earliest = min(dates)
    today = datetime.now(timezone.utc).date()
    span = (today - earliest).days + 1
    return min(max(span, 7), _MAX_ALL_TIME_DAYS)


def _posts_in_window(published: list[Post], period: str) -> list[Post]:
    if period == "all":
        return published
    day_span = _period_day_span(period, published)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=day_span - 1)
    return [
        post
        for post in published
        if (post_day := _post_date(post)) is not None and start <= post_day <= today
    ]


def _totals_from_posts(posts: list[Post]) -> dict[str, float | int]:
    views = 0
    reactions = 0
    comments = 0
    reposts = 0
    for post in posts:
        metrics = post.data.get("metrics")
        if not isinstance(metrics, dict):
            continue
        views += parse_views_value(metrics.get("views"))
        reactions += sum_reactions(metrics)
        reposts += int(metrics.get("reposts") or 0)
        comments += len(post.data.get("comments") or [])
    subscribers = max(1, round(views / 95)) if views > 0 else 0
    return {
        "subscribers": subscribers,
        "reactions": reactions,
        "views": views,
        "comments": comments,
        "reposts": reposts,
        "er": calc_er(views, reactions, comments),
    }


def aggregate_reactions(posts: list[Post]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for post in posts:
        metrics = post.data.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for item in metrics.get("reactions") or []:
            if not isinstance(item, dict):
                continue
            emoji = str(item.get("emoji") or "").strip()
            if not emoji:
                continue
            counts[emoji] = counts.get(emoji, 0) + int(item.get("count") or 0)
    return [
        {"emoji": emoji, "count": count}
        for emoji, count in sorted(counts.items(), key=lambda row: -row[1])
    ]


def build_top_posts(posts: list[Post], period: str) -> list[dict[str, Any]]:
    published = _published_posts(posts)
    window_posts = _posts_in_window(published, period)
    rows: list[dict[str, Any]] = []
    for post in window_posts:
        data = post.data
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        views = parse_views_value(metrics.get("views"))
        reactions = sum_reactions(metrics)
        reposts = int(metrics.get("reposts") or 0)
        comments = len(data.get("comments") or [])
        rows.append(
            {
                "id": str(data.get("id") or post.id),
                "title": post_title(str(data.get("text") or "")),
                "subscribers": max(1, round(views / 95)) if views > 0 else 1,
                "reactions": reactions,
                "views": views,
                "comments": comments,
                "reposts": reposts,
                "er": calc_er(views, reactions, comments),
            }
        )
    rows.sort(key=lambda row: row["views"], reverse=True)
    return rows


def build_overview(posts: list[Post], period: str) -> dict[str, Any]:
    published = _published_posts(posts)
    window_posts = _posts_in_window(published, period)
    day_span = _period_day_span(period, published)
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=day_span - 1)

    end_totals = _totals_from_posts(published)
    window_totals = _totals_from_posts(window_posts)
    start_er = max(0.0, float(end_totals["er"]) - float(window_totals["er"]))
    if start_er == 0 and int(end_totals["views"]) > int(window_totals["views"]):
        start_er = calc_er(
            max(0, int(end_totals["views"]) - int(window_totals["views"])),
            max(0, int(end_totals["reactions"]) - int(window_totals["reactions"])),
            max(0, int(end_totals["comments"]) - int(window_totals["comments"])),
        )
    start_totals = {
        "subscribers": max(0, int(end_totals["subscribers"]) - int(window_totals["subscribers"])),
        "reactions": max(0, int(end_totals["reactions"]) - int(window_totals["reactions"])),
        "views": max(0, int(end_totals["views"]) - int(window_totals["views"])),
        "comments": max(0, int(end_totals["comments"]) - int(window_totals["comments"])),
        "reposts": max(0, int(end_totals["reposts"]) - int(window_totals["reposts"])),
        "er": start_er,
    }

    days: list[dict[str, Any]] = []
    for offset in range(day_span):
        day = start_day + timedelta(days=offset)
        day_posts = [post for post in window_posts if _post_date(post) == day]
        day_totals = _totals_from_posts(day_posts)
        days.append(
            {
                "date": day.isoformat(),
                "views": int(day_totals["views"]),
                "posts": len(day_posts),
                "subscribers": int(day_totals["subscribers"]),
                "reactions": int(day_totals["reactions"]),
                "comments": int(day_totals["comments"]),
                "reposts": int(day_totals["reposts"]),
                "er": float(day_totals["er"]),
            }
        )

    return {
        "version": 1,
        "dayCount": day_span,
        "startTotals": start_totals,
        "endTotals": {key: (int(value) if key != "er" else float(value)) for key, value in end_totals.items()},
        "days": days,
        "reactions": aggregate_reactions(published),
    }
