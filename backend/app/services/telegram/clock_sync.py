"""Work around Docker VM clock skew on macOS (often 30+ seconds).

Telethon ignores server updates when local time differs from Telegram by more
than ~30s (``MSG_TOO_NEW_DELTA``). Mounting ``/etc/localtime`` does not fix the
running clock inside the VM. We probe real time over HTTP and pre-seed Telethon's
``time_offset`` immediately after ``connect()`` so live-sync events are not dropped.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import time
from datetime import timezone
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Telethon drops messages when skew exceeds MSG_TOO_NEW_DELTA (30s).
_TELEGRAM_SKEW_WARN_SECONDS = 25
# Do not overwrite Telethon's server-learned offset with noise below this threshold.
_CLOCK_SYNC_APPLY_MIN_SECONDS = 10
# Fresh live messages — offset from ``message.date`` must be within this window.
_LIVE_MESSAGE_MAX_SKEW_SECONDS = 90
# MTProto offsets beyond ±2 minutes are almost certainly corrupt (e.g. channel msg id ≠ remote id).
_MAX_REASONABLE_OFFSET_SECONDS = 120

_HTTP_TIME_PROBE_URLS = (
    "https://www.google.com/generate_204",
    "https://cloudflare.com/cdn-cgi/trace",
    "https://www.apple.com/library/test/success.html",
)


def _parse_http_date(header_value: str) -> float | None:
    try:
        parsed = email.utils.parsedate_to_datetime(header_value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return parsed.timestamp()
    return parsed.timestamp()


async def measure_http_time_offset_seconds(
    *, max_attempts: int = 3, retry_delay_seconds: float = 0.35
) -> int | None:
    """Return seconds to add to ``time.time()`` to approximate real UTC.

    Positive offset means the container clock is behind (common in Docker Desktop
    / Colima). ``None`` when every probe failed (offline / blocked egress).
    Takes several samples — Docker HTTP time can read ``0`` on a cold start;
    non-zero samples are preferred over ``0``. Retries when all samples look
    like noise (|offset| < ``_CLOCK_SYNC_APPLY_MIN_SECONDS``).
    """
    best: int | None = None
    for attempt in range(max(1, max_attempts)):
        samples: list[int] = []
        timeout = httpx.Timeout(5.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for url in _HTTP_TIME_PROBE_URLS:
                for probe in range(3):
                    try:
                        response = await client.head(url)
                        date_header = response.headers.get("date") or response.headers.get("Date")
                        if not date_header:
                            continue
                        server_ts = _parse_http_date(date_header)
                        if server_ts is None:
                            continue
                        samples.append(int(server_ts - time.time()))
                    except httpx.HTTPError:
                        continue
                    if probe < 2:
                        await asyncio.sleep(0.1)
        if samples:
            significant = [s for s in samples if abs(s) >= _CLOCK_SYNC_APPLY_MIN_SECONDS]
            pool = significant if significant else samples
            candidate = max(pool, key=abs)
            if best is None or abs(candidate) > abs(best):
                best = candidate
        if (
            best is not None
            and abs(best) >= _CLOCK_SYNC_APPLY_MIN_SECONDS
        ) or attempt + 1 >= max_attempts:
            break
        await asyncio.sleep(retry_delay_seconds)
    return best


def apply_time_offset_to_client(client: Any, offset_seconds: int) -> int | None:
    """Write *offset_seconds* into Telethon's MTProto state, if available."""
    sender = getattr(client, "_sender", None)
    state = getattr(sender, "_state", None) if sender is not None else None
    if state is None:
        return None

    old_offset = int(getattr(state, "time_offset", 0) or 0)
    state.time_offset = int(offset_seconds)
    if state.time_offset != old_offset:
        state._last_msg_id = 0  # noqa: SLF001 — Telethon resets this on offset change
    return old_offset


def _plausible_offset_seconds(value: int) -> bool:
    return abs(value) <= _MAX_REASONABLE_OFFSET_SECONDS


def offset_from_message_date(message: Any) -> int | None:
    """Derive Telethon ``time_offset`` from a channel message's ``date`` field."""
    date = getattr(message, "date", None)
    if date is None:
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    else:
        date = date.astimezone(timezone.utc)
    return int(date.timestamp()) - int(time.time())


def apply_preferred_time_offset(client: Any, http_offset: int) -> int | None:
    """Apply HTTP offset only when it is a stronger correction than Telethon already has."""
    sender = getattr(client, "_sender", None)
    state = getattr(sender, "_state", None) if sender is not None else None
    current = int(getattr(state, "time_offset", 0) or 0) if state is not None else 0
    if not _plausible_offset_seconds(http_offset) or abs(http_offset) < _CLOCK_SYNC_APPLY_MIN_SECONDS:
        if _plausible_offset_seconds(current) and abs(current) >= _CLOCK_SYNC_APPLY_MIN_SECONDS:
            return current
        return None
    if not _plausible_offset_seconds(current):
        return apply_time_offset_to_client(client, http_offset)
    if abs(http_offset) <= abs(current):
        return current
    return apply_time_offset_to_client(client, http_offset)


