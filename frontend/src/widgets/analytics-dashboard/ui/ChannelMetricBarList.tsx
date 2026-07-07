"use client";

import { useMemo, type CSSProperties, type Ref } from "react";
import { createPortal } from "react-dom";
import {
  buildChannelMetricBarSeries,
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
  /** Короткая подпись под столбцом (время или дата). */
  axisLabel: string;
  periodLabel: string;
  growthLabel: string;
  cumulativeLabel: string;
  /** Высота столбца от нулевой линии, доля 0..1. */
  magnitude: number;
  isNegative: boolean;
};

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
    const barValues = buildChannelMetricBarSeries(row.id, row.values, prior);
    const maxMagnitude = barValues.reduce(
      (max, value) => Math.max(max, Math.abs(value)),
      0,
    );

    return labels.map((axisLabel, index) => {
      const barAmount = barValues[index] ?? 0;
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
        magnitude: maxMagnitude > 0 ? Math.abs(barAmount) / maxMagnitude : 0,
        isNegative: barAmount < 0,
      };
    });
  }, [row.id, row.values, prior, labels, chartPeriod, pointCount]);

  const hasNegative = bars.some((bar) => bar.isNegative);

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

      <div
        className={`channel-metric-bar-chart${hasNegative ? " channel-metric-bar-chart--signed" : ""}`}
      >
        {bars.map((bar) => (
          <MetricBarColumn key={bar.key} bar={bar} signed={hasNegative} />
        ))}
      </div>

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

function MetricBarTooltipBody({ bar }: { bar: BarDatum }) {
  return (
    <>
      <b>{bar.periodLabel}</b>
      <span>Прирост: {bar.growthLabel}</span>
      <span>Всего: {bar.cumulativeLabel}</span>
    </>
  );
}

function MetricBarColumn({ bar, signed }: { bar: BarDatum; signed: boolean }) {
  const isMobile = useMobile760();
  const { rowRef, open, mobileHandlers } = useAnchoredBarRowTooltip(isMobile);
  const { desktopTooltipPos, desktopTooltipHandlers } = useDesktopBarTooltipPortal(!isMobile);

  // Со знаком: доступна половина высоты трека по каждую сторону нулевой линии.
  const maxPercent = signed ? 50 : 100;
  const heightPercent = Math.max(bar.magnitude * maxPercent, bar.magnitude > 0 ? 3 : 0);
  const fillStyle: CSSProperties = signed
    ? bar.isNegative
      ? { top: "50%", bottom: "auto", height: `${heightPercent}%` }
      : { bottom: "50%", height: `${heightPercent}%` }
    : { bottom: 0, height: `${heightPercent}%` };

  return (
    <div
      ref={rowRef as Ref<HTMLDivElement>}
      className={`channel-metric-bar-col${bar.isNegative ? " channel-metric-bar-col--negative" : ""}${
        open && isMobile ? " channel-metric-bar-col--tooltip-open" : ""
      }`}
      role="button"
      tabIndex={0}
      aria-label={`${bar.periodLabel}: прирост ${bar.growthLabel}`}
      {...(isMobile ? mobileHandlers : desktopTooltipHandlers)}
    >
      <div className="channel-metric-bar-col-track">
        <div className="channel-metric-bar-col-fill" style={fillStyle} />
      </div>
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
