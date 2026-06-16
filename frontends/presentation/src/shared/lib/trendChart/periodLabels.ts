const LAST_24_HOURS_POINTS = 24;
const LAST_7_DAYS_POINTS = 7;
const LAST_30_DAYS_POINTS = 30;
const LAST_90_DAYS_POINTS = 30;
const LAST_90_DAYS_STEP = 3;
const LAST_90_DAYS_SPAN = LAST_90_DAYS_POINTS * LAST_90_DAYS_STEP;
const PLATFORM_LIFETIME_MONTHS = 6;

/** Фиксированные подписи месяцев — без Intl (SSR и браузер расходятся в «short»). */
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

const RU_MONTH_AXIS_SHORT = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
] as const;

/** Максимум точек на оси X в мобильной версии графиков */
export const MOBILE_CHART_MAX_POINTS = 8;

/** Desktop/tablet: при шапке ≤1080px — не более 15 диапазонов (вместо 30). */
export const COMPACT_HEADER_CHART_MAX_POINTS = 15;

/** Desktop/tablet: при шапке ≤640px — не более 10 диапазонов. */
export const NARROW_HEADER_CHART_MAX_POINTS = 10;

export type PeriodChartLabelOptions = {
  maxPoints?: number;
};

export function resolveTrendChartMaxPoints(options: {
  isMobile: boolean;
  isHeaderLe1080: boolean;
  isHeaderLe640: boolean;
}): number | undefined {
  if (options.isMobile) return MOBILE_CHART_MAX_POINTS;
  if (options.isHeaderLe640) return NARROW_HEADER_CHART_MAX_POINTS;
  if (options.isHeaderLe1080) return COMPACT_HEADER_CHART_MAX_POINTS;
  return undefined;
}

export function getFullPeriodPointCount(period: number): number {
  if (period === 0) return LAST_24_HOURS_POINTS;
  if (period === 1) return LAST_7_DAYS_POINTS;
  if (period === 2) return LAST_30_DAYS_POINTS;
  if (period === 3) return LAST_90_DAYS_POINTS;
  if (period === 4) return PLATFORM_LIFETIME_MONTHS;
  return 0;
}

function isReducedChartPointCount(period: number, pointCount: number): boolean {
  const full = getFullPeriodPointCount(period);
  return full > 0 && pointCount > 0 && pointCount < full;
}

/** Индекс точки на усечённой оси → диапазон в полном периоде (0 … totalUnits − 1). */
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

