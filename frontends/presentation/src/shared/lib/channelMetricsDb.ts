import { channelMetrics110d, type ChannelMetricsDataset } from "@/shared/data/analytics-seed";
import { presentationChannelMetrics } from "@/shared/data/presentation-analytics-seed";
import { DEMO_ACCOUNT_ID, PRESENTATION_ACCOUNT_ID } from "@/shared/lib/auth/constants";
import {
  formatTrendChartRangeFromStart,
  formatTrendPointPeriod,
  getPeriodChartLabels,
} from "@/shared/lib/trendChart/periodLabels";

export type ChannelMetricId =
  | "subscribers"
  | "reactions"
  | "views"
  | "comments"
  | "reposts"
  | "er";

export type ChannelDayRecord = Record<ChannelMetricId, number>;

export type ChannelMetricsDatabase = {
  version: number;
  dayCount: number;
  startTotals: ChannelDayRecord;
  endTotals: ChannelDayRecord;
  days: ChannelDayRecord[];
};

function cloneMetricsDataset(source: ChannelMetricsDataset): ChannelMetricsDatabase {
  return {
    version: source.version,
    dayCount: source.dayCount,
    startTotals: { ...source.startTotals },
    endTotals: { ...source.endTotals },
    days: source.days.map((day) => ({
      subscribers: day.subscribers,
      reactions: day.reactions,
      views: day.views,
      comments: day.comments,
      reposts: day.reposts,
      er: day.er,
    })),
  };
}

let activeMetricsAccountId = DEMO_ACCOUNT_ID;
let db = cloneMetricsDataset(channelMetrics110d);

export function setChannelMetricsAccount(accountId: string) {
  if (accountId === activeMetricsAccountId) return;
  activeMetricsAccountId = accountId;
  const source =
    accountId === PRESENTATION_ACCOUNT_ID ? presentationChannelMetrics : channelMetrics110d;
  db = cloneMetricsDataset(source);
}

export function getChannelMetricsDatabase(): ChannelMetricsDatabase {
  return db;
}

export const CHANNEL_METRICS_DAY_COUNT = db.dayCount;

const CHANNEL_ALL_TIME_MAX_LABELS = 30;

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

function displayIndexToSpan(
  pointIndex: number,
  pointCount: number,
  totalUnits: number,
): { start: number; end: number } {
  if (totalUnits <= 1 || pointCount <= 1) {
    return { start: 0, end: Math.max(0, totalUnits - 1) };
  }
  const start = Math.round((pointIndex / (pointCount - 1)) * (totalUnits - 1));
  const end =
    pointIndex >= pointCount - 1
      ? totalUnits - 1
      : Math.max(
          start,
          Math.round(((pointIndex + 1) / (pointCount - 1)) * (totalUnits - 1)) - 1,
        );
  return { start, end };
}

function getChannelDataAnchorNow() {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return now;
}

function getChannelDayDate(dayIndex: number) {
  const day = getChannelDataAnchorNow();
  day.setDate(day.getDate() - (db.dayCount - 1 - dayIndex));
  return day;
}

function startOfDay(date: Date) {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
}

function endOfDay(date: Date) {
  const next = new Date(date);
  next.setHours(23, 59, 59, 999);
  return next;
}

