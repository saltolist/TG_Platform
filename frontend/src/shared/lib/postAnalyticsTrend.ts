import {
  ANALYTICS_SCREEN_PERIOD_TO_CHART,
  buildChannelMetricBarSeries,
  buildChannelTrendPlotYValues,
  rebuildErSeriesAsLevel,
} from "@/shared/lib/channelAnalyticsTrend";
import {
  buildChannelChartLabels,
  extractChannelMetricSeriesForChart,
  type ChannelMetricId,
} from "@/shared/lib/channelMetricsDb";
import type { TrendSeriesRow } from "@/shared/lib/trendChart/chartTypes";

const POST_METRICS = [
  {
    id: "reactions",
    label: "Реакции",
    color: "#4caf82",
  },
  {
    id: "views",
    label: "Просмотры",
    color: "#e8954a",
  },
  {
    id: "comments",
    label: "Комментарии",
    color: "#9b7cdb",
  },
  {
    id: "reposts",
    label: "Репосты",
    color: "#e85a5a",
  },
  {
    id: "er",
    label: "ER",
    color: "#35b8d4",
  },
] as const;

export function buildPostTrendSeries(analyticsPeriodIndex: number): {
  labels: string[];
  series: TrendSeriesRow[];
} {
  const chartPeriod = ANALYTICS_SCREEN_PERIOD_TO_CHART[analyticsPeriodIndex] ?? 1;
  const labels = buildChannelChartLabels(chartPeriod);
  const pointCount = labels.length;

  const series: TrendSeriesRow[] = POST_METRICS.map((metric) => {
    const { values, priorCumulative } = extractChannelMetricSeriesForChart(
      metric.id as ChannelMetricId,
      chartPeriod,
      pointCount,
    );

    return {
      id: metric.id,
      label: metric.label,
      color: metric.color,
      values,
      priorCumulative,
      yValues: buildChannelTrendPlotYValues(metric.id, values, priorCumulative),
    };
  });

  rebuildErSeriesAsLevel(series);

  return { labels, series };
}

export { buildChannelMetricBarSeries };