def read_telethon_time_offset(client: Any) -> int:
    sender = getattr(client, "_sender", None)
    state = getattr(sender, "_state", None) if sender is not None else None
    if state is None:
        return 0
    offset = int(getattr(state, "time_offset", 0) or 0)
    if not _plausible_offset_seconds(offset):
        return 0
    return offset


def choose_clock_offset(http_offset: int | None, telethon_offset: int) -> int | None:
    """Pick the strongest plausible correction — HTTP and Telegram often disagree in Docker."""
    candidates: list[int] = []
    if (
        http_offset is not None
        and _plausible_offset_seconds(http_offset)
        and abs(http_offset) >= _CLOCK_SYNC_APPLY_MIN_SECONDS
    ):
        candidates.append(http_offset)
    if _plausible_offset_seconds(telethon_offset) and abs(telethon_offset) >= _CLOCK_SYNC_APPLY_MIN_SECONDS:
        candidates.append(telethon_offset)
    if not candidates:
        return None
    return max(candidates, key=abs)


async def reinforce_clock_after_telegram_rpc(client: Any, settings: Settings) -> int | None:
    """Align Telethon after MTProto RPCs — must run before live update handlers."""
    if not settings.telegram_clock_sync_enabled:
        return None
    http_offset = await measure_http_time_offset_seconds()
    tg_offset = read_telethon_time_offset(client)
    chosen = choose_clock_offset(http_offset, tg_offset)
    if chosen is None:
        return None
    if (
        http_offset is None or abs(http_offset) < _CLOCK_SYNC_APPLY_MIN_SECONDS
    ) and abs(tg_offset) >= _TELEGRAM_SKEW_WARN_SECONDS:
        logger.warning(
            "HTTP clock probe inconclusive (http=%s); relying on Telethon offset %ds — "
            "live events may drop if the VM clock drifts further",
            http_offset,
            tg_offset,
        )
    previous = read_telethon_time_offset(client)
    apply_time_offset_to_client(client, chosen)
    applied = read_telethon_time_offset(client)
    if abs(chosen) >= _TELEGRAM_SKEW_WARN_SECONDS or abs(applied) >= _TELEGRAM_SKEW_WARN_SECONDS:
        logger.info(
            "Reinforced Telethon clock: applied=%ds chosen=%s http=%s telethon_learned=%s (was %s)",
            applied,
            chosen,
            http_offset,
            tg_offset,
            previous,
        )
    return applied


def refine_clock_from_live_message(client: Any, message: Any, settings: Settings) -> int | None:
    """Update Telethon offset from a just-received channel message's ``date``.

    Unlike historical posts, live events carry a server timestamp close to now,
    so ``message.date`` reflects current clock skew (safe after successful ingest).
    """
    if not settings.telegram_clock_sync_enabled:
        return None
    live_offset = offset_from_message_date(message)
    if live_offset is None or not _plausible_offset_seconds(live_offset):
        return None
    if abs(live_offset) > _LIVE_MESSAGE_MAX_SKEW_SECONDS:
        return None
    tg_offset = read_telethon_time_offset(client)
    chosen = choose_clock_offset(live_offset, tg_offset)
    if chosen is None and abs(live_offset) >= _CLOCK_SYNC_APPLY_MIN_SECONDS:
        chosen = live_offset
    if chosen is None:
        return None
    previous = read_telethon_time_offset(client)
    if chosen == previous:
        return previous
    apply_time_offset_to_client(client, chosen)
    applied = read_telethon_time_offset(client)
    if abs(chosen - previous) >= 3:
        logger.info(
            "Refined Telethon clock from live message: applied=%ds chosen=%s live=%s telethon=%s (was %s)",
            applied,
            chosen,
            live_offset,
            tg_offset,
            previous,
        )
    return applied


async def refresh_telethon_clock(client: Any, settings: Settings) -> int | None:
    """Re-sync during a long-lived listener (HTTP + Telethon-learned offset)."""
    if not settings.telegram_clock_sync_enabled:
        return None
    try:
        await asyncio.wait_for(client.get_me(), timeout=settings.telegram_rpc_timeout_seconds)
    except Exception:
        logger.debug("get_me during clock refresh failed", exc_info=True)
    return await reinforce_clock_after_telegram_rpc(client, settings)


async def log_container_clock_skew() -> None:
    """Startup diagnostic — helps explain live-sync drops in Docker logs."""
    offset = await measure_http_time_offset_seconds()
    if offset is None:
        logger.warning(
            "Could not probe HTTP time for Telethon clock sync "
            "(egress blocked?). Live-sync may drop Telegram updates in Docker."
        )
        return
    if abs(offset) >= _TELEGRAM_SKEW_WARN_SECONDS:
        logger.warning(
            "Container clock skew is %ds vs HTTP time. "
            "Telethon live-sync needs offset correction (applied on each connect). "
            "On macOS Docker consider running the backend on the host: "
            "cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000",
            offset,
        )
    else:
        logger.info(
            "Container clock skew vs HTTP time: %ds "
            "(Telegram MTProto may still report a larger offset at connect)",
            offset,
        )
