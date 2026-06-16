"use client";

import type { CSSProperties, FocusEvent, MouseEvent } from "react";
import TrendTooltipBody from "@/widgets/charts/ui/trend/TrendTooltipBody";
import { shouldClearTrendDotHover, trendDotKey } from "@/shared/lib/trendChart/dotClustering";
import type { TrendChartDotView, TrendSeriesRow } from "@/shared/lib/trendChart/chartTypes";

type DotCallbacks = {
  getDotPrimaryLine: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotGrowthBadge?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotRangeFromStartLine?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotPercentGrowthLine?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
};

type Props = DotCallbacks & {
  dot: TrendChartDotView;
  row: TrendSeriesRow | undefined;
  isClusterActive: boolean;
  onMouseEnter: (dot: TrendChartDotView, event: MouseEvent<HTMLButtonElement>) => void;
  onMouseLeave: (event: MouseEvent<HTMLButtonElement>) => void;
  onFocus: (dot: TrendChartDotView, event: FocusEvent<HTMLButtonElement>) => void;
  onBlur: (event: FocusEvent<HTMLButtonElement>) => void;
};

export default function TrendChartDotButton({
  dot,
  row,
  isClusterActive,
  onMouseEnter,
  onMouseLeave,
  onFocus,
  onBlur,
  getDotPrimaryLine,
  getDotGrowthBadge,
  getDotRangeFromStartLine,
  getDotPercentGrowthLine,
}: Props) {
  return (
    <button
      data-trend-dot-key={trendDotKey(dot)}
      className={`trend-html-dot${isClusterActive ? " is-cluster-active" : ""}`}
      type="button"
      aria-label={`${dot.seriesLabel}: ${dot.label}`}
      style={
        {
          left: `${dot.x}%`,
          top: `${dot.y}%`,
          "--dot-color": dot.color,
        } as CSSProperties
      }
      onMouseEnter={(event) => onMouseEnter(dot, event)}
      onMouseLeave={(event) => {
        if (!shouldClearTrendDotHover(event.relatedTarget, event.currentTarget)) return;
        onMouseLeave(event);
      }}
      onFocus={(event) => onFocus(dot, event)}
      onBlur={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        onBlur(event);
      }}
    >
      <span className="trend-html-dot-body" aria-hidden>
        <span className="trend-html-dot-halo" />
        <span
          className="trend-html-dot-core"
          style={{ backgroundColor: dot.color }}
        />
      </span>
      {dot.clusterSize === 1 && row ? (
        <span className="trend-tooltip">
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
      ) : null}
    </button>
  );
}
