"use client";

import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
import { DEMO_CHANNEL_ANALYTICS_HEATMAP } from "@/shared/data/analyticsSeedData";
import type { ChannelAnalyticsHeatmap } from "@/shared/api/schemas/channelAnalytics";

export default function AnalyticsHeatmap({
  heatmap,
}: {
  /** Реальная карта из analytics API; для demo-режима используется seed. */
  heatmap?: ChannelAnalyticsHeatmap;
}) {
  const resolved = heatmap ?? (shouldPersistLocally() ? DEMO_CHANNEL_ANALYTICS_HEATMAP : undefined);
  const hasData = resolved != null && resolved.hasData !== false;

  return (
    <div className="analytics-card platform-analytics-section">
      <div className="profile-section-title platform-section-title-spaced">Тепловая карта активности</div>
      <div className="analytics-card-subtitle">Средний отклик по дням и времени публикации</div>
      {hasData ? (
        <div className="heatmap">
          <div className="heatmap-head">
            <span />
            {resolved.hours.map((hour) => (
              <span key={hour}>{hour}</span>
            ))}
          </div>
          {resolved.rows.map((row) => (
            <div className="heatmap-row" key={row.day}>
              <span className="heatmap-day">{row.day}</span>
              {row.values.map((level, i) => (
                <span key={`${row.day}-${i}`} className={`heatmap-cell heatmap-level-${level}`} />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <p className="heatmap-empty">Пока недостаточно данных — карта появится после публикаций с просмотрами</p>
      )}
    </div>
  );
}
