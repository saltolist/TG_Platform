import { describe, expect, it } from "vitest";

import {
  analyticsIndexToPeriod,
  analyticsPeriodToIndex,
} from "@/shared/lib/analyticsPeriod";
import { buildChannelTrendSeries } from "@/shared/lib/channelAnalyticsTrend";

describe("analyticsPeriod", () => {
  it("maps period slug to screen index", () => {
    expect(analyticsPeriodToIndex("24h")).toBe(0);
    expect(analyticsPeriodToIndex("7d")).toBe(1);
    expect(analyticsPeriodToIndex("30d")).toBe(2);
    expect(analyticsPeriodToIndex("90d")).toBe(3);
    expect(analyticsPeriodToIndex("all")).toBe(4);
  });

  it("maps index back to period slug", () => {
    expect(analyticsIndexToPeriod(1)).toBe("7d");
    expect(analyticsIndexToPeriod(99)).toBe("30d");
  });
});

describe("buildChannelTrendSeries", () => {
  it("builds labels and six metric series for 7d", () => {
    const { labels, series } = buildChannelTrendSeries(1);
    expect(labels.length).toBeGreaterThan(0);
    expect(series).toHaveLength(6);
    expect(series.every((row) => row.values.length === labels.length)).toBe(true);
  });
});
