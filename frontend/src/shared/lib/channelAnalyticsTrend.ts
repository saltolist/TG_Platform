import {
  buildChannelChartLabels,
  extractChannelMetricSeriesForChart,
  getChannelChartPeriodDaySpan,
  getChannelEndTotals,
  getMetricTypicalPeriodGrowth,
  isChannelErMetric,
  type ChannelMetricId,
} from "@/shared/lib/channelMetricsDb";
import { formatNumber } from "@/shared/lib/trendChart/math";
import type { TrendSeriesRow } from "@/shared/lib/trendChart/chartTypes";

const CHANNEL_METRICS = [
  {
    id: "subscribers",
    label: "Подписчики",
    color: "#3d7cff",
    base: 214,
    countForms: ["подписчик", "подписчика", "подписчиков"] as const,
  },
  {
    id: "reactions",
    label: "Реакции",
    color: "#4caf82",
    base: 1286,
    countForms: ["реакция", "реакции", "реакций"] as const,
  },
  {
    id: "views",
    label: "Просмотры",
    color: "#e8954a",
    base: 3820,
    countForms: ["просмотр", "просмотра", "просмотров"] as const,
  },
  {
    id: "comments",
    label: "Комментарии",
    color: "#9b7cdb",
    base: 94,
    countForms: ["комментарий", "комментария", "комментариев"] as const,
  },
  {
    id: "reposts",
    label: "Репосты",
    color: "#e85a5a",
    base: 61,
    countForms: ["репост", "репоста", "репостов"] as const,
  },
  {
    id: "er",
    label: "ER постов",
    color: "#35b8d4",
    base: 48,
    isEr: true,
  },
] as const;

function pluralRu(count: number, forms: readonly [string, string, string]) {
  const n = Math.abs(Math.round(count));
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod100 >= 11 && mod100 <= 14) return forms[2];
  if (mod10 === 1) return forms[0];
  if (mod10 >= 2 && mod10 <= 4) return forms[1];
  return forms[2];
}

export const CHANNEL_POST_TABLE_METRICS = CHANNEL_METRICS.map((metric) => ({
  id: metric.id,
  label: metric.id === "er" ? "ER" : metric.label,
}));

/** Таблица «Лучшие посты за период» (десктоп) — без подписчиков */
export const CHANNEL_TOP_POSTS_TABLE_METRICS = CHANNEL_POST_TABLE_METRICS.filter(
  (metric) => metric.id !== "subscribers",
);

/** Телефон или шапка ≤780px: только ER; иначе все метрики кроме подписчиков */
export function getChannelTopPostsTableMetrics(compactColumns: boolean) {
  if (compactColumns) {
    return CHANNEL_POST_TABLE_METRICS.filter((metric) => metric.id === "er");
  }
  return CHANNEL_TOP_POSTS_TABLE_METRICS;
}

export const ANALYTICS_SCREEN_PERIOD_TO_CHART = [0, 1, 2, 3, 4] as const;

export function getChannelCurrentTotals() {
  return getChannelEndTotals();
}

function cumulativeChannelValue(values: number[], pointIndex: number, priorCumulative = 0) {
  const inPeriod = values.slice(0, pointIndex + 1).reduce((sum, item) => sum + item, 0);
  return priorCumulative + inPeriod;
}

function isErMetric(metricId: string) {
  return isChannelErMetric(metricId);
}

/**
 * Индекс от состояния до начала графика (prior): 1 = база, >1 — рост.
 * Первая видимая точка уже отражает прирост за день, поэтому линии не сходятся в одну точку.
 */
function channelPeriodIndexRatio(
  metricId: string,
  values: number[],
  pointIndex: number,
  priorCumulative = 0,
): number {
  if (isErMetric(metricId)) {
    const current = (values[pointIndex] ?? 0) / 10;
    const base =
      priorCumulative > 0 ? priorCumulative / 10 : (values[0] ?? 0) / 10;
    if (base <= 0) return 1;
    return current / base;
  }

  const total = cumulativeChannelValue(values, pointIndex, priorCumulative);
  const base =
    priorCumulative > 0 ? priorCumulative : cumulativeChannelValue(values, 0, 0);
  if (base <= 0) return 1;
  return total / base;
}

