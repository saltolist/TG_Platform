"""Dedicated Telegram live-sync worker process."""

from __future__ import annotations

import asyncio
import logging
import signal

from app.db.session import async_session_factory
from app.services.telegram.listener_control import run_listener_control_subscriber
from app.services.telegram.live_sync_worker import telegram_live_sync_worker

logger = logging.getLogger(__name__)


async def _run(stop_event: asyncio.Event) -> None:
    live_sync_task = asyncio.create_task(
        telegram_live_sync_worker(async_session_factory, stop_event),
        name="telegram-live-sync-worker",
    )
    control_task = asyncio.create_task(
        run_listener_control_subscriber(stop_event),
        name="telegram-listener-control",
    )
    try:
        await asyncio.gather(live_sync_task, control_task)
    except asyncio.CancelledError:
        stop_event.set()
        live_sync_task.cancel()
        control_task.cancel()
        await asyncio.gather(live_sync_task, control_task, return_exceptions=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop_event = asyncio.Event()

    def _handle_signal(*_args: object) -> None:
        logger.info("Sync worker shutdown requested")
        stop_event.set()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_a: _handle_signal())

    try:
        loop.run_until_complete(_run(stop_event))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
