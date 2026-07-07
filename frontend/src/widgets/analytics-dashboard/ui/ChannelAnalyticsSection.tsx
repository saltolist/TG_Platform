"use client";

import { useMemo } from "react";
import { ChartSeriesSelector } from "@/widgets/charts";
import ChannelMetricBarList from "@/widgets/analytics-dashboard/ui/ChannelMetricBarList";
import ChannelReactionsPanel from "@/widgets/analytics-dashboard/ui/ChannelReactionsPanel";
import ModelPicker from "@/shared/ui/model-picker";
import {
  ANALYTICS_SCREEN_PERIOD_TO_CHART,
  buildChannelTrendSeries,
  formatChannelTrackingSinceLabel,
} from "@/shared/lib/channelAnalyticsTrend";
import { resolveTrendChartMaxPoints } from "@/shared/lib/trendChart/periodLabels";
import { useChartSeriesVisibility } from "@/shared/lib/hooks/useChartSeriesVisibility";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { usePageHeaderLe1080, usePageHeaderLe640 } from "@/widgets/page-header";

import type { ChannelAnalyticsOverview } from "@/shared/api/schemas/channelAnalytics";
import type { PostReaction } from "@/shared/types";

type HistorySource = NonNullable<ChannelAnalyticsOverview["historySource"]>;

export default function ChannelAnalyticsSection({
  periodIndex,
  periods,
  onPeriodChange,
  reactions,
  metricsRevision = 0,
  historySource,
  trackingSince,
}: {
  periodIndex: number;
  periods: string[];
  onPeriodChange: (next: number) => void;
  reactions?: PostReaction[];
  /** Ревизия channelMetricsDb — форсирует пересборку графиков при загрузке API-данных. */
  metricsRevision?: number;
  historySource?: HistorySource;
  trackingSince?: string | null;
}) {
  const isMobile = useMobile760();
  const isHeaderLe1080 = usePageHeaderLe1080();
  const isHeaderLe640 = usePageHeaderLe640();
  const chartMaxPoints = resolveTrendChartMaxPoints({
    isMobile,
    isHeaderLe1080,
    isHeaderLe640,
  });
  const chartPeriod = ANALYTICS_SCREEN_PERIOD_TO_CHART[periodIndex] ?? 1;
  const { labels, series } = useMemo(
    () => buildChannelTrendSeries(periodIndex, { maxPoints: chartMaxPoints }),
    [periodIndex, chartMaxPoints, metricsRevision],
  );
  const seriesIds = useMemo(() => series.map((row) => row.id), [series]);
  const { isVisible, setVisible, filterSeries } = useChartSeriesVisibility(seriesIds);
  const visibleSeries = useMemo(() => filterSeries(series), [filterSeries, series]);
  const selectorItems = useMemo(
    () => series.map((row) => ({ id: row.id, label: row.label, color: row.color })),
    [series],
  );

  const isNoHistory = historySource === "no_history";
  const trackingSinceLabel = trackingSince
    ? formatChannelTrackingSinceLabel(trackingSince)
    : null;

  return (
    <>
      <div className="analytics-card analytics-chart-card platform-analytics-section profile-checkbox-scope">
        <div className="analytics-card-head">
          <div className="profile-section-title">Динамика прироста</div>
          <div className="analytics-channel-head-filters model-filter-stack model-filter-stack--with-series">
            {!isMobile ? (
              <ModelPicker
                ariaLabel="Период"
                className="profile-model-picker analytics-period-picker"
                value={String(periodIndex)}
                options={periods.map((label, index) => ({ id: String(index), label }))}
                placement="down"
                dropdownClassName="model-picker-dropdown--page-header"
                onChange={(id) => onPeriodChange(Number(id))}
              />
            ) : null}
            <ChartSeriesSelector
              variant="profile"
              label="Метрики"
              items={selectorItems}
              isVisible={isVisible}
              onVisibleChange={setVisible}
            />
          </div>
        </div>

        {isNoHistory ? (
          <p className="channel-analytics-history-empty">
            Собираем историю канала — данные появятся после первого цикла сбора метрик
          </p>
        ) : (
          <>
            {!isNoHistory && trackingSinceLabel ? (
              <p className="channel-analytics-tracking-since">
                Отслеживаем метрики с {trackingSinceLabel}
              </p>
            ) : null}
            <ChannelMetricBarList
              labels={labels}
              series={visibleSeries}
              chartPeriod={chartPeriod}
              periodIndex={periodIndex}
            />
          </>
        )}
      </div>

      <div className="analytics-card channel-reactions-card platform-analytics-section analytics-metrics-card">
        <div className="analytics-metrics-card-title">Реакции</div>
        <div className="analytics-metrics-card-body">
          <ChannelReactionsPanel reactions={reactions} />
        </div>
      </div>
    </>
  );
}
