import {
  buildChannelChartLabels,
  extractChannelMetricSeriesForChart,
  getChannelChartPeriodDaySpan,
  getChannelEndTotals,
  getChannelStartTotals,
  getMetricTypicalPeriodGrowth,
  isChannelErMetric,
  isChannelSubscribersAvailable,
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

/** Ось Y — абсолютное значение метрики на каждой точке (своя шкала в мини-графике). */
export function buildChannelTrendPlotYValues(
  metricId: string,
  values: number[],
  priorCumulative = 0,
): number[] {
  if (isErMetric(metricId)) {
    return values.map((value) => value / 10);
  }
  return values.map((_, pointIndex) =>
    cumulativeChannelValue(values, pointIndex, priorCumulative),
  );
}

/**
 * Прирост метрики за каждый временной слот (высота столбца).
 * Для счётных метрик values уже являются поинтервальными приростами; для ER берём
 * разницу уровней между соседними слотами (в процентных пунктах).
 */
export function buildChannelMetricGrowthBars(
  metricId: string,
  values: number[],
  priorCumulative = 0,
): number[] {
  if (isErMetric(metricId)) {
    return values.map((value, index) => {
      const level = (value ?? 0) / 10;
      const prevLevel = index > 0 ? (values[index - 1] ?? 0) / 10 : priorCumulative / 10;
      return level - prevLevel;
    });
  }
  return values.map((value) => value ?? 0);
}

/**
 * Высота столбцов в карточке. Для счётных метрик — поинтервальный прирост;
 * для ER — абсолютный уровень в каждом слоте (не прирост).
 */
export function buildChannelMetricBarSeries(
  metricId: string,
  values: number[],
  priorCumulative = 0,
): number[] {
  if (isErMetric(metricId)) {
    return values.map((value) => (value ?? 0) / 10);
  }
  return buildChannelMetricGrowthBars(metricId, values, priorCumulative);
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

  // Telegram может скрывать число подписчиков — тогда метрику не показываем.
  const metrics = isChannelSubscribersAvailable()
    ? CHANNEL_METRICS
    : CHANNEL_METRICS.filter((metric) => metric.id !== "subscribers");

  const series: TrendSeriesRow[] = metrics.map((metric) => {
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

/**
 * ER на момент столбца — уровень (накопленные реакции+комментарии / накопленные
 * просмотры), а не дневная дельта. Дневная дельта давала 0 в неактивные дни и
 * случайные всплески, хотя ER так себя не ведёт. Точки до появления данных
 * (накопленные просмотры = 0) остаются нулевыми — «канал ещё не был подключён».
 */
function rebuildErSeriesAsLevel(series: TrendSeriesRow[]): void {
  const erRow = series.find((row) => isErMetric(row.id));
  if (!erRow) return;
  const views = series.find((row) => row.id === "views");
  const reactions = series.find((row) => row.id === "reactions");
  const comments = series.find((row) => row.id === "comments");
  if (!views || !reactions) return;

  const cumViews = views.yValues ?? [];
  const cumReactions = reactions.yValues ?? [];
  const cumComments = comments?.yValues ?? [];

  const levelValues = erRow.values.map((_, index) => {
    const v = cumViews[index] ?? 0;
    if (v <= 0) return 0;
    const r = cumReactions[index] ?? 0;
    const c = cumComments[index] ?? 0;
    const level = ((r + c) / v) * 100;
    return Math.round(level * 10);
  });

  erRow.values = levelValues;
  erRow.priorCumulative = 0;
  erRow.yValues = buildChannelTrendPlotYValues(erRow.id, levelValues, 0);
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

function formatGrowthDelta(metricId: string, growth: number) {
  if (isErMetric(metricId)) {
    const sign = growth >= 0 ? "+" : "−";
    return `${sign}${Math.abs(growth).toFixed(1)}%`;
  }
  const sign = growth >= 0 ? "+" : "−";
  return `${sign}${formatNumber(Math.round(Math.abs(growth)))}`;
}

/** Заголовок карточки метрики: «Подписчики 98 (+4)». */
export function formatChannelMetricCardHeadline(
  label: string,
  total: string,
  growth: string,
): string {
  return `${label} ${total} (${growth})`;
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
    // Прирост за период — чистое изменение на той же базе, что и итог
    // (endTotals − startTotals). Так прирост согласован с показанным итогом и
    // не может его превысить (в отличие от суммы дельт снимков, которая
    // включает удалённые посты).
    const endQuantity = getChannelCurrentTotals()[metricId] ?? 0;
    const startQuantity = getChannelStartTotals()[metricId] ?? 0;
    const growth = endQuantity - startQuantity;
    const typicalPeriodGrowth = getMetricTypicalPeriodGrowth(metricId, periodDaySpan);
    // Итог — текущее значение метрики на платформе (не зависит от выбранного
    // периода).
    const quantity = endQuantity;

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

/** Человекочитаемая дата начала отслеживания метрик канала. */
export function formatChannelTrackingSinceLabel(isoDate: string): string | null {
  const normalized = isoDate.includes("T") ? isoDate : `${isoDate}T12:00:00`;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;

  const RU_MONTH_GENITIVE = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
  ] as const;

  return `${parsed.getDate()} ${RU_MONTH_GENITIVE[parsed.getMonth()]} ${parsed.getFullYear()}`;
}

/** Человекочитаемый возраст последнего снимка аналитики ("5 мин", "3 ч", "2 дн"). */
export function formatDataAgeLabel(ageSeconds: number): string {
  if (ageSeconds < 60) return "меньше минуты";
  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч`;
  const days = Math.floor(hours / 24);
  return `${days} дн`;
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

function formatPeriodGrowthPercent(
  metricId: string,
  values: number[],
  pointIndex: number,
  priorCumulative = 0,
): string {
  if (isErMetric(metricId)) {
    const current = (values[pointIndex] ?? 0) / 10;
    const periodStart =
      priorCumulative > 0 ? priorCumulative / 10 : (values[0] ?? 0) / 10;
    const delta = current - periodStart;
    if (Math.abs(delta) < 0.05) return "+0.0%";
    if (periodStart <= 0) {
      if (current <= 0) return "+0.0%";
      const percent = (delta / current) * 100;
      const sign = percent >= 0 ? "+" : "−";
      return `${sign}${Math.abs(percent).toFixed(1)}%`;
    }
    const percent = (delta / periodStart) * 100;
    const sign = percent >= 0 ? "+" : "−";
    return `${sign}${Math.abs(percent).toFixed(1)}%`;
  }

  const periodStart = priorCumulative;
  const total = cumulativeChannelValue(values, pointIndex, priorCumulative);
  const delta = Math.round(total - periodStart);
  if (delta === 0) return "+0.0%";
  if (periodStart <= 0) {
    if (total <= 0) return "+0.0%";
    const percent = (delta / total) * 100;
    const sign = percent >= 0 ? "+" : "−";
    return `${sign}${Math.abs(percent).toFixed(1)}%`;
  }
  const percent = (delta / periodStart) * 100;
  const sign = percent >= 0 ? "+" : "−";
  return `${sign}${Math.abs(percent).toFixed(1)}%`;
}

function formatChannelPointGrowthPercentInParens(
  metricId: string,
  pointIndex: number,
  values: number[],
  priorCumulative = 0,
): string {
  return formatPeriodGrowthPercent(metricId, values, pointIndex, priorCumulative);
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

  const delta = Math.round(value ?? 0);
  const sign = delta >= 0 ? "+" : "−";
  return `${sign}${formatNumber(Math.abs(delta))}`;
}