function formatAxisDateLabel(date: Date) {
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}`;
}

function formatAxisHourLabel(date: Date) {
  return `${String(date.getHours()).padStart(2, "0")}:00`;
}

function formatAxisMonthLabel(date: Date) {
  return RU_MONTH_AXIS_SHORT[date.getMonth()];
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

function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function startOfMonth(date: Date) {
  const next = new Date(date);
  next.setDate(1);
  next.setHours(0, 0, 0, 0);
  return next;
}

function endOfMonth(date: Date) {
  return endOfDay(new Date(date.getFullYear(), date.getMonth() + 1, 0));
}

function buildLast24HoursChartLabels(now = getChartReferenceNow(0)) {
  const end = new Date(now);
  end.setMinutes(0, 0, 0);

  return Array.from({ length: LAST_24_HOURS_POINTS }, (_, index) => {
    const hour = new Date(end);
    hour.setHours(hour.getHours() - (LAST_24_HOURS_POINTS - 1 - index));
    return formatAxisHourLabel(hour);
  });
}

function buildLast7DaysChartLabels(now = getChartReferenceNow(1)) {
  return Array.from({ length: LAST_7_DAYS_POINTS }, (_, index) => {
    const day = startOfDay(addDays(now, -(LAST_7_DAYS_POINTS - 1 - index)));
    return formatAxisDateLabel(day);
  });
}

function buildLast30DaysChartLabels(now = getChartReferenceNow(2)) {
  const periodStart = startOfDay(addDays(now, -(LAST_30_DAYS_POINTS - 1)));
  return Array.from({ length: LAST_30_DAYS_POINTS }, (_, index) => {
    const day = addDays(periodStart, index);
    return formatAxisDateLabel(day);
  });
}

function buildLast90DaysChartLabels(now = getChartReferenceNow(3)) {
  const periodStart = startOfDay(addDays(now, -(LAST_90_DAYS_POINTS * LAST_90_DAYS_STEP - 1)));
  return Array.from({ length: LAST_90_DAYS_POINTS }, (_, index) => {
    const day = addDays(periodStart, index * LAST_90_DAYS_STEP);
    return formatAxisDateLabel(day);
  });
}

function buildAllTimeChartLabels(now = getChartReferenceNow(4)) {
  const currentMonthStart = startOfMonth(now);
  return Array.from({ length: PLATFORM_LIFETIME_MONTHS }, (_, index) => {
    const month = new Date(currentMonthStart);
    month.setMonth(month.getMonth() - (PLATFORM_LIFETIME_MONTHS - 1 - index));
    return formatAxisMonthLabel(month);
  });
}

function buildReducedPeriodChartLabels(period: number, maxPoints: number) {
  const now = getChartReferenceNow(period);

  if (period === 0) {
    const total = LAST_24_HOURS_POINTS;
    const count = Math.min(maxPoints, total);
    const end = new Date(now);
    end.setMinutes(0, 0, 0);
    return Array.from({ length: count }, (_, index) => {
      const { start } = displayIndexToSpan(index, count, total);
      const hour = new Date(end);
      hour.setHours(hour.getHours() - (total - 1 - start));
      return formatAxisHourLabel(hour);
    });
  }

  if (period === 1) {
    return buildLast7DaysChartLabels(now);
  }

  if (period === 2) {
    const total = LAST_30_DAYS_POINTS;
    const count = Math.min(maxPoints, total);
    const periodStart = startOfDay(addDays(now, -(total - 1)));
    return Array.from({ length: count }, (_, index) => {
      const { start } = displayIndexToSpan(index, count, total);
      return formatAxisDateLabel(addDays(periodStart, start));
    });
  }

  if (period === 3) {
    const total = LAST_90_DAYS_SPAN;
    const count = Math.min(maxPoints, LAST_90_DAYS_POINTS);
    const periodStart = startOfDay(addDays(now, -(total - 1)));
    return Array.from({ length: count }, (_, index) => {
      const { start } = displayIndexToSpan(index, count, total);
      return formatAxisDateLabel(addDays(periodStart, start));
    });
  }

  if (period === 4) {
    return buildAllTimeChartLabels(now);
  }

  return [];
}

export function getPeriodChartLabels(period: number, options?: PeriodChartLabelOptions) {
  const fullCount = getFullPeriodPointCount(period);
  const maxPoints = options?.maxPoints;
  if (!maxPoints || fullCount <= maxPoints) {
    if (period === 0) return buildLast24HoursChartLabels();
    if (period === 1) return buildLast7DaysChartLabels();
    if (period === 2) return buildLast30DaysChartLabels();
    if (period === 3) return buildLast90DaysChartLabels();
    if (period === 4) return buildAllTimeChartLabels();
    return [];
  }
  return buildReducedPeriodChartLabels(period, maxPoints);
}

/** Stable anchor for SSR/hydration and chart bounds (no live clock in tooltips). */
function getChartReferenceNow(period: number) {
  const now = new Date();
  if (period === 0) {
    now.setMinutes(0, 0, 0);
    return now;
  }
  return startOfDay(now);
}

function formatTrendRangePart(date: Date, withTime: boolean) {
  const day = date.getDate();
  const month = RU_MONTH_GENITIVE[date.getMonth()];
  if (withTime) {
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    return `${day} ${month}, ${hh}:${mm}`;
  }
  return `${day} ${month}`;
}

function getTrendPointPeriodBounds(
  period: number,
  pointIndex: number,
  pointCount: number,
  now = getChartReferenceNow(period),
): { from: Date; to: Date } {
  if (pointCount <= 0) return { from: now, to: now };

  switch (period) {
    case 0: {
      if (isReducedChartPointCount(0, pointCount)) {
        const total = LAST_24_HOURS_POINTS;
        const end = new Date(now);
        end.setMinutes(0, 0, 0);
        const { start, end: hourEnd } = displayIndexToSpan(pointIndex, pointCount, total);
        const from = new Date(end);
        from.setHours(from.getHours() - (total - 1 - start));
        const to = new Date(end);
        to.setHours(to.getHours() - (total - 1 - hourEnd));
        to.setHours(to.getHours() + 1);
        return { from, to };
      }
      const end = new Date(now);
      const from = new Date(end);
      from.setHours(from.getHours() - (pointCount - 1 - pointIndex));
      const to = new Date(from);
      to.setHours(to.getHours() + 1);
      return { from, to };
    }
    case 1: {
      const day = addDays(now, -(pointCount - 1 - pointIndex));
      const from = startOfDay(day);
      return { from, to: endOfDay(day) };
    }
    case 2: {
      if (isReducedChartPointCount(2, pointCount)) {
        const total = LAST_30_DAYS_POINTS;
        const periodStart = startOfDay(addDays(now, -(total - 1)));
        const { start, end } = displayIndexToSpan(pointIndex, pointCount, total);
        const from = startOfDay(addDays(periodStart, start));
        const to = endOfDay(addDays(periodStart, end));
        return { from, to };
      }
      const day = addDays(now, -(pointCount - 1 - pointIndex));
      const from = startOfDay(day);
      return { from, to: endOfDay(day) };
    }
    case 3: {
      if (isReducedChartPointCount(3, pointCount)) {
        const total = LAST_90_DAYS_SPAN;
        const periodStart = startOfDay(addDays(now, -(total - 1)));
        const { start, end } = displayIndexToSpan(pointIndex, pointCount, total);
        const from = startOfDay(addDays(periodStart, start));
        const to = endOfDay(addDays(periodStart, end));
        return { from, to };
      }
      const periodStart = startOfDay(addDays(now, -(pointCount * LAST_90_DAYS_STEP - 1)));
      const from = startOfDay(addDays(periodStart, pointIndex * LAST_90_DAYS_STEP));
      const to = endOfDay(addDays(from, LAST_90_DAYS_STEP - 1));
      return { from, to };
    }
    case 4: {
      const currentMonthStart = startOfMonth(now);
      const month = new Date(currentMonthStart);
      month.setMonth(month.getMonth() - (pointCount - 1 - pointIndex));
      const from = startOfMonth(month);
      return { from, to: endOfMonth(month) };
    }
    default:
      return { from: now, to: now };
  }
}

export function formatTrendPointPeriod(
  period: number,
  pointIndex: number,
  pointCount: number,
  now = getChartReferenceNow(period),
) {
  const { from, to } = getTrendPointPeriodBounds(period, pointIndex, pointCount, now);
  const useTime = period === 0 || from.toDateString() === to.toDateString();
  return `${formatTrendRangePart(from, useTime)} — ${formatTrendRangePart(to, useTime)}`;
}

/** Интервал от начала графика (точка 0) до конца выбранной точки. */
export function formatTrendChartRangeFromStart(
  period: number,
  pointIndex: number,
  pointCount: number,
  now = getChartReferenceNow(period),
) {
  const start = getTrendPointPeriodBounds(period, 0, pointCount, now);
  const end = getTrendPointPeriodBounds(period, pointIndex, pointCount, now);
  const withTime = period === 0 || end.from.toDateString() === end.to.toDateString();
  return `${formatTrendRangePart(start.from, withTime)} — ${formatTrendRangePart(end.to, withTime)}`;
}

export function getTrendPointXPercent(
  index: number,
  pointCount: number,
  edgeInsetPercent = 0,
) {
  if (pointCount <= 1) return 50;
  const t = index / (pointCount - 1);
  const inset = Math.max(0, Math.min(edgeInsetPercent, 40));
  const span = 100 - 2 * inset;
  return inset + t * span;
}
