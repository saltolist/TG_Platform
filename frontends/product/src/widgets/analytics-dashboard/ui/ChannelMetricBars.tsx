"use client";

import { useMemo, type CSSProperties, type Ref } from "react";
import { createPortal } from "react-dom";
import {
  buildChannelMetricSummaries,
  buildChannelTrendSeries,
  type ChannelMetricSummary,
} from "@/shared/lib/channelAnalyticsTrend";
import { resolveTrendChartMaxPoints } from "@/shared/lib/trendChart/periodLabels";
import { useAnchoredBarRowTooltip } from "@/shared/lib/hooks/useAnchoredBarRowTooltip";
import { useDesktopBarTooltipPortal } from "@/shared/lib/hooks/useDesktopBarTooltipPortal";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { usePageHeaderLe1080, usePageHeaderLe640 } from "@/widgets/page-header";

type ChannelMetricBarsProps = {
  periodIndex: number;
};

export default function ChannelMetricBars({ periodIndex }: ChannelMetricBarsProps) {
  const isMobile = useMobile760();
  const isHeaderLe1080 = usePageHeaderLe1080();
  const isHeaderLe640 = usePageHeaderLe640();
  const chartMaxPoints = resolveTrendChartMaxPoints({
    isMobile,
    isHeaderLe1080,
    isHeaderLe640,
  });
  const { series } = useMemo(
    () => buildChannelTrendSeries(periodIndex, { maxPoints: chartMaxPoints }),
    [periodIndex, chartMaxPoints],
  );
  const metrics = useMemo(
    () => buildChannelMetricSummaries(series, periodIndex),
    [series, periodIndex],
  );

  return (
    <table
      className={`channel-metrics-table${isMobile ? " channel-metrics-table--mobile" : ""}`}
      style={{ "--channel-metric-rows": metrics.length } as CSSProperties}
    >
      <colgroup>
        <col className="cmt-col-metric" />
        {!isMobile ? <col className="cmt-col-bar" /> : null}
        <col className="cmt-col-growth" />
        <col className="cmt-col-quantity" />
      </colgroup>
      <thead>
        <tr>
          <th className="cmt-metric" scope="col">
            Метрика
          </th>
          {!isMobile ? <th className="cmt-bar" scope="col" aria-hidden /> : null}
          <th className="cmt-growth" scope="col">
            Прирост
          </th>
          <th className="cmt-quantity" scope="col">
            Количество
          </th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric) => (
          <ChannelMetricBarRow key={metric.id} metric={metric} isMobile={isMobile} />
        ))}
      </tbody>
    </table>
  );
}

function ChannelMetricTooltipBody({ metric }: { metric: ChannelMetricSummary }) {
  return (
    <>
      <b>{metric.label}</b>
      <span>Прирост: {metric.displayGrowth}</span>
      <span>Количество: {metric.displayQuantity}</span>
      <span>Ср. прирост за период: {metric.displayPeriodAverageGrowth}</span>
    </>
  );
}

function ChannelMetricBarRow({
  metric,
  isMobile,
}: {
  metric: ChannelMetricSummary;
  isMobile: boolean;
}) {
  const { rowRef, open, mobileHandlers } = useAnchoredBarRowTooltip(isMobile);
  const { desktopTooltipPos, desktopTooltipHandlers } = useDesktopBarTooltipPortal(!isMobile);
  const fillPercent = metric.barFillPercent;

  return (
    <tr
      ref={rowRef as Ref<HTMLTableRowElement>}
      className={`channel-metric-row${open && isMobile ? " channel-metric-row--tooltip-open" : ""}`}
      style={{ "--bar-row-color": metric.color } as CSSProperties}
      tabIndex={isMobile ? 0 : undefined}
      aria-expanded={isMobile ? open : undefined}
      {...(isMobile ? mobileHandlers : {})}
    >
      <td className="cmt-metric">
        <div className="bar-label">
          <span className="bar-label-text-clip">{metric.label}</span>
          {isMobile && open ? (
            <div className="model-usage-tooltip model-usage-tooltip--anchored-row">
              <ChannelMetricTooltipBody metric={metric} />
            </div>
          ) : null}
        </div>
      </td>
      {!isMobile ? (
        <td className="cmt-bar">
          <div className="channel-metric-bar-zone">
            <div
              className="bar-track model-usage-track channel-metric-track"
              tabIndex={0}
              style={{ "--fill-width": `${fillPercent}%` } as CSSProperties}
              {...desktopTooltipHandlers}
            >
              <div
                className="bar-fill"
                style={
                  {
                    "--fill-width": `${fillPercent}%`,
                    "--bar-color": metric.color,
                    backgroundColor: metric.color,
                  } as CSSProperties
                }
              />
            </div>
          </div>
        </td>
      ) : null}
      <td className="cmt-growth channel-metric-value channel-metric-value--growth">
        {metric.displayGrowth}
      </td>
      <td className="cmt-quantity channel-metric-value channel-metric-value--quantity">
        {metric.displayQuantity}
      </td>
      {!isMobile && desktopTooltipPos && typeof document !== "undefined"
        ? createPortal(
            <div
              className="model-usage-tooltip"
              style={{ left: desktopTooltipPos.x, top: desktopTooltipPos.y }}
            >
              <ChannelMetricTooltipBody metric={metric} />
            </div>,
            document.body,
          )
        : null}
    </tr>
  );
}
