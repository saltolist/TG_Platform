import { describe, expect, it } from "vitest";

import {
  buildAdaptiveValueScale,
  buildSmoothPath,
  formatTrendNumber,
  getClusterStripColumnCount,
  sanitizeSvgId,
  valueToChartY,
} from "@/shared/lib/trendChart/math";

describe("trendChart/math", () => {
  it("buildAdaptiveValueScale produces positive span", () => {
    const scale = buildAdaptiveValueScale([100, 200, 150]);
    expect(scale.span).toBeGreaterThan(0);
    expect(scale.max).toBeGreaterThan(scale.min);
  });

  it("valueToChartY maps max to top of plot", () => {
    const scale = { min: 0, max: 100, span: 100 };
    expect(valueToChartY(100, scale, 88, 87)).toBeCloseTo(1, 0);
    expect(valueToChartY(0, scale, 88, 87)).toBeCloseTo(88, 0);
  });

  it("buildSmoothPath returns empty for no points", () => {
    expect(buildSmoothPath([])).toBe("");
  });

  it("buildSmoothPath handles single point", () => {
    expect(buildSmoothPath([{ x: 10, y: 20 }])).toBe("M 10.0 20.0");
  });

  it("formatTrendNumber compacts large values", () => {
    expect(formatTrendNumber(1_500_000, 2_000_000)).toMatch(/1/);
  });

  it("sanitizeSvgId strips unsafe characters", () => {
    expect(sanitizeSvgId("views/ai")).toBe("views_ai");
  });

  it("getClusterStripColumnCount caps columns", () => {
    expect(getClusterStripColumnCount(8, 5)).toBe(5);
    expect(getClusterStripColumnCount(2, 5)).toBe(2);
  });
});
