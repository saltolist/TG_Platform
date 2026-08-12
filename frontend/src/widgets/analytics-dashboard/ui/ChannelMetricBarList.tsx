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
// Ненулевые значения должны быть визуально чуть выше дна, чтобы не выглядеть как 0.
const NON_ZERO_MIN_MAGNITUDE = 0.12;

/** Позиция точки снизу трека в процентах — итоговое значение на этот момент. */
function pointOffsetPercent(bar: BarDatum): number {
  return CHART_PADDING + bar.magnitude * (100 - 2 * CHART_PADDING);
}

function normalizePlotMagnitude(value: number, plotValues: number[]): number {
  if (!plotValues.length) return 0;

  const max = Math.max(...plotValues);
  if (max <= 0) {
    return 0;
  }

  if (value <= 0) {
    return 0;
  }

  const positiveValues = plotValues.filter((item) => item > 0);
  const minPositive = positiveValues.length ? Math.min(...positiveValues) : 0;

  if (max === minPositive) {
    return 0.5;
  }

  const scaled = (value - minPositive) / (max - minPositive);
  return NON_ZERO_MIN_MAGNITUDE + scaled * (1 - NON_ZERO_MIN_MAGNITUDE);
}

/** Координаты точек в viewBox 0..100 (ось Y снизу вверх). */
function buildChartPoints(bars: BarDatum[], count: number) {
  return bars.map((bar, index) => {
    const x = count > 0 ? ((index + 0.5) / count) * 100 : 50;
    const y = 100 - pointOffsetPercent(bar);
    return { x, y };
  });
}

function formatSvgPoints(points: { x: number; y: number }[]) {
  return points.map((point) => `${point.x.toFixed(3)},${point.y.toFixed(3)}`).join(" ");
}

/** Замкнутый полигон: низ → линия → низ (заливка под кривой). */
function buildAreaPolygonPoints(points: { x: number; y: number }[]) {
  if (points.length === 0) return "";
  const first = points[0];
  const last = points[points.length - 1];
  return formatSvgPoints([
    { x: first.x, y: 100 },
    ...points,
    { x: last.x, y: 100 },
  ]);
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
        // Ноль остается на самом дне, но любые положительные значения слегка
        // приподнимаем, чтобы «малые» точки не выглядели как нулевые.
        magnitude: normalizePlotMagnitude(value, plotValues),
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

      <MetricLineChart chartId={row.id} bars={bars} />

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

function MetricLineChart({ chartId, bars }: { chartId: string; bars: BarDatum[] }) {
  const count = bars.length;
  const points = buildChartPoints(bars, count);
  const polylinePoints = formatSvgPoints(points);
  const areaPoints = buildAreaPolygonPoints(points);
  const gradientId = `channel-metric-area-${chartId}`;

  return (
    <div className="channel-metric-line-chart">
      <svg
        className="channel-metric-line-svg"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" className="channel-metric-line-area-stop-top" />
            <stop offset="100%" className="channel-metric-line-area-stop-bottom" />
          </linearGradient>
        </defs>
        {count > 1 ? (
          <>
            <polygon
              className="channel-metric-line-area"
              points={areaPoints}
              fill={`url(#${gradientId})`}
            />
            <polyline
              className="channel-metric-line-path"
              points={polylinePoints}
              vectorEffect="non-scaling-stroke"
            />
          </>
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
