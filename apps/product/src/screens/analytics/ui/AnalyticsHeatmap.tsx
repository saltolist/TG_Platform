"use client";

import { ANALYTICS_HEATMAP_HOURS, ANALYTICS_HEATMAP_ROWS } from "@/shared/data/analyticsSeedData";

export default function AnalyticsHeatmap() {
  return (
    <div className="analytics-card platform-analytics-section">
      <div className="profile-section-title platform-section-title-spaced">Тепловая карта активности</div>
      <div className="analytics-card-subtitle">Средний отклик по дням и времени публикации</div>
      <div className="heatmap">
        <div className="heatmap-head">
          <span />
          {ANALYTICS_HEATMAP_HOURS.map((hour) => (
            <span key={hour}>{hour}</span>
          ))}
        </div>
        {ANALYTICS_HEATMAP_ROWS.map((row) => (
          <div className="heatmap-row" key={row.day}>
            <span className="heatmap-day">{row.day}</span>
            {row.values.map((level, i) => (
              <span key={`${row.day}-${i}`} className={`heatmap-cell heatmap-level-${level}`} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
