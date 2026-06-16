"use client";

import TrendChartDotButton from "@/widgets/charts/ui/trend/TrendChartDotButton";
import TrendChartSvg from "@/widgets/charts/ui/trend/TrendChartSvg";
import TrendChartXLabels from "@/widgets/charts/ui/trend/TrendChartXLabels";
import TrendClusterTooltipPortal from "@/widgets/charts/ui/trend/TrendClusterTooltipPortal";
import { useMultiSeriesTrendChart } from "@/widgets/charts/model/useMultiSeriesTrendChart";
import type { MultiSeriesTrendChartProps } from "@/shared/lib/trendChart/chartTypes";

export type { TrendSeriesRow, MultiSeriesTrendChartProps } from "@/shared/lib/trendChart/chartTypes";

export default function MultiSeriesTrendChart(props: MultiSeriesTrendChartProps) {
  const {
    title,
    getDotPrimaryLine,
    getDotGrowthBadge,
    getDotRangeFromStartLine,
    getDotPercentGrowthLine,
  } = props;
  const chart = useMultiSeriesTrendChart(props);

  const clearDotHover = () => {
    chart.setHoveredClusterId(null);
    chart.setHoveredDotKey(null);
    chart.setClusterAnchor(null);
    chart.setClusterStripAnchor(null);
  };

  const dotCallbacks = {
    getDotPrimaryLine,
    getDotGrowthBadge,
    getDotRangeFromStartLine,
    getDotPercentGrowthLine,
  };

  return (
    <div
      className={`trend-plot model-trend-plot${chart.showYAxisLabels ? "" : " trend-plot--no-y-labels"}`}
    >
      <div
        ref={chart.chartWrapRef}
        className="trend-chart-wrap"
        onMouseLeave={() => {
          if (chart.isMobile) return;
          chart.clearTrendHover();
        }}
        onBlur={(event) => {
          if (chart.isMobile) return;
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            chart.clearTrendHover();
          }
        }}
      >
        <TrendChartSvg
          title={title}
          gridRows={chart.gridRows}
          chartRows={chart.chartRows}
          hoveredLineHighlights={chart.hoveredLineHighlights}
        />
        {chart.chartDots.map((dot) => (
          <TrendChartDotButton
            key={`${dot.seriesId}:${dot.label}`}
            dot={dot}
            row={chart.series.find((item) => item.id === dot.seriesId)}
            isClusterActive={chart.hoveredClusterId === dot.clusterId}
            onMouseEnter={chart.onDotMouseEnter}
            onMouseLeave={clearDotHover}
            onFocus={chart.onDotFocus}
            onBlur={clearDotHover}
            {...dotCallbacks}
          />
        ))}
        {chart.showYAxisLabels
          ? chart.gridRows.map((row) => (
              <span key={row.label} className="trend-y-label" style={{ top: `${row.y}%` }}>
                {row.label}
              </span>
            ))
          : null}
      </div>
      <TrendChartXLabels
        labels={chart.labels}
        compactAxisLabels={chart.compactAxisLabels}
        pointEdgeInsetPercent={chart.pointEdgeInsetPercent}
      />
      <TrendClusterTooltipPortal
        clusterStripRef={chart.clusterStripRef}
        hoveredCluster={chart.hoveredCluster}
        clusterAnchor={chart.clusterAnchor}
        clusterStripAnchor={chart.clusterStripAnchor}
        series={chart.series}
        isMobile={chart.isMobile}
        {...dotCallbacks}
      />
    </div>
  );
}
