export type AnalyticsPeriod = "24h" | "7d" | "30d" | "90d" | "all";

export type ChannelDayMetrics = {
  date: string;
  views: number;
  posts: number;
  subscribers: number;
  reactions: number;
  comments: number;
  reposts: number;
  er: number;
};

export type ChannelMetricsDataset = {
  version: number;
  dayCount: number;
  startTotals: {
    subscribers: number;
    reactions: number;
    views: number;
    comments: number;
    reposts: number;
    er: number;
  };
  endTotals: {
    subscribers: number;
    reactions: number;
    views: number;
    comments: number;
    reposts: number;
    er: number;
  };
  days: ChannelDayMetrics[];
};

const DAY_COUNT = 110;

const startTotals = {
  subscribers: 200,
  reactions: 418,
  views: 12400,
  comments: 31,
  reposts: 12,
  er: 2.8,
};

function mulberry32(seed: number) {
  return function next() {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function maybeNegative(value: number, chance: number, rand: () => number): number {
  if (value <= 0) return value;
  if (rand() < chance) return -Math.abs(Math.round(value * (0.15 + rand() * 0.85)));
  return value;
}

function formatIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function generateChannelMetrics110d(): ChannelMetricsDataset {
  const rand = mulberry32(20260214);
  const randn = () => rand() * 2 - 1;

  const endDate = new Date("2026-06-09T12:00:00Z");
  const days: ChannelDayMetrics[] = [];
  let erLevel = startTotals.er;

  for (let d = 0; d < DAY_COUNT; d++) {
    const t = d / (DAY_COUNT - 1);
    const wave = Math.sin(d / 9) * 0.35 + Math.sin(d / 23) * 0.25;
    const growthPhase = 0.55 + t * 1.15 + wave * 0.2;
    const negScale = d < 20 ? 0.55 : 1;

    const dayDate = new Date(endDate);
    dayDate.setUTCDate(endDate.getUTCDate() - (DAY_COUNT - 1 - d));

    const subscribers = maybeNegative(
      Math.round((4 + t * 78 + randn() * 18) * growthPhase),
      0.1 * negScale,
      rand,
    );

    const reactions = maybeNegative(
      Math.round((5 + t * 20 + randn() * 12) * growthPhase * (0.85 + rand() * 0.35)),
      0.14 * negScale,
      rand,
    );

    const views = maybeNegative(
      Math.round((35 + t * 380 + randn() * 110) * growthPhase * (0.7 + rand() * 0.6)),
      0.1 * negScale,
      rand,
    );

    const comments = maybeNegative(
      Math.round((0.15 + t * 2.2 + rand() * 2.5) * growthPhase),
      0.18 * negScale,
      rand,
    );

    const reposts = maybeNegative(
      Math.round((0.08 + t * 1.05 + rand() * 1.8) * growthPhase),
      0.16 * negScale,
      rand,
    );

    const posts =
      views > 120 && rand() > 0.42
        ? rand() > 0.78
          ? 2
          : 1
        : rand() > 0.88
          ? 1
          : 0;

    erLevel += randn() * 0.09 + t * 0.011 + (rand() < 0.1 * negScale ? -0.28 : 0);
    erLevel = Math.min(6.5, Math.max(1.6, erLevel));

    days.push({
      date: formatIsoDate(dayDate),
      subscribers,
      reactions,
      views: Math.max(views, 0),
      comments,
      reposts,
      posts,
      er: Math.round(erLevel * 10) / 10,
    });
  }

  const endTotals = { ...startTotals };
  for (const day of days) {
    endTotals.subscribers += day.subscribers;
    endTotals.reactions += day.reactions;
    endTotals.views += day.views;
    endTotals.comments += day.comments;
    endTotals.reposts += day.reposts;
    endTotals.er = day.er;
  }

  return {
    version: 1,
    dayCount: DAY_COUNT,
    startTotals,
    endTotals,
    days,
  };
}

export const channelMetrics110d = generateChannelMetrics110d();

export function parseViewsMetric(views: string | undefined): number {
  if (!views) return 0;
  const normalized = views.replace(/\s/g, "").replace(",", ".");
  const n = Number(normalized);
  return Number.isFinite(n) ? n : 0;
}

export const ANALYTICS_PERIOD_OPTIONS: { value: AnalyticsPeriod; label: string }[] = [
  { value: "24h", label: "24 ч." },
  { value: "7d", label: "7 дн." },
  { value: "30d", label: "30 дн." },
  { value: "90d", label: "90 дн." },
  { value: "all", label: "Всё время" },
];
