import type { TrendChartRow, TrendSeriesRow } from "@/shared/lib/trendChart/chartTypes";
import {
  TREND_CHART_WIDTH,
  buildAdaptiveValueScale,
  buildSmoothPath,
  valueToChartY,
} from "@/shared/lib/trendChart/math";

type ValueScale = ReturnType<typeof buildAdaptiveValueScale>;
import {
  formatTrendPointPeriod,
  getTrendPointXPercent,
} from "@/shared/lib/trendChart/periodLabels";

export const TREND_PLOT_TOP = 1;
export const TREND_PLOT_BOTTOM = 88;

export function collectYValues(series: TrendSeriesRow[], pointCount: number) {
  return series.flatMap((row) =>
    Array.from({ length: pointCount }, (_, index) => row.yValues?.[index] ?? row.values[index] ?? 0),
  );
}

type BuildRowsArgs = {
  labels: string[];
  series: TrendSeriesRow[];
  period: number;
  pointEdgeInsetPercent: number;
  valueScale: ValueScale;
  getDotExtraLines?: (row: TrendSeriesRow, value: number, pointIndex: number) => string[];
};

export function buildTrendChartRows({
  labels,
  series,
  period,
  pointEdgeInsetPercent,
  valueScale,
  getDotExtraLines,
}: BuildRowsArgs): TrendChartRow[] {
  const chartBottom = TREND_PLOT_BOTTOM;
  const chartHeight = chartBottom - TREND_PLOT_TOP;

  return series.map((row) => {
    const points = labels.map((_, i) => {
      const yValue = row.yValues?.[i] ?? row.values[i] ?? 0;
      const x =
        labels.length === 1
          ? TREND_CHART_WIDTH / 2
          : (getTrendPointXPercent(i, labels.length, pointEdgeInsetPercent) / 100) *
            TREND_CHART_WIDTH;
      const y = valueToChartY(yValue, valueScale, chartBottom, chartHeight);
      return { x, y };
    });

    const dots = labels.map((label, i) => {
      const value = row.values[i] ?? 0;
      const yValue = row.yValues?.[i] ?? value;
      return {
        x: getTrendPointXPercent(i, labels.length, pointEdgeInsetPercent),
        y: valueToChartY(yValue, valueScale, chartBottom, chartHeight),
        value,
        label,
        pointIndex: i,
        periodLabel: formatTrendPointPeriod(period, i, labels.length),
        extraLines: getDotExtraLines?.(row, value, i) ?? [],
      };
    });

    return { ...row, path: buildSmoothPath(points), dots };
  });
}
