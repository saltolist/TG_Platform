"""Aggregate channel analytics from stored post metrics (Phase 3 / Step 5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.db.models import ChannelMetricSnapshot, Post

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


def subscriber_count_from_profile(telegram: dict[str, Any] | None) -> int | None:
    """Real subscriber count synced from Telegram, or None when unknown/hidden."""
    if not telegram:
        return None
    raw = telegram.get("subscriberCount")
    if raw is None:
        return None
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


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
    return {
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
                # Per-post subscriber attribution is not available from Telegram.
                "subscribers": 0,
                "reactions": reactions,
                "views": views,
                "comments": comments,
                "reposts": reposts,
                "er": calc_er(views, reactions, comments),
            }
        )
    rows.sort(key=lambda row: row["views"], reverse=True)
    return rows


def _backfill_days(
    published: list[Post],
    window_posts: list[Post],
    start_day: date,
    day_span: int,
) -> list[dict[str, Any]]:
    """Per-day rows grouped by post publish date (used before snapshots exist)."""
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
                "subscribers": 0,
                "reactions": int(day_totals["reactions"]),
                "comments": int(day_totals["comments"]),
                "reposts": int(day_totals["reposts"]),
                "er": float(day_totals["er"]),
            }
        )
    return days


def build_overview(
    posts: list[Post],
    period: str,
    telegram: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backfill overview built from post publish dates (no snapshot history).

    Subscribers come from the real Telegram count synced to the profile; the
    per-day subscriber deltas are unknown without snapshots and stay 0.
    """
    published = _published_posts(posts)
    window_posts = _posts_in_window(published, period)
    day_span = _period_day_span(period, published)
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=day_span - 1)

    subscribers = subscriber_count_from_profile(telegram)
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
        "subscribers": subscribers or 0,
        "reactions": max(0, int(end_totals["reactions"]) - int(window_totals["reactions"])),
        "views": max(0, int(end_totals["views"]) - int(window_totals["views"])),
        "comments": max(0, int(end_totals["comments"]) - int(window_totals["comments"])),
        "reposts": max(0, int(end_totals["reposts"]) - int(window_totals["reposts"])),
        "er": start_er,
    }

    days = _backfill_days(published, window_posts, start_day, day_span)

    return {
        "version": 1,
        "dayCount": day_span,
        "startTotals": start_totals,
        "endTotals": {
            "subscribers": subscribers or 0,
            "reactions": int(end_totals["reactions"]),
            "views": int(end_totals["views"]),
            "comments": int(end_totals["comments"]),
            "reposts": int(end_totals["reposts"]),
            "er": float(end_totals["er"]),
        },
        "subscribersAvailable": subscribers is not None,
        "days": days,
        "reactions": aggregate_reactions(published),
    }


_HEATMAP_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_HEATMAP_HOURS = [9, 12, 15, 18, 21]


def build_heatmap(posts: list[Post], period: str) -> dict[str, Any]:
    """Views by weekday × publish-hour slot, normalized to levels 1–5 (UTC).

    Empty cells stay at level 1; cells with data are scaled 2–5 against the
    busiest slot in the window.
    """
    published = _published_posts(posts)
    window_posts = _posts_in_window(published, period)

    sums = [[0 for _ in _HEATMAP_HOURS] for _ in _HEATMAP_DAYS]
    for post in window_posts:
        raw = post.data.get("date")
        if not raw:
            continue
        try:
            moment = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone.utc)
        weekday = moment.weekday()
        hour_index = min(
            range(len(_HEATMAP_HOURS)),
            key=lambda i: abs(_HEATMAP_HOURS[i] - moment.hour),
        )
        metrics = post.data.get("metrics")
        views = parse_views_value(metrics.get("views")) if isinstance(metrics, dict) else 0
        sums[weekday][hour_index] += max(1, views)

    peak = max((value for row in sums for value in row), default=0)
    rows: list[dict[str, Any]] = []
    for day_index, day in enumerate(_HEATMAP_DAYS):
        values: list[int] = []
        for value in sums[day_index]:
            if value <= 0 or peak <= 0:
                values.append(1)
            else:
                values.append(2 + round((value / peak) * 3))
        rows.append({"day": day, "values": values})

    return {
        "hours": [f"{hour:02d}" for hour in _HEATMAP_HOURS],
        "rows": rows,
        "hasData": peak > 0,
    }


