"""Work around Docker VM clock skew on macOS (often 30+ seconds).

Telethon ignores server updates when local time differs from Telegram by more
than ~30s (``MSG_TOO_NEW_DELTA``). Mounting ``/etc/localtime`` does not fix the
running clock inside the VM. We probe real time over HTTP and pre-seed Telethon's
``time_offset`` immediately after ``connect()`` so live-sync events are not dropped.
"""

from __future__ import annotations

import email.utils
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Telethon drops messages when skew exceeds MSG_TOO_NEW_DELTA (30s).
_TELEGRAM_SKEW_WARN_SECONDS = 25

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


async def measure_http_time_offset_seconds() -> int | None:
    """Return seconds to add to ``time.time()`` to approximate real UTC.

    Positive offset means the container clock is behind (common in Docker Desktop
    / Colima). ``None`` when every probe failed (offline / blocked egress).
    """
    timeout = httpx.Timeout(5.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in _HTTP_TIME_PROBE_URLS:
            try:
                response = await client.head(url)
                date_header = response.headers.get("date") or response.headers.get("Date")
                if not date_header:
                    continue
                server_ts = _parse_http_date(date_header)
                if server_ts is None:
                    continue
                return int(server_ts - time.time())
            except httpx.HTTPError:
                continue
    return None


def apply_time_offset_to_client(client: Any, offset_seconds: int) -> int | None:
    """Write *offset_seconds* into Telethon's MTProto state, if available."""
    sender = getattr(client, "_sender", None)
    state = getattr(sender, "_state", None) if sender is not None else None
    if state is None:
        return None

    old_offset = int(getattr(state, "time_offset", 0) or 0)
    # Small buffer past Telethon's 30s MSG_TOO_NEW_DELTA — Docker Desktop often drifts ~31s.
    adjusted = int(offset_seconds)
    if adjusted > 20:
        adjusted += 2
    elif adjusted < -20:
        adjusted -= 2
    state.time_offset = adjusted
    if state.time_offset != old_offset:
        state._last_msg_id = 0  # noqa: SLF001 — Telethon resets this on offset change
    return old_offset


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
        logger.info("Container clock skew vs HTTP time: %ds", offset)
