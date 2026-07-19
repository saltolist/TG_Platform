#!/bin/sh
set -e

# Migrations + seeding already run by the `backend` API service on startup
# (scripts/entrypoint.sh); this entrypoint only starts a Celery process.
# Usage: entrypoint-celery.sh worker|heavy|beat

role="${1:-worker}"

prepare_prometheus_multiproc_dir() {
    if [ -z "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
        return
    fi
    rm -rf -- "$PROMETHEUS_MULTIPROC_DIR"
    mkdir -p -- "$PROMETHEUS_MULTIPROC_DIR"
}

case "$role" in
  worker)
    prepare_prometheus_multiproc_dir
    export TG_CELERY_WORKER_KIND=interactive
    queues="${CELERY_WORKER_QUEUES:-agent-interactive,telegram-io,analytics}"
    echo "[entrypoint-celery] Starting warm worker queues=${queues}; embedding warmup runs in the child process."
    exec celery -A app.celery_app worker -l info --queues "$queues" --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
    ;;
  heavy)
    prepare_prometheus_multiproc_dir
    export TG_CELERY_WORKER_KIND=heavy
    queues="${CELERY_WORKER_QUEUES:-agent-heavy}"
    echo "[entrypoint-celery] Starting heavy worker queues=${queues}; embedding warmup runs in the child process."
    exec celery -A app.celery_app worker -l info --queues "$queues" --concurrency="${CELERY_WORKER_CONCURRENCY:-1}"
    ;;
  beat)
    echo "[entrypoint-celery] Starting Celery beat..."
    exec celery -A app.celery_app beat -l info
    ;;
  *)
    echo "[entrypoint-celery] Unknown role '$role' (expected: worker|heavy|beat)" >&2
    exit 1
    ;;
esac
