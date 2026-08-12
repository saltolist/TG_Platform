# Observability — analytics snapshot monitoring

The analytics snapshot Celery job pushes per-cycle metrics to **Pushgateway**. Prometheus scrapes Pushgateway, Grafana visualizes the data, and Alertmanager evaluates alert rules.

## Quick start (Docker Compose)

```bash
docker compose up -d pushgateway prometheus alertmanager grafana celery-worker celery-beat
```

After the next snapshot cycle (default every 5 minutes), metrics appear in Prometheus and Grafana.

## UIs

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3001 | `admin` / `GRAFANA_ADMIN_PASSWORD` (default `admin`) |
| Prometheus | http://localhost:9090 | — |
| Alertmanager | http://localhost:9093 | — |
| Pushgateway | http://localhost:9091 | — |

Open Grafana → folder **Analytics** → dashboard **Analytics Snapshot**.

## Metrics

| Metric | Description |
|--------|-------------|
| `analytics_snapshot_cycle_timestamp_seconds` | Unix time of last completed cycle |
| `analytics_snapshot_channels_total` | Connected channels processed |
| `analytics_snapshot_channels_overdue` | Channels past overdue threshold |
| `analytics_snapshot_last_cycle_success` | Successful captures last cycle |
| `analytics_snapshot_last_cycle_errors{error_type}` | Errors by type last cycle |
| `analytics_snapshot_lag_seconds{channel}` | Seconds since last snapshot per channel |

Error types: `profile_missing`, `telegram_connect`, `metrics_poll`, `subscriber_rpc`, `db_error`, `other`.

## Alerts

Defined in `ops/prometheus/alerts.yml`:

- **AnalyticsSnapshotChannelOverdue** — per-channel lag > 30m for 5m
- **AnalyticsSnapshotCycleStalled** — no cycle completed in 30m (celery-beat/worker down)
- **AnalyticsSnapshotErrors** — any errors in the last cycle

Alerts appear in Alertmanager at http://localhost:9093. No external receiver is configured by default.

## Adding a real alert receiver

Edit `ops/alertmanager/alertmanager.yml` and add a receiver (Slack, Telegram, email, etc.). Example for Slack:

```yaml
receivers:
  - name: default
    slack_configs:
      - api_url: "https://hooks.slack.com/services/..."
        channel: "#alerts"
```

Then reload Alertmanager: `docker compose restart alertmanager`.

## Disabling metrics push

Set `PROMETHEUS_PUSHGATEWAY_URL=` (empty) on the `celery-worker` service. Snapshot capture continues normally; only observability is disabled.

## Manual trigger (debug)

```bash
docker compose exec celery-worker celery -A app.celery_app call app.tasks.analytics_snapshot.capture_all_channel_snapshots
```

Then check Pushgateway: http://localhost:9091/metrics