function formatAxisDateLabel(date: Date) {
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}`;
}

function formatTrendRangePart(date: Date) {
  const day = date.getDate();
  const month = RU_MONTH_GENITIVE[date.getMonth()];
  return `${day} ${month}`;
}

function resolveChannelPointCount(
  chartPeriod: number,
  windowDays: number,
  maxPoints?: number,
) {
  if (maxPoints != null && maxPoints > 0) {
    return Math.min(maxPoints, windowDays);
  }
  if (chartPeriod === 4) {
    return Math.min(windowDays, CHANNEL_ALL_TIME_MAX_LABELS);
  }
  return windowDays;
}

export function buildChannelChartLabels(
  chartPeriod: number,
  options?: { maxPoints?: number },
) {
  if (chartPeriod === 0) {
    return getPeriodChartLabels(0, options);
  }

  const daySpan = Math.min(chartPeriodToDaySpan(chartPeriod), db.dayCount);
  const sliceStart = db.days.length - daySpan;
  const pointCount = resolveChannelPointCount(chartPeriod, daySpan, options?.maxPoints);

  if (pointCount >= daySpan) {
    return Array.from({ length: daySpan }, (_, index) =>
      formatAxisDateLabel(getChannelDayDate(sliceStart + index)),
    );
  }

  return Array.from({ length: pointCount }, (_, index) => {
    const { start } = displayIndexToSpan(index, pointCount, daySpan);
    return formatAxisDateLabel(getChannelDayDate(sliceStart + start));
  });
}

export function getChannelTrendPointPeriodBounds(
  chartPeriod: number,
  pointIndex: number,
  pointCount: number,
) {
  const daySpan = Math.min(chartPeriodToDaySpan(chartPeriod), db.dayCount);
  const sliceStart = db.days.length - daySpan;

  if (pointCount >= daySpan) {
    const from = startOfDay(getChannelDayDate(sliceStart + pointIndex));
    return { from, to: endOfDay(from) };
  }

  const { start, end } = displayIndexToSpan(pointIndex, pointCount, daySpan);
  const from = startOfDay(getChannelDayDate(sliceStart + start));
  const to = endOfDay(getChannelDayDate(sliceStart + end));
  return { from, to };
}

export function formatChannelTrendPointPeriod(
  chartPeriod: number,
  pointIndex: number,
  pointCount: number,
) {
  if (chartPeriod === 0) {
    return formatTrendPointPeriod(0, pointIndex, pointCount);
  }
  const { from, to } = getChannelTrendPointPeriodBounds(chartPeriod, pointIndex, pointCount);
  return `${formatTrendRangePart(from)} — ${formatTrendRangePart(to)}`;
}

export function formatChannelTrendChartRangeFromStart(
  chartPeriod: number,
  pointIndex: number,
  pointCount: number,
) {
  if (chartPeriod === 0) {
    return formatTrendChartRangeFromStart(0, pointIndex, pointCount);
  }
  const start = getChannelTrendPointPeriodBounds(chartPeriod, 0, pointCount);
  const end = getChannelTrendPointPeriodBounds(chartPeriod, pointIndex, pointCount);
  return `${formatTrendRangePart(start.from)} — ${formatTrendRangePart(end.to)}`;
}

export function getChannelEndTotals(): ChannelDayRecord {
  return { ...db.endTotals };
}

export function isChannelErMetric(metricId: string) {
  return metricId === "er";
}

export function getChannelChartPeriodDaySpan(chartPeriod: number) {
  return chartPeriodToDaySpan(chartPeriod);
}

function chartPeriodToDaySpan(chartPeriod: number) {
  switch (chartPeriod) {
    case 0:
      return 1;
    case 1:
      return 7;
    case 2:
      return 30;
    case 3:
      return 90;
    case 4:
      return db.dayCount;
    default:
      return 7;
  }
}

function cumulativeCountMetric(metricId: ChannelMetricId, throughDayIndex: number) {
  let total = db.startTotals[metricId] ?? 0;
  for (let i = 0; i <= throughDayIndex && i < db.days.length; i++) {
    total += db.days[i]?.[metricId] ?? 0;
  }
  return total;
}

function priorCumulativeForMetric(metricId: ChannelMetricId, dayIndexBeforeWindow: number) {
  if (isChannelErMetric(metricId)) {
    if (dayIndexBeforeWindow < 0) {
      return Math.round((db.startTotals.er ?? 0) * 10);
    }
    return Math.round((db.days[dayIndexBeforeWindow]?.er ?? db.startTotals.er) * 10);
  }
  return cumulativeCountMetric(metricId, dayIndexBeforeWindow);
}

function hashHour(seed: number) {
  let t = (seed * 2654435761) >>> 0;
  t ^= t >>> 16;
  return (t & 0xffff) / 0xffff;
}

function splitDayDeltaIntoHours(delta: number, hours: number, seed: number) {
  if (hours <= 1) return [delta];
  const weights = Array.from({ length: hours }, (_, hour) => 0.25 + hashHour(seed + hour) * 1.5);
  const weightSum = weights.reduce((sum, weight) => sum + weight, 0);
  const scaled = weights.map((weight) => (weight / weightSum) * delta);
  const rounded = scaled.map((value) => Math.round(value));
  const drift = delta - rounded.reduce((sum, value) => sum + value, 0);
  rounded[rounded.length - 1] += drift;
  return rounded;
}

function bucketSum(values: number[], bucketCount: number) {
  if (bucketCount <= 0) return [];
  if (bucketCount >= values.length) return [...values];
  const buckets: number[] = [];
  for (let bucket = 0; bucket < bucketCount; bucket++) {
    const start = Math.floor((bucket / bucketCount) * values.length);
    const end = Math.floor(((bucket + 1) / bucketCount) * values.length);
    let sum = 0;
    for (let i = start; i < end; i++) sum += values[i] ?? 0;
    buckets.push(sum);
  }
  return buckets;
}

function bucketLast(values: number[], bucketCount: number) {
  if (bucketCount <= 0) return [];
  if (bucketCount >= values.length) return [...values];
  const buckets: number[] = [];
  for (let bucket = 0; bucket < bucketCount; bucket++) {
    const end = Math.floor(((bucket + 1) / bucketCount) * values.length) - 1;
    const index = Math.max(0, Math.min(values.length - 1, end));
    buckets.push(values[index] ?? 0);
  }
  return buckets;
}

export function extractChannelMetricSeriesForChart(
  metricId: ChannelMetricId,
  chartPeriod: number,
  pointCount: number,
): { values: number[]; priorCumulative: number } {
  const daySpan = Math.min(chartPeriodToDaySpan(chartPeriod), db.days.length);
  const sliceStart = Math.max(0, db.days.length - daySpan);
  const windowDays = db.days.slice(sliceStart);
  const priorDayIndex = sliceStart - 1;
  const priorCumulative = priorCumulativeForMetric(metricId, priorDayIndex);

  if (chartPeriod === 0 && pointCount > 1) {
    const lastDay = windowDays[windowDays.length - 1] ?? db.days[db.days.length - 1];
    if (isChannelErMetric(metricId)) {
      const level = Math.round((lastDay?.er ?? db.endTotals.er) * 10);
      return { values: Array.from({ length: pointCount }, () => level), priorCumulative };
    }
    const seed = sliceStart * 17 + metricId.length;
    return {
      values: splitDayDeltaIntoHours(lastDay?.[metricId] ?? 0, pointCount, seed),
      priorCumulative,
    };
  }

  const raw = windowDays.map((day) =>
    isChannelErMetric(metricId) ? Math.round(day.er * 10) : day[metricId],
  );

  const values = isChannelErMetric(metricId)
    ? bucketLast(raw, pointCount)
    : bucketSum(raw, pointCount);

  return { values, priorCumulative };
}

export function getMetricHistoricalAverageDailyDelta(metricId: ChannelMetricId) {
  if (isChannelErMetric(metricId)) {
    let sum = 0;
    let prev = db.startTotals.er;
    for (const day of db.days) {
      sum += day.er - prev;
      prev = day.er;
    }
    return sum / db.days.length;
  }
  const sum = db.days.reduce((acc, day) => acc + (day[metricId] ?? 0), 0);
  return sum / db.days.length;
}

export function getMetricTypicalPeriodGrowth(metricId: ChannelMetricId, daySpan: number) {
  const span = Math.max(1, Math.min(daySpan, db.dayCount));
  return getMetricHistoricalAverageDailyDelta(metricId) * span;
}
