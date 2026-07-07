import { describe, expect, it } from "vitest";

import {
  buildChannelMetricGrowthBars,
  buildChannelTrendPlotYValues,
  formatChannelPointPercentGrowth,
  formatChannelTrackingSinceLabel,
} from "@/shared/lib/channelAnalyticsTrend";

describe("buildChannelTrendPlotYValues", () => {
  it("returns cumulative totals for count metrics", () => {
    const yValues = buildChannelTrendPlotYValues("reactions", [2, 1, 3], 100);

    expect(yValues).toEqual([102, 103, 106]);
  });

  it("returns ER level for er metric", () => {
    const yValues = buildChannelTrendPlotYValues("er", [48, 52, 55], 450);

    expect(yValues).toEqual([4.8, 5.2, 5.5]);
  });

  it("includes prior cumulative in count metric baseline", () => {
    const yValues = buildChannelTrendPlotYValues("views", [10, 5], 1000);

    expect(yValues).toEqual([1010, 1015]);
  });
});

describe("buildChannelMetricGrowthBars", () => {
  it("returns per-slot deltas verbatim for count metrics", () => {
    const bars = buildChannelMetricGrowthBars("reactions", [2, 1, 3], 100);

    expect(bars).toEqual([2, 1, 3]);
  });

  it("returns level-to-level deltas for er metric", () => {
    const bars = buildChannelMetricGrowthBars("er", [48, 52, 50], 450);

    // levels: 4.8, 5.2, 5.0; prior level 4.5
    expect(bars[0]).toBeCloseTo(0.3, 5);
    expect(bars[1]).toBeCloseTo(0.4, 5);
    expect(bars[2]).toBeCloseTo(-0.2, 5);
  });

  it("keeps negative count deltas (drops)", () => {
    const bars = buildChannelMetricGrowthBars("subscribers", [5, -3, 0], 200);

    expect(bars).toEqual([5, -3, 0]);
  });
});

describe("formatChannelPointPercentGrowth", () => {
  it("shows non-zero percent when growth starts from zero", () => {
    const percent = formatChannelPointPercentGrowth(
      "reactions",
      2,
      [0, 0, 2],
      0,
    );

    expect(percent).toBe("+100.0%");
  });

  it("uses period start as baseline when prior cumulative is non-zero", () => {
    const percent = formatChannelPointPercentGrowth(
      "reactions",
      1,
      [1, 1],
      100,
    );

    expect(percent).toBe("+2.0%");
  });

  it("returns zero percent when there is no growth", () => {
    const percent = formatChannelPointPercentGrowth(
      "reactions",
      0,
      [0, 0],
      0,
    );

    expect(percent).toBe("+0.0%");
  });
});

describe("formatChannelTrackingSinceLabel", () => {
  it("formats ISO date in Russian", () => {
    expect(formatChannelTrackingSinceLabel("2026-03-15")).toBe("15 марта 2026");
  });

  it("returns null for invalid date", () => {
    expect(formatChannelTrackingSinceLabel("not-a-date")).toBeNull();
  });
});
