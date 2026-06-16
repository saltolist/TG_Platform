import {
  ANALYTICS_PERIOD_OPTIONS,
  type AnalyticsPeriod,
} from "@/shared/data/analytics-seed";

const PERIOD_ORDER: AnalyticsPeriod[] = ["24h", "7d", "30d", "90d", "all"];

export function analyticsPeriodToIndex(period: AnalyticsPeriod): number {
  const index = PERIOD_ORDER.indexOf(period);
  return index >= 0 ? index : 2;
}

export function analyticsIndexToPeriod(index: number): AnalyticsPeriod {
  return PERIOD_ORDER[index] ?? "30d";
}

export const ANALYTICS_PERIOD_LABELS = ANALYTICS_PERIOD_OPTIONS.map((item) => item.label);
