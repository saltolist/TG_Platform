"""Per-post analytics from PostMetricSnapshot rows."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.db.models import Post, PostMetricSnapshot
from app.services.analytics.channel_metrics import (
    _PERIOD_DAYS,
    _MAX_ALL_TIME_DAYS,
    _delta_row_from_live_totals,
    _floor_to_slot,
    _post_date,
    _snapshot_freshness,
    _totals_from_posts,
    _zeroed_period_days,
    calc_er,
)

_POST_METRIC_KEYS = ("views", "reactions", "comments", "reposts")


def _period_day_span(period: str, post: Post) -> int:
    if period != "all":
        return _PERIOD_DAYS.get(period) or 30
    post_day = _post_date(post)
    if post_day is None:
        return 30
    today = datetime.now(timezone.utc).date()
    span = (today - post_day).days + 1
    return min(max(span, 7), _MAX_ALL_TIME_DAYS)


def _post_snapshot_values(snapshot: PostMetricSnapshot) -> dict[str, int]:
    return {
        "views": int(snapshot.views or 0),
        "reactions": int(snapshot.reactions or 0),
        "comments": int(snapshot.comments or 0),
        "reposts": int(snapshot.reposts or 0),
    }


def _latest_snapshot_at_or_before(
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


def _totals_at_moment(snapshots: list[PostMetricSnapshot], moment: datetime) -> dict[str, int]:
    latest = _latest_snapshot_at_or_before(snapshots, moment)
    if latest is None:
        return {key: 0 for key in _POST_METRIC_KEYS}
    return _post_snapshot_values(latest)


def _live_totals(post: Post) -> dict[str, int]:
    totals = _totals_from_posts([post])
    return {
        "views": int(totals["views"]),
        "reactions": int(totals["reactions"]),
        "comments": int(totals["comments"]),
        "reposts": int(totals["reposts"]),
    }


def _normalize_post_totals(totals: dict[str, int]) -> dict[str, float | int]:
    views = int(totals["views"])
    reactions = int(totals["reactions"])
    comments = int(totals["comments"])
    return {
        "subscribers": 0,
        "views": views,
        "reactions": reactions,
        "comments": comments,
        "reposts": int(totals["reposts"]),
        "er": calc_er(views, reactions, comments),
    }


def _delta_row_from_post_totals(
    date_label: str,
    current: dict[str, int],
    previous: dict[str, int] | None,
) -> dict[str, Any]:
    prev = previous or {}
    view_delta = current["views"] - int(prev.get("views") or 0)
    reaction_delta = current["reactions"] - int(prev.get("reactions") or 0)
    comment_delta = current["comments"] - int(prev.get("comments") or 0)
    repost_delta = current["reposts"] - int(prev.get("reposts") or 0)
    return {
        "date": date_label,
        "views": view_delta,
        "posts": 0,
        "subscribers": 0,
        "reactions": reaction_delta,
        "comments": comment_delta,
        "reposts": repost_delta,
        "er": calc_er(view_delta, reaction_delta, comment_delta),
    }


def _post_day_rows(
    snapshots: list[PostMetricSnapshot],
    start_day: date,
    end_day: date,
) -> dict[date, dict[str, Any]]:
    rows: dict[date, dict[str, Any]] = {}
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    previous_totals = _totals_at_moment(snapshots, window_start - timedelta(microseconds=1))

    day = start_day
    while day <= end_day:
        end_of_day = datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc)
        current_totals = _totals_at_moment(snapshots, end_of_day)
        rows[day] = _delta_row_from_post_totals(day.isoformat(), current_totals, previous_totals)
        previous_totals = current_totals
        day += timedelta(days=1)
    return rows


def _post_slot_rows(
    snapshots: list[PostMetricSnapshot],
    since: datetime,
) -> list[dict[str, Any]]:
    slot_times = sorted(
        snap.captured_at.astimezone(timezone.utc)
        for snap in snapshots
        if snap.captured_at.astimezone(timezone.utc) >= since
    )
    if not slot_times:
        return []

    rows: list[dict[str, Any]] = []
    previous_totals = _totals_at_moment(snapshots, since - timedelta(microseconds=1))
    for slot in slot_times:
        current_totals = _totals_at_moment(snapshots, slot)
        rows.append(_delta_row_from_post_totals(slot.isoformat(), current_totals, previous_totals))
        previous_totals = current_totals
    return rows


def _tracking_since(snapshots: list[PostMetricSnapshot]) -> str | None:
    if not snapshots:
        return None
    return snapshots[0].captured_at.astimezone(timezone.utc).date().isoformat()


def _start_totals_from_window(post: Post, period: str) -> dict[str, float | int]:
    """Estimate period-start totals when there is no snapshot history."""
    from app.services.analytics.channel_metrics import _posts_in_window

    end_totals = _normalize_post_totals(_live_totals(post))
    if period == "all":
        return {
            "subscribers": 0,
            "views": 0,
            "reactions": 0,
            "comments": 0,
            "reposts": 0,
            "er": 0.0,
        }
    window_posts = _posts_in_window([post], period)
    window_totals = _totals_from_posts(window_posts)
    views = max(0, int(end_totals["views"]) - int(window_totals["views"]))
    reactions = max(0, int(end_totals["reactions"]) - int(window_totals["reactions"]))
    comments = max(0, int(end_totals["comments"]) - int(window_totals["comments"]))
    reposts = max(0, int(end_totals["reposts"]) - int(window_totals["reposts"]))
    return {
        "subscribers": 0,
        "views": views,
        "reactions": reactions,
        "comments": comments,
        "reposts": reposts,
        "er": calc_er(views, reactions, comments),
    }


def _compute_post_overview(
    post: Post,
    snapshots: list[PostMetricSnapshot],
    period: str,
    telegram: dict[str, Any] | None = None,
    *,
    snapshot_stale_after_seconds: float | None = None,
) -> dict[str, Any]:
    """Growth time series for a single published post."""
    day_span = _period_day_span(period, post)
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=day_span - 1)
    freshness = _snapshot_freshness(telegram, snapshot_stale_after_seconds)

    snapshots = sorted(snapshots, key=lambda snap: snap.captured_at)
    live = _live_totals(post)
    end_totals = _normalize_post_totals(live)
    tracking_since = _tracking_since(snapshots)

    if not snapshots:
        return {
            "dayCount": day_span,
            "granularity": "day",
            "anchorDate": today.isoformat(),
            "startTotals": _start_totals_from_window(post, period),
            "endTotals": end_totals,
            "subscribersAvailable": False,
            "days": _zeroed_period_days(start_day, day_span),
            "historySource": "no_history",
            "trackingSince": None,
            **freshness,
        }

    first_snap_day = snapshots[0].captured_at.astimezone(timezone.utc).date()
    post_day_rows = _post_day_rows(snapshots, start_day, today)

    if period == "24h":
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        slot_rows = _post_slot_rows(snapshots, since)
        current_slot_start = _floor_to_slot(now)
        live_slot_row = _delta_row_from_post_totals(
            now.isoformat(),
            live,
            _totals_at_moment(snapshots, current_slot_start - timedelta(microseconds=1)),
        )

        replacing_last = bool(
            slot_rows
            and datetime.fromisoformat(str(slot_rows[-1]["date"])) >= current_slot_start
        )
        if replacing_last:
            slot_rows[-1] = live_slot_row
        else:
            slot_rows.append(live_slot_row)

        if len(slot_rows) >= 2:
            baseline_totals = _totals_at_moment(snapshots, since - timedelta(microseconds=1))
            start_totals = _normalize_post_totals(baseline_totals)
            return {
                "dayCount": len(slot_rows),
                "granularity": "30m",
                "anchorDate": today.isoformat(),
                "startTotals": start_totals,
                "endTotals": end_totals,
                "subscribersAvailable": False,
                "days": slot_rows,
                "historySource": "post_snapshots",
                "trackingSince": tracking_since,
                **freshness,
            }

    days: list[dict[str, Any]] = []
    for offset in range(day_span):
        day = start_day + timedelta(days=offset)
        if day >= first_snap_day and day in post_day_rows:
            days.append(dict(post_day_rows[day]))
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

    if days:
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        baseline_today = _totals_at_moment(snapshots, today_start - timedelta(microseconds=1))
        live_today_row = _delta_row_from_live_totals(
            days[-1]["date"],
            live,
            baseline_today,
            0,
        )
        live_today_row["posts"] = 0
        live_today_row["subscribers"] = 0
        days[-1] = live_today_row

    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    baseline_totals = _totals_at_moment(snapshots, window_start - timedelta(microseconds=1))
    if any(baseline_totals.values()):
        start_totals = _normalize_post_totals(baseline_totals)
    else:
        start_totals = _start_totals_from_window(post, period)

    return {
        "dayCount": day_span,
        "granularity": "day",
        "anchorDate": today.isoformat(),
        "startTotals": start_totals,
        "endTotals": end_totals,
        "subscribersAvailable": False,
        "days": days,
        "historySource": "post_snapshots",
        "trackingSince": tracking_since,
        **freshness,
    }


def build_post_trend(
    post: Post,
    snapshots: list[PostMetricSnapshot],
    period: str,
    telegram: dict[str, Any] | None = None,
    *,
    snapshot_stale_after_seconds: float | None = None,
) -> dict[str, Any]:
    """Time-series growth rows for one post."""
    overview = _compute_post_overview(
        post,
        snapshots,
        period,
        telegram,
        snapshot_stale_after_seconds=snapshot_stale_after_seconds,
    )
    return {
        "dayCount": overview["dayCount"],
        "granularity": overview["granularity"],
        "anchorDate": overview["anchorDate"],
        "days": overview["days"],
        "startTotals": overview["startTotals"],
        "endTotals": overview["endTotals"],
        "subscribersAvailable": overview["subscribersAvailable"],
        "historySource": overview["historySource"],
        "trackingSince": overview["trackingSince"],
        "lastSnapshotAt": overview.get("lastSnapshotAt"),
        "dataAgeSeconds": overview.get("dataAgeSeconds"),
        "isStale": overview.get("isStale"),
    }