def _snapshot_totals(snapshot: ChannelMetricSnapshot) -> dict[str, float | int]:
    return {
        "subscribers": snapshot.subscribers,
        "views": int(snapshot.views or 0),
        "reactions": int(snapshot.reactions or 0),
        "comments": int(snapshot.comments or 0),
        "reposts": int(snapshot.reposts or 0),
        "er": float(snapshot.er or 0),
    }


def _delta_row(
    date_label: str,
    current: dict[str, float | int],
    previous: dict[str, float | int] | None,
    posts_delta: int,
) -> dict[str, Any]:
    """Growth between two cumulative snapshots (ER is a level, not a delta)."""

    def count_delta(key: str) -> int:
        cur = current.get(key)
        prev = (previous or {}).get(key)
        if cur is None or prev is None:
            return 0
        return int(cur) - int(prev)

    return {
        "date": date_label,
        "views": count_delta("views"),
        "posts": max(0, posts_delta),
        "subscribers": count_delta("subscribers"),
        "reactions": count_delta("reactions"),
        "comments": count_delta("comments"),
        "reposts": count_delta("reposts"),
        "er": float(current.get("er") or 0),
    }


def _snapshot_day_rows(
    snapshots: list[ChannelMetricSnapshot],
    start_day: date,
    end_day: date,
) -> dict[date, dict[str, Any]]:
    """Daily growth rows derived from the last snapshot of each day."""
    last_by_day: dict[date, ChannelMetricSnapshot] = {}
    for snapshot in snapshots:
        last_by_day[snapshot.captured_at.astimezone(timezone.utc).date()] = snapshot

    rows: dict[date, dict[str, Any]] = {}
    previous: ChannelMetricSnapshot | None = None
    for snapshot in snapshots:
        snap_day = snapshot.captured_at.astimezone(timezone.utc).date()
        if snap_day < start_day:
            previous = snapshot
            continue
        break

    day = start_day
    while day <= end_day:
        snapshot = last_by_day.get(day)
        if snapshot is not None:
            current = _snapshot_totals(snapshot)
            prev_totals = _snapshot_totals(previous) if previous is not None else None
            posts_delta = int(snapshot.posts_count or 0) - int(
                (previous.posts_count if previous is not None else snapshot.posts_count) or 0
            )
            rows[day] = _delta_row(day.isoformat(), current, prev_totals, posts_delta)
            previous = snapshot
        day += timedelta(days=1)
    return rows


def _snapshot_slot_rows(
    snapshots: list[ChannelMetricSnapshot],
    since: datetime,
) -> list[dict[str, Any]]:
    """30-minute growth rows for the 24h chart (one row per snapshot slot)."""
    rows: list[dict[str, Any]] = []
    previous: ChannelMetricSnapshot | None = None
    for snapshot in snapshots:
        captured = snapshot.captured_at.astimezone(timezone.utc)
        if captured < since:
            previous = snapshot
            continue
        current = _snapshot_totals(snapshot)
        prev_totals = _snapshot_totals(previous) if previous is not None else None
        posts_delta = int(snapshot.posts_count or 0) - int(
            (previous.posts_count if previous is not None else snapshot.posts_count) or 0
        )
        rows.append(_delta_row(captured.isoformat(), current, prev_totals, posts_delta))
        previous = snapshot
    return rows


