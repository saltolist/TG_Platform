"use client";

import { ANALYTICS_HEATMAP_HOURS, ANALYTICS_HEATMAP_ROWS } from "@/shared/data/analyticsSeedData";
import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
import type { ChannelAnalyticsHeatmap } from "@/shared/api/schemas/channelAnalytics";

const SEED_HEATMAP: ChannelAnalyticsHeatmap = {
  hours: [...ANALYTICS_HEATMAP_HOURS],
  rows: ANALYTICS_HEATMAP_ROWS.map((row) => ({ day: row.day, values: [...row.values] })),
  hasData: true,
};

export default function AnalyticsHeatmap({
  heatmap,
}: {
  /** Реальная карта из overview API; для demo-режима используется seed. */
  heatmap?: ChannelAnalyticsHeatmap;
}) {
  const resolved = heatmap ?? (shouldPersistLocally() ? SEED_HEATMAP : undefined);
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