/** Ось Y — индекс от старта периода (совпадает с подписью в карточке). */
export function buildChannelTrendPlotYValues(
  metricId: string,
  values: number[],
  priorCumulative = 0,
): number[] {
  return values.map((_, pointIndex) =>
    channelPeriodIndexRatio(metricId, values, pointIndex, priorCumulative),
  );
}

export function buildChannelTrendSeries(
  analyticsPeriodIndex: number,
  options?: { maxPoints?: number },
): {
  labels: string[];
  series: TrendSeriesRow[];
} {
  const chartPeriod = ANALYTICS_SCREEN_PERIOD_TO_CHART[analyticsPeriodIndex] ?? 1;
  const labels = buildChannelChartLabels(chartPeriod, { maxPoints: options?.maxPoints });
  const pointCount = labels.length;

  const series: TrendSeriesRow[] = CHANNEL_METRICS.map((metric) => {
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

  return { labels, series };
}

export type ChannelMetricSummary = {
  id: string;
  label: string;
  color: string;
  displayGrowth: string;
  /** Доля прироста от количества для тултипа, например «(5.9%)». */
  displayGrowthRelativePercent: string;
  displayQuantity: string;
  /** Ширина полосы: прирост относительно среднего прироста за период (50% = средний). */
  barFillPercent: number;
  /** Типичный (средний) прирост этой метрики за выбранный период — шкала полос и тултип. */
  displayPeriodAverageGrowth: string;
};

/** 50% полосы = типичный прирост этой метрики за период. */
const CHANNEL_BAR_FILL_AVERAGE_ANCHOR_PERCENT = 50;
const CHANNEL_BAR_FILL_MIN_PERCENT = 4;

function computePeriodGrowth(metricId: string, values: number[]): number {
  if (isErMetric(metricId)) {
    const last = values[values.length - 1] ?? 0;
    const first = values[0] ?? last;
    return (last - first) / 10;
  }
  return values.reduce((sum, value) => sum + value, 0);
}

function formatGrowthDelta(metricId: string, growth: number) {
  if (isErMetric(metricId)) {
    const sign = growth >= 0 ? "+" : "−";
    return `${sign}${Math.abs(growth).toFixed(1)}%`;
  }
  const sign = growth >= 0 ? "+" : "−";
  return `${sign}${formatNumber(Math.round(Math.abs(growth)))}`;
}

function formatGrowthRelativeToQuantityPercent(growth: number, quantity: number) {
  if (quantity <= 0) return "(0%)";
  const percent = (growth / quantity) * 100;
  return `(${percent.toFixed(1)}%)`;
}

function barFillPercentForPeriodGrowth(growth: number, typicalPeriodGrowth: number) {
  if (growth <= 0) return CHANNEL_BAR_FILL_MIN_PERCENT;
  if (typicalPeriodGrowth <= 0) {
    return Math.min(100, Math.max(CHANNEL_BAR_FILL_MIN_PERCENT, 100));
  }
  const fill =
    CHANNEL_BAR_FILL_AVERAGE_ANCHOR_PERCENT * (growth / typicalPeriodGrowth);
  return Math.min(
    100,
    Math.max(CHANNEL_BAR_FILL_MIN_PERCENT, Math.round(fill)),
  );
}

export type ChannelSummaryCard = {
  id: string;
  label: string;
  value: string;
  displayGrowth: string;
};

export function buildChannelSummaryCards(
  series: TrendSeriesRow[],
  periodIndex: number,
): ChannelSummaryCard[] {
  return buildChannelMetricSummaries(series, periodIndex).map((item) => ({
    id: item.id,
    label: item.label,
    value: formatChannelPostMetricValue(item.id, getChannelCurrentTotals()[item.id as ChannelMetricId] ?? 0),
    displayGrowth: item.displayGrowth,
  }));
}

export function buildChannelMetricSummaries(
  series: TrendSeriesRow[],
  periodIndex: number,
): ChannelMetricSummary[] {
  const chartPeriod = ANALYTICS_SCREEN_PERIOD_TO_CHART[periodIndex] ?? 1;
  const periodDaySpan = getChannelChartPeriodDaySpan(chartPeriod);

  return series.map((row) => {
    const metricId = row.id as ChannelMetricId;
    const growth = computePeriodGrowth(row.id, row.values);
    const typicalPeriodGrowth = getMetricTypicalPeriodGrowth(metricId, periodDaySpan);
    const quantity = getChannelCurrentTotals()[metricId] ?? 0;

    return {
      id: row.id,
      label: row.label,
      color: row.color,
      barFillPercent: barFillPercentForPeriodGrowth(growth, typicalPeriodGrowth),
      displayPeriodAverageGrowth: formatGrowthDelta(metricId, typicalPeriodGrowth),
      displayGrowth: formatGrowthDelta(row.id, growth),
      displayGrowthRelativePercent: formatGrowthRelativeToQuantityPercent(growth, quantity),
      displayQuantity: formatChannelPostMetricValue(row.id, quantity),
    };
  });
}

export function formatChannelPostMetricValue(metricId: string, value: number): string {
  if (isErMetric(metricId)) return `${value.toFixed(1)}%`;
  return formatNumber(Math.round(value));
}

function formatChannelMomentCount(
  metricId: string,
  value: number,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  const metric = CHANNEL_METRICS.find((item) => item.id === metricId);
  if (!metric) return formatNumber(value);

  if ("isEr" in metric && metric.isEr) {
    return `ER ${(value / 10).toFixed(1)}%`;
  }

  const total = cumulativeChannelValue(values, pointIndex, priorCumulative);
  if (!("countForms" in metric)) return formatNumber(total);

  return `${formatNumber(total)} ${pluralRu(total, metric.countForms)}`;
}

function formatChannelIndexGrowthPercent(index: number): string {
  const growth = index - 1;
  const sign = growth >= 0 ? "+" : "−";
  return `${sign}${Math.abs(growth * 100).toFixed(1)}%`;
}

function formatChannelPointGrowthPercentInParens(
  metricId: string,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  const index = channelPeriodIndexRatio(metricId, values, pointIndex, priorCumulative);
  return formatChannelIndexGrowthPercent(index);
}

/** Числовой прирост за шаг — строка с названием метрики в тултипе. */
export function formatChannelGrowthBadge(
  metricId: string,
  value: number,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  return formatChannelPointGrowthDelta(metricId, value, pointIndex, values, priorCumulative);
}

/** Процентный прирост от базы графика до точки — отдельная строка в тултипе. */
export function formatChannelPointPercentGrowth(
  metricId: string,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  return formatChannelPointGrowthPercentInParens(metricId, pointIndex, values, priorCumulative);
}

/** @deprecated Используйте formatChannelGrowthBadge */
export function formatChannelGrowthPercent(
  metricId: string,
  value: number,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  return formatChannelGrowthBadge(metricId, value, pointIndex, values, priorCumulative);
}

export function formatChannelGrowthPrimary(
  metricId: string,
  value: number,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  return formatChannelMomentCount(metricId, value, pointIndex, values, priorCumulative);
}

function formatChannelPointGrowthDelta(
  metricId: string,
  value: number,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  if (isErMetric(metricId)) {
    const current = value / 10;
    const previous =
      pointIndex > 0 ? (values[pointIndex - 1] ?? 0) / 10 : priorCumulative / 10;
    const delta = current - previous;
    const sign = delta >= 0 ? "+" : "−";
    return `${sign}${Math.abs(delta).toFixed(1)}%`;
  }

  const total = cumulativeChannelValue(values, pointIndex, priorCumulative);
  const prevTotal =
    pointIndex > 0
      ? cumulativeChannelValue(values, pointIndex - 1, priorCumulative)
      : priorCumulative;
  const delta = Math.round(total - prevTotal);
  const sign = delta >= 0 ? "+" : "−";
  return `${sign}${formatNumber(Math.abs(delta))}`;
}