def build_overview_from_history(
    posts: list[Post],
    snapshots: list[ChannelMetricSnapshot],
    period: str,
    telegram: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Overview v2: snapshot history where available, publish-date backfill before it.

    - Days before the first snapshot use the v1 grouping by post publish date.
    - Days covered by snapshots use real deltas between daily last snapshots.
    - ``24h`` uses 30-minute snapshot slots when at least two exist.
    """
    published = _published_posts(posts)
    window_posts = _posts_in_window(published, period)
    day_span = _period_day_span(period, published)
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=day_span - 1)

    snapshots = sorted(snapshots, key=lambda snap: snap.captured_at)
    subscribers_now = subscriber_count_from_profile(telegram)
    if subscribers_now is None and snapshots:
        last_subs = snapshots[-1].subscribers
        subscribers_now = int(last_subs) if last_subs is not None else None

    backfill = build_overview(posts, period, telegram)
    heatmap = build_heatmap(posts, period)

    if not snapshots:
        return {
            **backfill,
            "version": 2,
            "granularity": "day",
            "anchorDate": today.isoformat(),
            "heatmap": heatmap,
            "historySource": "publish_backfill",
        }

    first_snap_day = snapshots[0].captured_at.astimezone(timezone.utc).date()
    last_snapshot = snapshots[-1]
    last_totals = _snapshot_totals(last_snapshot)

    # 24h: use 30-minute slots once at least two snapshots cover the day.
    if period == "24h":
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        slot_rows = _snapshot_slot_rows(snapshots, since)
        if len(slot_rows) >= 2:
            in_window = [
                snap
                for snap in snapshots
                if snap.captured_at.astimezone(timezone.utc) >= since
            ]
            baseline = None
            for snap in snapshots:
                if snap.captured_at.astimezone(timezone.utc) < since:
                    baseline = snap
            baseline_totals = (
                _snapshot_totals(baseline)
                if baseline is not None
                else _snapshot_totals(in_window[0])
            )
            return {
                "version": 2,
                "dayCount": len(slot_rows),
                "granularity": "30m",
                "anchorDate": today.isoformat(),
                "startTotals": _normalize_totals(baseline_totals, subscribers_fallback=0),
                "endTotals": _normalize_totals(
                    last_totals, subscribers_fallback=subscribers_now or 0,
                    subscribers_override=subscribers_now,
                ),
                "subscribersAvailable": subscribers_now is not None,
                "days": slot_rows,
                "reactions": aggregate_reactions(published),
                "heatmap": heatmap,
                "historySource": "snapshots",
            }

    snap_rows = _snapshot_day_rows(snapshots, start_day, today)

    days: list[dict[str, Any]] = []
    used_backfill = False
    used_snapshots = False
    backfill_days: list[dict[str, Any]] = backfill["days"]
    for offset in range(day_span):
        day = start_day + timedelta(days=offset)
        snap_row = snap_rows.get(day)
        if snap_row is not None:
            days.append(snap_row)
            used_snapshots = True
        elif day < first_snap_day:
            days.append(backfill_days[offset])
            used_backfill = True
        else:
            # Snapshot-era day without a snapshot (listener down): no growth data.
            previous_er = days[-1]["er"] if days else float(backfill["startTotals"]["er"])
            days.append(
                {
                    "date": day.isoformat(),
                    "views": 0,
                    "posts": 0,
                    "subscribers": 0,
                    "reactions": 0,
                    "comments": 0,
                    "reposts": 0,
                    "er": previous_er,
                }
            )
            used_snapshots = True

    baseline = None
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    for snap in snapshots:
        if snap.captured_at.astimezone(timezone.utc) < window_start:
            baseline = snap
    if baseline is not None:
        start_totals = _normalize_totals(_snapshot_totals(baseline), subscribers_fallback=0)
    else:
        start_totals = dict(backfill["startTotals"])

    end_totals = _normalize_totals(
        last_totals,
        subscribers_fallback=subscribers_now or 0,
        subscribers_override=subscribers_now,
    )

    history_source = (
        "mixed" if used_backfill and used_snapshots
        else "snapshots" if used_snapshots
        else "publish_backfill"
    )

    return {
        "version": 2,
        "dayCount": day_span,
        "granularity": "day",
        "anchorDate": today.isoformat(),
        "startTotals": start_totals,
        "endTotals": end_totals,
        "subscribersAvailable": subscribers_now is not None,
        "days": days,
        "reactions": aggregate_reactions(published),
        "heatmap": heatmap,
        "historySource": history_source,
    }


def _normalize_totals(
    totals: dict[str, float | int],
    *,
    subscribers_fallback: int,
    subscribers_override: int | None = None,
) -> dict[str, float | int]:
    subscribers = subscribers_override
    if subscribers is None:
        raw = totals.get("subscribers")
        subscribers = int(raw) if raw is not None else subscribers_fallback
    return {
        "subscribers": subscribers,
        "reactions": int(totals.get("reactions") or 0),
        "views": int(totals.get("views") or 0),
        "comments": int(totals.get("comments") or 0),
        "reposts": int(totals.get("reposts") or 0),
        "er": float(totals.get("er") or 0),
    }
