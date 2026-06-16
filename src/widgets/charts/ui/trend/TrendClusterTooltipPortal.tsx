"use client";

import { createPortal } from "react-dom";
import type { RefObject } from "react";
import TrendTooltipBody from "@/widgets/charts/ui/trend/TrendTooltipBody";
import type { TrendDotCluster, TrendSeriesRow } from "@/shared/lib/trendChart/chartTypes";
import { trendDotKey } from "@/shared/lib/trendChart/dotClustering";
import {
  TREND_CLUSTER_STRIP_MAX_COLUMNS,
  TREND_CLUSTER_STRIP_MAX_COLUMNS_MOBILE,
  getClusterStripColumnCount,
} from "@/shared/lib/trendChart/math";

type DotCallbacks = {
  getDotPrimaryLine: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotGrowthBadge?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotRangeFromStartLine?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotPercentGrowthLine?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
};

type Props = DotCallbacks & {
  clusterStripRef: RefObject<HTMLDivElement | null>;
  hoveredCluster: TrendDotCluster | null;
  clusterAnchor: { dotX: number } | null;
  clusterStripAnchor: { left?: number; bottom: number } | null;
  series: TrendSeriesRow[];
  isMobile: boolean;
};

export default function TrendClusterTooltipPortal({
  clusterStripRef,
  hoveredCluster,
  clusterAnchor,
  clusterStripAnchor,
  series,
  isMobile,
  getDotPrimaryLine,
  getDotGrowthBadge,
  getDotRangeFromStartLine,
  getDotPercentGrowthLine,
}: Props) {
  if (
    !hoveredCluster ||
    hoveredCluster.dots.length <= 1 ||
    !clusterAnchor ||
    !clusterStripAnchor ||
    typeof document === "undefined"
  ) {
    return null;
  }

  return createPortal(
    <div
      ref={clusterStripRef}
      className="trend-tooltip-strip trend-tooltip-strip--fixed"
      style={{
        left: `${clusterStripAnchor.left ?? 0}px`,
        bottom: `${clusterStripAnchor.bottom}px`,
        opacity: clusterStripAnchor.left == null ? 0 : 1,
      }}
      aria-hidden
    >
      <div
        className="trend-tooltip-strip-track"
        style={{
          gridTemplateColumns: `repeat(${getClusterStripColumnCount(
            hoveredCluster.dots.length,
            isMobile ? TREND_CLUSTER_STRIP_MAX_COLUMNS_MOBILE : TREND_CLUSTER_STRIP_MAX_COLUMNS,
          )}, minmax(170px, 220px))`,
        }}
      >
        {hoveredCluster.dots.map((dot) => {
          const row = series.find((item) => item.id === dot.seriesId);
          if (!row) return null;
          return (
            <span key={trendDotKey(dot)} className="trend-tooltip trend-tooltip-card">
              <TrendTooltipBody
                label={dot.seriesLabel}
                growth={getDotGrowthBadge?.(row, dot.value, dot.pointIndex)}
                periodLabel={dot.periodLabel}
                primaryLine={getDotPrimaryLine(row, dot.value, dot.pointIndex)}
                rangeFromStart={getDotRangeFromStartLine?.(row, dot.value, dot.pointIndex)}
                percentGrowth={getDotPercentGrowthLine?.(row, dot.value, dot.pointIndex)}
                extraLines={dot.extraLines}
              />
            </span>
          );
        })}
      </div>
    </div>,
    document.body,
  );
}
