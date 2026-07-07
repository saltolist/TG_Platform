"""Aggregate channel analytics from stored post metrics (Phase 3 / Step 5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from uuid import UUID

from app.db.models import ChannelMetricSnapshot, Post, PostMetricSnapshot

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


def _post_snapshot_values(snapshot: PostMetricSnapshot) -> dict[str, int]:
    return {
        "views": int(snapshot.views or 0),
        "reactions": int(snapshot.reactions or 0),
        "comments": int(snapshot.comments or 0),
        "reposts": int(snapshot.reposts or 0),
    }


def _group_post_snapshots_by_post(
    post_snapshots: list[PostMetricSnapshot],
) -> dict[UUID, list[PostMetricSnapshot]]:
    grouped: dict[UUID, list[PostMetricSnapshot]] = {}
    for snapshot in sorted(post_snapshots, key=lambda row: row.captured_at):
        grouped.setdefault(snapshot.post_id, []).append(snapshot)
    return grouped


def _latest_post_snapshot_at_or_before(
    snapshots: list[PostMetricSnapshot],
    moment: datetime,
) -> PostMetricSnapshot | None:
    latest: PostMetricSnapshot | None = None
    for snapshot in snapshots:
        if snapshot.captured_at.astimezone(timezone.utc) <= moment:
            latest = snapshot
        else:
            break
    return latest


def _post_totals_at_moment(
    by_post: dict[UUID, list[PostMetricSnapshot]],
    moment: datetime,
) -> dict[str, int]:
    totals = {"views": 0, "reactions": 0, "comments": 0, "reposts": 0}
    for snapshots in by_post.values():
        latest = _latest_post_snapshot_at_or_before(snapshots, moment)
        if latest is None:
            continue
        values = _post_snapshot_values(latest)
        for key in totals:
            totals[key] += values[key]
    return totals


def _posts_published_on_day(published: list[Post], day: date) -> int:
    return sum(1 for post in published if _post_date(post) == day)


def _floor_to_slot(moment: datetime, minutes: int = 30) -> datetime:
    """Round *moment* down to a fixed-width slot boundary (mirrors snapshot capture)."""
    minute = (moment.minute // minutes) * minutes
    return moment.replace(minute=minute, second=0, microsecond=0)


def _subscribers_before_moment(
    moment: datetime,
    channel_snapshots: list[ChannelMetricSnapshot],
) -> int:
    """Subscriber count as of just before *moment* — always from channel snapshots.

    Subscriber count only ever comes from a Telethon call made during a
    scheduled snapshot capture (there is no continuous live source for it,
    unlike views/reactions), so it stays tied to snapshot cadence.
    """
    baseline: ChannelMetricSnapshot | None = None
    for snap in channel_snapshots:
        if snap.captured_at.astimezone(timezone.utc) < moment:
            baseline = snap
    if baseline is None or baseline.subscribers is None:
        return 0
    return int(baseline.subscribers)


def _totals_before_moment(
    moment: datetime,
    by_post: dict[UUID, list[PostMetricSnapshot]],
    channel_snapshots: list[ChannelMetricSnapshot],
) -> dict[str, int]:
    """Baseline counts as of just before *moment* — per-post history first, legacy fallback."""
    if by_post:
        return _post_totals_at_moment(by_post, moment - timedelta(microseconds=1))
    baseline: ChannelMetricSnapshot | None = None
    for snap in channel_snapshots:
        if snap.captured_at.astimezone(timezone.utc) < moment:
            baseline = snap
    if baseline is None:
        return {"views": 0, "reactions": 0, "comments": 0, "reposts": 0}
    totals = _snapshot_totals(baseline)
    return {
        "views": int(totals["views"]),
        "reactions": int(totals["reactions"]),
        "comments": int(totals["comments"]),
        "reposts": int(totals["reposts"]),
    }


def _delta_row_from_post_totals(
    date_label: str,
    current: dict[str, int],
    previous: dict[str, int] | None,
    posts_delta: int,
) -> dict[str, Any]:
    prev = previous or {}
    view_delta = current["views"] - int(prev.get("views") or 0)
    reaction_delta = current["reactions"] - int(prev.get("reactions") or 0)
    comment_delta = current["comments"] - int(prev.get("comments") or 0)
    repost_delta = current["reposts"] - int(prev.get("reposts") or 0)
    return {
        "date": date_label,
        "views": view_delta,
        "posts": max(0, posts_delta),
        "subscribers": 0,
        "reactions": reaction_delta,
        "comments": comment_delta,
        "reposts": repost_delta,
        "er": calc_er(view_delta, reaction_delta, comment_delta),
    }


def _delta_row(
    date_label: str,
    current: dict[str, float | int],
    previous: dict[str, float | int] | None,
    posts_delta: int,
) -> dict[str, Any]:
    """Growth between two cumulative channel snapshots (ER is a level, not a delta).

    A missing *previous* snapshot means "no earlier baseline in range" (e.g. the
    first tracked day), not "no growth" — treat it as a zero baseline so counts
    grow from 0, matching ``_delta_row_from_post_totals``. A missing *current*
    value still means "unknown for this metric" and stays 0.
    """

    def count_delta(key: str) -> int:
        cur = current.get(key)
        if cur is None:
            return 0
        prev = (previous or {}).get(key) or 0
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


def _post_snapshot_day_rows(
    by_post: dict[UUID, list[PostMetricSnapshot]],
    published: list[Post],
    start_day: date,
    end_day: date,
) -> dict[date, dict[str, Any]]:
    """Daily growth from per-post snapshot deltas summed into channel totals."""
    rows: dict[date, dict[str, Any]] = {}
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    previous_totals = _post_totals_at_moment(by_post, window_start - timedelta(microseconds=1))

    day = start_day
    while day <= end_day:
        end_of_day = datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc)
        current_totals = _post_totals_at_moment(by_post, end_of_day)
        rows[day] = _delta_row_from_post_totals(
            day.isoformat(),
            current_totals,
            previous_totals,
            _posts_published_on_day(published, day),
        )
        previous_totals = current_totals
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


def _post_snapshot_slot_rows(
    by_post: dict[UUID, list[PostMetricSnapshot]],
    post_snapshots: list[PostMetricSnapshot],
    since: datetime,
) -> list[dict[str, Any]]:
    """30-minute growth rows aggregated from per-post snapshots."""
    slot_times = sorted(
        {
            snapshot.captured_at.astimezone(timezone.utc)
            for snapshot in post_snapshots
            if snapshot.captured_at.astimezone(timezone.utc) >= since
        }
    )
    if not slot_times:
        return []

    rows: list[dict[str, Any]] = []
    previous_totals = _post_totals_at_moment(by_post, since - timedelta(microseconds=1))
    for slot in slot_times:
        current_totals = _post_totals_at_moment(by_post, slot)
        rows.append(
            _delta_row_from_post_totals(
                slot.isoformat(),
                current_totals,
                previous_totals,
                0,
            )
        )
        previous_totals = current_totals
    return rows


def _tracking_since(
    channel_snapshots: list[ChannelMetricSnapshot],
    post_snapshots: list[PostMetricSnapshot],
) -> str | None:
    dates: list[date] = []
    if channel_snapshots:
        dates.append(channel_snapshots[0].captured_at.astimezone(timezone.utc).date())
    if post_snapshots:
        dates.append(post_snapshots[0].captured_at.astimezone(timezone.utc).date())
    if not dates:
        return None
    return min(dates).isoformat()


def _start_totals_from_window(
    published: list[Post],
    period: str,
    subscribers: int | None,
) -> dict[str, float | int]:
    window_posts = _posts_in_window(published, period)
    end_totals = _totals_from_posts(published)
    window_totals = _totals_from_posts(window_posts)
    start_er = max(0.0, float(end_totals["er"]) - float(window_totals["er"]))
    if start_er == 0 and int(end_totals["views"]) > int(window_totals["views"]):
        start_er = calc_er(
            max(0, int(end_totals["views"]) - int(window_totals["views"])),
            max(0, int(end_totals["reactions"]) - int(window_totals["reactions"])),
            max(0, int(end_totals["comments"]) - int(window_totals["comments"])),
        )
    return {
        "subscribers": subscribers or 0,
        "reactions": max(0, int(end_totals["reactions"]) - int(window_totals["reactions"])),
        "views": max(0, int(end_totals["views"]) - int(window_totals["views"])),
        "comments": max(0, int(end_totals["comments"]) - int(window_totals["comments"])),
        "reposts": max(0, int(end_totals["reposts"]) - int(window_totals["reposts"])),
        "er": start_er,
    }


def _zeroed_period_days(start_day: date, day_span: int) -> list[dict[str, Any]]:
    return [
        {
            "date": (start_day + timedelta(days=offset)).isoformat(),
            "views": 0,
            "posts": 0,
            "subscribers": 0,
            "reactions": 0,
            "comments": 0,
            "reposts": 0,
            "er": 0.0,
        }
        for offset in range(day_span)
    ]


def _merge_subscriber_deltas(
    days: list[dict[str, Any]],
    channel_snap_rows: dict[date, dict[str, Any]],
) -> None:
    for row in days:
        day = date.fromisoformat(str(row["date"])[:10])
        channel_row = channel_snap_rows.get(day)
        if channel_row is not None:
            row["subscribers"] = int(channel_row.get("subscribers") or 0)


def build_overview_from_history(
    posts: list[Post],
    channel_snapshots: list[ChannelMetricSnapshot],
    post_snapshots: list[PostMetricSnapshot],
    period: str,
    telegram: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Overview v2: per-post snapshot deltas with legacy channel-snapshot fallback."""
    published = _published_posts(posts)
    day_span = _period_day_span(period, published)
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=day_span - 1)
    heatmap = build_heatmap(posts, period)

    channel_snapshots = sorted(channel_snapshots, key=lambda snap: snap.captured_at)
    post_snapshots = sorted(post_snapshots, key=lambda snap: snap.captured_at)
    by_post = _group_post_snapshots_by_post(post_snapshots)

    subscribers_now = subscriber_count_from_profile(telegram)
    if subscribers_now is None and channel_snapshots:
        last_subs = channel_snapshots[-1].subscribers
        subscribers_now = int(last_subs) if last_subs is not None else None

    end_post_totals = _totals_from_posts(published)
    end_totals = _normalize_totals(
        end_post_totals,
        subscribers_fallback=subscribers_now or 0,
        subscribers_override=subscribers_now,
    )
    tracking_since = _tracking_since(channel_snapshots, post_snapshots)

    if not channel_snapshots and not post_snapshots:
        start_totals = _start_totals_from_window(published, period, subscribers_now)
        return {
            "version": 2,
            "dayCount": day_span,
            "granularity": "day",
            "anchorDate": today.isoformat(),
            "startTotals": start_totals,
            "endTotals": end_totals,
            "subscribersAvailable": subscribers_now is not None,
            "days": _zeroed_period_days(start_day, day_span),
            "reactions": aggregate_reactions(published),
            "heatmap": heatmap,
            "historySource": "no_history",
            "trackingSince": None,
        }

    first_post_snap_day = (
        post_snapshots[0].captured_at.astimezone(timezone.utc).date()
        if post_snapshots
        else None
    )
    channel_snap_rows = _snapshot_day_rows(channel_snapshots, start_day, today)
    post_snap_rows = (
        _post_snapshot_day_rows(by_post, published, start_day, today)
        if post_snapshots
        else {}
    )

    if period == "24h":
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        if post_snapshots:
            slot_rows = _post_snapshot_slot_rows(by_post, post_snapshots, since)
            history_source = "post_snapshots"
        else:
            slot_rows = _snapshot_slot_rows(channel_snapshots, since)
            history_source = "legacy_channel_snapshots"

        # The most recent slot is always rebuilt from live post data so growth
        # shows up immediately, without waiting for the next scheduled capture.
        now = datetime.now(timezone.utc)
        current_slot_start = _floor_to_slot(now)
        live_slot_row = _delta_row_from_post_totals(
            now.isoformat(),
            end_post_totals,
            _totals_before_moment(current_slot_start, by_post, channel_snapshots),
            0,
        )
        live_slot_row["subscribers"] = (subscribers_now or 0) - _subscribers_before_moment(
            current_slot_start, channel_snapshots
        )
        # ER is always the channel's current overall level (matches endTotals
        # and the legacy convention), not a delta computed for just this slot.
        live_slot_row["er"] = float(end_post_totals["er"])
        if slot_rows and datetime.fromisoformat(str(slot_rows[-1]["date"])) >= current_slot_start:
            slot_rows[-1] = live_slot_row
        else:
            slot_rows.append(live_slot_row)

        if len(slot_rows) >= 2:
            baseline_moment = since - timedelta(microseconds=1)
            if post_snapshots:
                baseline_totals = _post_totals_at_moment(by_post, baseline_moment)
                start_totals = _normalize_totals(baseline_totals, subscribers_fallback=0)
            else:
                baseline = None
                for snap in channel_snapshots:
                    if snap.captured_at.astimezone(timezone.utc) < since:
                        baseline = snap
                in_window = [
                    snap
                    for snap in channel_snapshots
                    if snap.captured_at.astimezone(timezone.utc) >= since
                ]
                baseline_totals = (
                    _snapshot_totals(baseline)
                    if baseline is not None
                    else _snapshot_totals(in_window[0])
                )
                start_totals = _normalize_totals(baseline_totals, subscribers_fallback=0)

            return {
                "version": 2,
                "dayCount": len(slot_rows),
                "granularity": "30m",
                "anchorDate": today.isoformat(),
                "startTotals": start_totals,
                "endTotals": end_totals,
                "subscribersAvailable": subscribers_now is not None,
                "days": slot_rows,
                "reactions": aggregate_reactions(published),
                "heatmap": heatmap,
                "historySource": history_source,
                "trackingSince": tracking_since,
            }

    days: list[dict[str, Any]] = []
    used_legacy = False
    used_post = False
    for offset in range(day_span):
        day = start_day + timedelta(days=offset)
        use_post = first_post_snap_day is not None and day >= first_post_snap_day
        if use_post and day in post_snap_rows:
            days.append(dict(post_snap_rows[day]))
            used_post = True
        elif day in channel_snap_rows:
            days.append(dict(channel_snap_rows[day]))
            used_legacy = True
        elif use_post:
            days.append(
                {
                    "date": day.isoformat(),
                    "views": 0,
                    "posts": 0,
                    "subscribers": 0,
                    "reactions": 0,
                    "comments": 0,
                    "reposts": 0,
                    "er": 0.0,
                }
            )
            used_post = True
        else:
            days.append(
                {
                    "date": day.isoformat(),
                    "views": 0,
                    "posts": 0,
                    "subscribers": 0,
                    "reactions": 0,
                    "comments": 0,
                    "reposts": 0,
                    "er": 0.0,
                }
            )

    # Today's bar is always rebuilt from live post data so growth shows up
    # immediately, without waiting for the next scheduled capture. History
    # classification (used_legacy/used_post/historySource) stays based on
    # what actually backed the window, unaffected by this live refresh.
    if days:
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        baseline_today = _totals_before_moment(today_start, by_post, channel_snapshots)
        live_today_row = _delta_row_from_post_totals(
            days[-1]["date"],
            end_post_totals,
            baseline_today,
            _posts_published_on_day(published, today),
        )
        live_today_row["subscribers"] = (subscribers_now or 0) - _subscribers_before_moment(
            today_start, channel_snapshots
        )
        # ER is always the channel's current overall level (matches endTotals
        # and the legacy convention), not a delta computed for just today.
        live_today_row["er"] = float(end_post_totals["er"])
        days[-1] = live_today_row

    # Backfill subscriber deltas for any earlier day still sourced from
    # per-post history (_delta_row_from_post_totals always zeroes them there).
    _merge_subscriber_deltas(days, channel_snap_rows)

    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    if post_snapshots:
        baseline_totals = _post_totals_at_moment(
            by_post,
            window_start - timedelta(microseconds=1),
        )
        start_totals = _normalize_totals(baseline_totals, subscribers_fallback=0)
    else:
        baseline = None
        for snap in channel_snapshots:
            if snap.captured_at.astimezone(timezone.utc) < window_start:
                baseline = snap
        if baseline is not None:
            start_totals = _normalize_totals(_snapshot_totals(baseline), subscribers_fallback=0)
        else:
            start_totals = _start_totals_from_window(published, period, subscribers_now)

    if used_legacy and used_post:
        history_source = "mixed"
    elif used_post:
        history_source = "post_snapshots"
    else:
        history_source = "legacy_channel_snapshots"

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
        "trackingSince": tracking_since,
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
