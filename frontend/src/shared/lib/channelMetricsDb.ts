import { channelMetrics110d, type ChannelMetricsDataset } from "@/shared/data/analytics-seed";
import { presentationChannelMetrics } from "@/shared/data/presentation-analytics-seed";
import { PRESENTATION_ACCOUNT_ID } from "@/shared/lib/auth/constants";
import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
import {
  formatTrendChartRangeFromStart,
  formatTrendPointPeriod,
  getFullPeriodPointCount,
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

export type ChannelDayEntry = ChannelDayRecord & { date?: string };

export type ChannelMetricsGranularity = "day" | "30m";

export type ChannelMetricsDatabase = {
  version: number;
  dayCount: number;
  granularity: ChannelMetricsGranularity;
  subscribersAvailable: boolean;
  startTotals: ChannelDayRecord;
  endTotals: ChannelDayRecord;
  days: ChannelDayEntry[];
};

type ChannelMetricsSource = ChannelMetricsDataset & {
  granularity?: ChannelMetricsGranularity;
  subscribersAvailable?: boolean;
};

function cloneMetricsDataset(source: ChannelMetricsSource): ChannelMetricsDatabase {
  return {
    version: source.version,
    dayCount: source.dayCount,
    granularity: source.granularity ?? "day",
    subscribersAvailable: source.subscribersAvailable ?? true,
    startTotals: { ...source.startTotals },
    endTotals: { ...source.endTotals },
    days: source.days.map((day) => ({
      date: day.date,
      subscribers: day.subscribers,
      reactions: day.reactions,
      views: day.views,
      comments: day.comments,
      reposts: day.reposts,
      er: day.er,
    })),
  };
}

function emptyMetricsDataset(): ChannelMetricsDatabase {
  const zeroTotals = (): ChannelDayRecord => ({
    subscribers: 0,
    reactions: 0,
    views: 0,
    comments: 0,
    reposts: 0,
    er: 0,
  });
  return {
    version: 1,
    dayCount: 1,
    granularity: "day",
    subscribersAvailable: true,
    startTotals: zeroTotals(),
    endTotals: zeroTotals(),
    days: [zeroTotals()],
  };
}

/** Real accounts start empty until analytics API data arrives; demo/presentation use seed. */
function seedForAccount(accountId: string): ChannelMetricsDatabase {
  if (accountId === PRESENTATION_ACCOUNT_ID) {
    return cloneMetricsDataset(presentationChannelMetrics);
  }
  if (shouldPersistLocally()) {
    return cloneMetricsDataset(channelMetrics110d);
  }
  return emptyMetricsDataset();
}

let activeMetricsAccountId: string | undefined;
let db = emptyMetricsDataset();
let dbRevision = 0;

export function setChannelMetricsAccount(accountId: string) {
  if (accountId === activeMetricsAccountId) return;
  activeMetricsAccountId = accountId;
  db = seedForAccount(accountId);
  dbRevision += 1;
}

export function getChannelMetricsDatabase(): ChannelMetricsDatabase {
  return db;
}

/** Bumped whenever the database contents are replaced; use as a memo dependency. */
export function getChannelMetricsRevision(): number {
  return dbRevision;
}

export function loadChannelMetricsFromApi(
  dataset: ChannelMetricsDataset & {
    granularity?: ChannelMetricsGranularity;
    subscribersAvailable?: boolean;
  },
): void {
  db = cloneMetricsDataset(dataset);
  dbRevision += 1;
}

export function isChannelSubscribersAvailable(): boolean {
  return db.subscribersAvailable;
}

export function isChannel30mGranularity(): boolean {
  return db.granularity === "30m";
}

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

function parseDayDate(value: string | undefined): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : `${value}T12:00:00`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Date-only API fields are UTC calendar days; timestamps are absolute instants. */
function parseSnapshotMoment(value: string | undefined): Date | null {
  if (!value) return null;
  if (value.includes("T")) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function localDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localHourStarts(pointCount: number): Date[] {
  const end = new Date();
  end.setMinutes(0, 0, 0);
  return Array.from({ length: pointCount }, (_, index) => {
    const hour = new Date(end);
    hour.setHours(hour.getHours() - (pointCount - 1 - index));
    return hour;
  });
}

const DAY_MS = 24 * 60 * 60 * 1000;

function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function hasTimedSnapshots(): boolean {
  return db.days.some((entry) => entry.date?.includes("T"));
}

/**
 * Ось привязана к НОВЕЙШЕМУ снимку, а не к «сегодня»: крайний правый столбец —
 * это день последнего снимка (для живого канала он же «сейчас»). Так значения
 * и подписи не «уезжают» из-за расхождения UTC-календаря бэкенда и локального
 * времени пользователя, и одно и то же событие стоит на одном столбце во всех
 * периодах.
 */
function newestSnapshotDayStart(): Date {
  let newest: Date | null = null;
  for (const entry of db.days) {
    const moment = parseSnapshotMoment(entry.date);
    if (!moment) continue;
    if (!newest || moment.getTime() > newest.getTime()) newest = moment;
  }
  return startOfDay(newest ?? new Date());
}

function dailyAxisConfig(chartPeriod: number, pointCount: number): { step: number; count: number } {
  if (chartPeriod === 3) {
    return { step: 3, count: pointCount };
  }
  if (chartPeriod === 4) {
    const daySpan = Math.min(chartPeriodToDaySpan(chartPeriod), db.dayCount);
    const count = Math.min(daySpan, CHANNEL_ALL_TIME_MAX_LABELS);
    const step = Math.max(1, Math.ceil(daySpan / Math.max(1, count)));
    return { step, count };
  }
  return { step: 1, count: pointCount };
}

/**
 * Правый край ПОДПИСЕЙ — локальное «сегодня» (живой столбец = «сейчас»), но не
 * раньше новейшего снимка. Данные при этом привязаны к новейшей строке (см.
 * {@link metricByDayOffset}), поэтому живой снимок всегда попадает в столбец
 * «сегодня», даже если бэкенд датирует его вчерашним днём по UTC.
 */
function dailyLabelAnchor(): Date {
  const today = startOfDay(new Date());
  const newest = newestSnapshotDayStart();
  return today.getTime() >= newest.getTime() ? today : newest;
}

/** Даты столбцов, справа налево от «сегодня» (крайний правый = сегодня/живой). */
function dailyAxisStarts(chartPeriod: number, pointCount: number): Date[] {
  const anchor = dailyLabelAnchor();
  const { step, count } = dailyAxisConfig(chartPeriod, pointCount);
  return Array.from({ length: count }, (_, index) => {
    const columnsFromRight = count - 1 - index;
    return addDays(anchor, -(columnsFromRight * step));
  });
}

/** Прирост каждой метрики по смещению в днях от новейшего снимка (0 = новейший). */
function metricByDayOffset(metricId: ChannelMetricId): {
  deltas: Map<number, number>;
  erLevels: Map<number, number>;
} {
  const newest = newestSnapshotDayStart();
  const deltas = new Map<number, number>();
  const erLevels = new Map<number, number>();
  for (const entry of db.days) {
    const moment = parseSnapshotMoment(entry.date);
    if (!moment) continue;
    const offset = Math.round((newest.getTime() - startOfDay(moment).getTime()) / DAY_MS);
    if (offset < 0) continue;
    deltas.set(offset, (deltas.get(offset) ?? 0) + (entry[metricId] ?? 0));
    // db.days идут по возрастанию времени, поэтому перезапись оставляет уровень
    // самого позднего снимка в этом дне.
    erLevels.set(offset, Math.round((entry.er ?? 0) * 10));
  }
  return { deltas, erLevels };
}

function aggregate30mToLocalHours(metricId: ChannelMetricId, pointCount: number): number[] {
  const hourStarts = localHourStarts(pointCount);
  const windowStart = hourStarts[0] ?? new Date();
  const buckets = Array.from({ length: pointCount }, () => 0);
  const erLevels = Array.from({ length: pointCount }, () => 0);

  for (const entry of db.days) {
    const moment = parseSnapshotMoment(entry.date);
    if (!moment || moment < windowStart) continue;
    const hourIndex = hourStarts.findIndex((start) => {
      const end = new Date(start);
      end.setHours(end.getHours() + 1);
      return moment >= start && moment < end;
    });
    if (hourIndex < 0) continue;
    if (isChannelErMetric(metricId)) {
      erLevels[hourIndex] = Math.round(entry.er * 10);
    } else {
      buckets[hourIndex] += entry[metricId] ?? 0;
    }
  }

  return isChannelErMetric(metricId) ? erLevels : buckets;
}

/** 24ч без поминутных снимков: дневные дельты нельзя честно разложить по часам. */
function aggregateDailyRowsToLocalHours(metricId: ChannelMetricId, pointCount: number): number[] {
  const result = Array.from({ length: pointCount }, () => 0);
  // Подписчики меняются только на снимках; без таймстампов нельзя ставить
  // исторический +N в «текущий час».
  if (metricId === "subscribers") {
    return result;
  }
  const { deltas, erLevels } = metricByDayOffset(metricId);
  if (isChannelErMetric(metricId)) {
    result[pointCount - 1] = erLevels.get(0) ?? 0;
  } else {
    result[pointCount - 1] = deltas.get(0) ?? 0;
  }
  return result;
}

function extractDailySeriesAligned(
  metricId: ChannelMetricId,
  chartPeriod: number,
  pointCount: number,
): number[] {
  const { deltas, erLevels } = metricByDayOffset(metricId);
  const { step, count } = dailyAxisConfig(chartPeriod, pointCount);

  return Array.from({ length: count }, (_, index) => {
    const columnsFromRight = count - 1 - index;
    const baseOffset = columnsFromRight * step;
    if (isChannelErMetric(metricId)) {
      for (let sub = 0; sub < step; sub++) {
        const level = erLevels.get(baseOffset + sub);
        if (level != null) return level;
      }
      return 0;
    }
    let sum = 0;
    for (let sub = 0; sub < step; sub++) {
      sum += deltas.get(baseOffset + sub) ?? 0;
    }
    return sum;
  });
}

function getChannelDayDate(dayIndex: number) {
  // Реальные даты из API имеют приоритет; синтетика «сегодня минус N» — только
  // для seed-данных без dates.
  const apiDate = parseDayDate(db.days[dayIndex]?.date);
  if (apiDate) return apiDate;
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

function formatTimeLabel(date: Date) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function zeroDayEntry(): ChannelDayEntry {
  return {
    subscribers: 0,
    reactions: 0,
    views: 0,
    comments: 0,
    reposts: 0,
    er: 0,
  };
}

function windowDaysForChartPeriod(chartPeriod: number) {
  const targetDaySpan =
    chartPeriod === 4 ? Math.min(chartPeriodToDaySpan(chartPeriod), db.dayCount) : chartPeriodToDaySpan(chartPeriod);
  const sliceStart = Math.max(0, db.days.length - targetDaySpan);
  const windowDays = db.days.slice(sliceStart);
  if (chartPeriod === 4 || windowDays.length >= targetDaySpan) {
    return windowDays;
  }
  const padding = targetDaySpan - windowDays.length;
  return [...Array.from({ length: padding }, () => zeroDayEntry()), ...windowDays];
}

function useTimed24hSlots(chartPeriod: number) {
  return chartPeriod === 0 && hasTimedSnapshots();
}

function get30mSlotBounds(pointIndex: number, pointCount: number) {
  const hourStarts = localHourStarts(pointCount);
  const from = hourStarts[pointIndex] ?? new Date();
  const to = new Date(from);
  to.setHours(to.getHours() + 1);
  to.setMilliseconds(to.getMilliseconds() - 1);
  return { from, to };
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
  return getFullPeriodPointCount(chartPeriod);
}

export function buildChannelChartLabels(
  chartPeriod: number,
  options?: { maxPoints?: number },
) {
  if (chartPeriod === 0) {
    return getPeriodChartLabels(0, options);
  }

  const daySpan = Math.min(chartPeriodToDaySpan(chartPeriod), db.dayCount);
  const pointCount = resolveChannelPointCount(chartPeriod, daySpan, options?.maxPoints);
  return dailyAxisStarts(chartPeriod, pointCount).map((day) => formatAxisDateLabel(day));
}

export function getChannelTrendPointPeriodBounds(
  chartPeriod: number,
  pointIndex: number,
  pointCount: number,
) {
  if (chartPeriod === 0) {
    const hourStarts = localHourStarts(pointCount);
    const from = hourStarts[pointIndex] ?? new Date();
    const to = new Date(from);
    to.setHours(to.getHours() + 1);
    to.setMilliseconds(to.getMilliseconds() - 1);
    return { from, to };
  }
  const { step } = dailyAxisConfig(chartPeriod, pointCount);
  const dayStarts = dailyAxisStarts(chartPeriod, pointCount);
  const from = dayStarts[pointIndex] ?? startOfDay(new Date());
  return { from, to: endOfDay(addDays(from, step - 1)) };
}

export function formatChannelTrendPointPeriod(
  chartPeriod: number,
  pointIndex: number,
  pointCount: number,
) {
  if (useTimed24hSlots(chartPeriod)) {
    return formatTrendPointPeriod(0, pointIndex, pointCount);
  }
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
  if (useTimed24hSlots(chartPeriod)) {
    const start = get30mSlotBounds(0, pointCount);
    const end = get30mSlotBounds(pointIndex, pointCount);
    return `${formatTimeLabel(start.from)} — ${formatTimeLabel(end.to)}`;
  }
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

export function getChannelStartTotals(): ChannelDayRecord {
  return { ...db.startTotals };
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
  const sliceStart = Math.max(0, db.days.length - chartPeriodToDaySpan(chartPeriod));
  const priorDayIndex = sliceStart - 1;
  const priorCumulative = priorCumulativeForMetric(metricId, priorDayIndex);

  if (chartPeriod === 0 && pointCount > 1) {
    let values = hasTimedSnapshots()
      ? aggregate30mToLocalHours(metricId, pointCount)
      : aggregateDailyRowsToLocalHours(metricId, pointCount);

    if (isChannelErMetric(metricId)) {
      return { values, priorCumulative: priorCumulativeForMetric(metricId, -1) };
    }

    if (metricId === "subscribers") {
      const growthInWindow =
        (db.endTotals.subscribers ?? 0) - (db.startTotals.subscribers ?? 0);
      if (growthInWindow <= 0) {
        values = Array.from({ length: pointCount }, () => 0);
      }
    }

    // Итоговая линия должна заканчиваться на текущем итоге канала (endTotals), а
    // не на сумме суточных дельт (≈0, когда бэкенд не знает базу суточного окна).
    // Поэтому базовый уровень = endTotals − сумма дельт окна, тогда крайняя правая
    // точка совпадает с текущим значением метрики.
    const windowDelta = values.reduce((sum, value) => sum + (value ?? 0), 0);
    const startBaseline = (db.endTotals[metricId] ?? 0) - windowDelta;
    return { values, priorCumulative: startBaseline };
  }

  if (chartPeriod >= 1 && chartPeriod <= 4 && pointCount > 1) {
    const values = extractDailySeriesAligned(metricId, chartPeriod, pointCount);
    return { values, priorCumulative };
  }

  const windowDays = windowDaysForChartPeriod(chartPeriod);
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
