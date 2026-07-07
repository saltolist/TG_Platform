import { describe, expect, it } from "vitest";

import { formatChannelPointPercentGrowth } from "@/shared/lib/channelAnalyticsTrend";

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
