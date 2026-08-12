"""Prometheus exporter for Celery prefork workers.

The prometheus client stores counters and histograms in per-process files when
``PROMETHEUS_MULTIPROC_DIR`` is set.  This module owns the parent-process HTTP
endpoint that merges those files with ``MultiProcessCollector``.  The directory
is deliberately local to a worker container; sharing it between containers can
collide because each container has its own PID namespace.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock, Thread
from wsgiref.simple_server import WSGIServer

from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client import multiprocess

logger = logging.getLogger("agent.runtime.prometheus")

_server_lock = Lock()
_server_started = False
_server: WSGIServer | None = None
_server_thread: Thread | None = None


def multiprocess_dir() -> Path | None:
    value = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "").strip()
    return Path(value) if value else None


def start_multiprocess_server() -> bool:
    """Expose merged metrics from the Celery parent, when configured."""
    global _server, _server_started, _server_thread
    directory = multiprocess_dir()
    if directory is None:
        return False
    directory.mkdir(parents=True, exist_ok=True)
    with _server_lock:
        if _server_started:
            return True
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        port = int(os.environ.get("PROMETHEUS_METRICS_PORT", "9108"))
        _server, _server_thread = start_http_server(port, registry=registry)
        _server_started = True
    logger.info(
        "Prometheus multiprocess exporter listening on port %s (dir=%s)",
        port,
        directory,
    )
    return True


def mark_process_dead() -> None:
    """Remove live gauge files for a normally exiting Celery child."""
    if multiprocess_dir() is None:
        return
    multiprocess.mark_process_dead(os.getpid())
