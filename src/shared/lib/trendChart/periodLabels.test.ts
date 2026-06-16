import { describe, expect, it } from "vitest";

import {
  getFullPeriodPointCount,
  getPeriodChartLabels,
  getTrendPointXPercent,
  resolveTrendChartMaxPoints,
} from "@/shared/lib/trendChart/periodLabels";

describe("trendChart/periodLabels", () => {
  it("getFullPeriodPointCount for known periods", () => {
    expect(getFullPeriodPointCount(0)).toBe(24);
    expect(getFullPeriodPointCount(1)).toBe(7);
    expect(getFullPeriodPointCount(2)).toBe(30);
    expect(getFullPeriodPointCount(4)).toBe(6);
  });

  it("getPeriodChartLabels returns stable lengths", () => {
    expect(getPeriodChartLabels(1)).toHaveLength(7);
    expect(getPeriodChartLabels(2, { maxPoints: 10 })).toHaveLength(10);
  });

  it("resolveTrendChartMaxPoints respects breakpoints", () => {
    expect(resolveTrendChartMaxPoints({ isMobile: true, isHeaderLe1080: false, isHeaderLe640: false })).toBe(8);
    expect(
      resolveTrendChartMaxPoints({ isMobile: false, isHeaderLe1080: true, isHeaderLe640: false }),
    ).toBe(15);
    expect(
      resolveTrendChartMaxPoints({ isMobile: false, isHeaderLe1080: false, isHeaderLe640: true }),
    ).toBe(10);
    expect(
      resolveTrendChartMaxPoints({ isMobile: false, isHeaderLe1080: false, isHeaderLe640: false }),
    ).toBeUndefined();
  });

  it("getTrendPointXPercent insets edge points", () => {
    expect(getTrendPointXPercent(0, 5, 10)).toBe(10);
    expect(getTrendPointXPercent(4, 5, 10)).toBe(90);
  });
});
