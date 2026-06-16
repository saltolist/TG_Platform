import { describe, expect, it } from "vitest";

import { groupOverlappingTrendDots, trendDotKey } from "@/shared/lib/trendChart/dotClustering";

describe("trendChart/dotClustering", () => {
  it("trendDotKey combines series and label", () => {
    expect(trendDotKey({ seriesId: "views", label: "01.01" })).toBe("views:01.01");
  });

  it("groupOverlappingTrendDots merges nearby dots", () => {
    const dots = [
      {
        seriesId: "a",
        seriesLabel: "A",
        color: "#fff",
        x: 50,
        y: 50,
        value: 1,
        label: "d1",
        pointIndex: 0,
        periodLabel: "p1",
        extraLines: [],
      },
      {
        seriesId: "b",
        seriesLabel: "B",
        color: "#000",
        x: 50.1,
        y: 50.1,
        value: 2,
        label: "d2",
        pointIndex: 0,
        periodLabel: "p1",
        extraLines: [],
      },
    ];

    const clusters = groupOverlappingTrendDots(dots, 720, 493);
    expect(clusters).toHaveLength(1);
    expect(clusters[0]!.dots).toHaveLength(2);
  });
});
