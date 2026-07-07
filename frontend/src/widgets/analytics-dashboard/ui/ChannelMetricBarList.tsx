"use client";

import { useMemo, type CSSProperties, type Ref } from "react";
import { createPortal } from "react-dom";
import {
  buildChannelMetricSummaries,
  formatChannelGrowthBadge,
  formatChannelGrowthPrimary,
} from "@/shared/lib/channelAnalyticsTrend";
import { formatChannelTrendPointPeriod } from "@/shared/lib/channelMetricsDb";
import { useAnchoredBarRowTooltip } from "@/shared/lib/hooks/useAnchoredBarRowTooltip";
import { useDesktopBarTooltipPortal } from "@/shared/lib/hooks/useDesktopBarTooltipPortal";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import type { TrendSeriesRow } from "@/shared/lib/trendChart/chartTypes";

type ChannelMetricBarListProps = {
  labels: string[];
  series: TrendSeriesRow[];
  chartPeriod: number;
  periodIndex: number;
};

type BarDatum = {
  key: string;
  /** Короткая подпись под точкой (время или дата). */
  axisLabel: string;
  periodLabel: string;
  growthLabel: string;
  cumulativeLabel: string;
  /** Положение точки в пределах видимого диапазона (min..max), доля 0..1. */
  magnitude: number;
};

// Отступ сверху/снизу трека (в %), чтобы точки на краях диапазона не обрезались.
const CHART_PADDING = 6;

/** Позиция точки снизу трека в процентах — итоговое значение на этот момент. */
function pointOffsetPercent(bar: BarDatum): number {
  return CHART_PADDING + bar.magnitude * (100 - 2 * CHART_PADDING);
}

export default function ChannelMetricBarList({
  labels,
  series,
  chartPeriod,
  periodIndex,
}: ChannelMetricBarListProps) {
  const summaries = useMemo(
    () => buildChannelMetricSummaries(series, periodIndex),
    [series, periodIndex],
  );
  const summaryById = useMemo(
    () => new Map(summaries.map((item) => [item.id, item])),
    [summaries],
  );

  if (series.length === 0) {
    return null;
  }

  return (
    <div className="channel-metric-bar-list">
      {series.map((row) => {
        const summary = summaryById.get(row.id);
        if (!summary) return null;
        return (
          <MetricBarCard
            key={row.id}
            row={row}
            label={summary.label}
            total={summary.displayQuantity}
            growth={summary.displayGrowth}
            labels={labels}
            chartPeriod={chartPeriod}
          />
        );
      })}
    </div>
  );
}

function MetricBarCard({
  row,
  label,
  total,
  growth,
  labels,
  chartPeriod,
}: {
  row: TrendSeriesRow;
  label: string;
  total: string;
  growth: string;
  labels: string[];
  chartPeriod: number;
}) {
  const prior = row.priorCumulative ?? 0;
  const pointCount = labels.length;

  const bars = useMemo<BarDatum[]>(() => {
    // Итоговое значение метрики на каждый момент (накопленный итог / уровень ER),
    // а не поинтервальный прирост.
    const plotValues = row.yValues ?? [];
    const min = plotValues.length ? Math.min(...plotValues) : 0;
    const max = plotValues.length ? Math.max(...plotValues) : 0;
    const range = max - min;

    return labels.map((axisLabel, index) => {
      const value = plotValues[index] ?? 0;
      return {
        key: `${row.id}:${index}`,
        axisLabel,
        periodLabel: formatChannelTrendPointPeriod(chartPeriod, index, pointCount),
        growthLabel: formatChannelGrowthBadge(
          row.id,
          row.values[index] ?? 0,
          index,
          row.values,
          prior,
        ),
        cumulativeLabel: formatChannelGrowthPrimary(
          row.id,
          row.values[index] ?? 0,
          index,
          row.values,
          prior,
        ),
        // Авто-масштаб по видимому диапазону: min → низ, max → верх. Иначе итог
        // (напр. 3800 просмотров) прижимался бы к потолку и линия была бы плоской.
        magnitude: range > 0 ? (value - min) / range : 0.5,
      };
    });
  }, [row.id, row.values, row.yValues, prior, labels, chartPeriod, pointCount]);

  return (
    <article
      className="channel-metric-bar-card"
      style={{ "--metric-color": row.color } as CSSProperties}
    >
      <header className="channel-metric-bar-card-head">
        <div className="channel-metric-bar-card-title">
          <span className="channel-metric-bar-card-dot" aria-hidden />
          <span className="channel-metric-bar-card-label">
            {label}{" "}
            <span className="channel-metric-bar-card-total">{total}</span>{" "}
            <span className="channel-metric-bar-card-growth">({growth})</span>
          </span>
        </div>
      </header>

      <MetricLineChart bars={bars} />

      <div className="channel-metric-bar-labels">
        {bars.map((bar) => (
          <span key={bar.key} className="channel-metric-bar-label-cell">
            {bar.axisLabel}
          </span>
        ))}
      </div>
    </article>
  );
}

function MetricLineChart({ bars }: { bars: BarDatum[] }) {
  const count = bars.length;
  const polylinePoints = bars
    .map((bar, index) => {
      const x = count > 0 ? ((index + 0.5) / count) * 100 : 50;
      const y = 100 - pointOffsetPercent(bar);
      return `${x.toFixed(3)},${y.toFixed(3)}`;
    })
    .join(" ");

  return (
    <div className="channel-metric-line-chart">
      <svg
        className="channel-metric-line-svg"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden
      >
        {count > 1 ? (
          <polyline
            className="channel-metric-line-path"
            points={polylinePoints}
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
      {bars.map((bar) => (
        <MetricLinePoint key={bar.key} bar={bar} />
      ))}
    </div>
  );
}

function MetricBarTooltipBody({ bar }: { bar: BarDatum }) {
  return (
    <>
      <b>{bar.periodLabel}</b>
      <span>Прирост: {bar.growthLabel}</span>
      <span>Всего: {bar.cumulativeLabel}</span>
    </>
  );
}

function MetricLinePoint({ bar }: { bar: BarDatum }) {
  const isMobile = useMobile760();
  const { rowRef, open, mobileHandlers } = useAnchoredBarRowTooltip(isMobile);
  const { desktopTooltipPos, desktopTooltipHandlers } = useDesktopBarTooltipPortal(!isMobile);

  const offsetPercent = pointOffsetPercent(bar);

  return (
    <div
      ref={rowRef as Ref<HTMLDivElement>}
      className={`channel-metric-line-col${
        open && isMobile ? " channel-metric-line-col--tooltip-open" : ""
      }`}
      role="button"
      tabIndex={0}
      aria-label={`${bar.periodLabel}: всего ${bar.cumulativeLabel}`}
      {...(isMobile ? mobileHandlers : desktopTooltipHandlers)}
    >
      <span
        className="channel-metric-line-dot"
        style={{ bottom: `${offsetPercent}%` }}
      />
      {isMobile && open ? (
        <div className="model-usage-tooltip model-usage-tooltip--anchored-row">
          <MetricBarTooltipBody bar={bar} />
        </div>
      ) : null}
      {!isMobile && desktopTooltipPos && typeof document !== "undefined"
        ? createPortal(
            <div
              className="model-usage-tooltip"
              style={{ left: desktopTooltipPos.x, top: desktopTooltipPos.y }}
            >
              <MetricBarTooltipBody bar={bar} />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
