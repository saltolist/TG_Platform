import { describe, expect, it } from "vitest";

import { channelAnalyticsTrendSchema } from "./channelAnalytics";

describe("channelAnalyticsTrendSchema", () => {
  it("accepts trend payload with embedded totals", () => {
    const parsed = channelAnalyticsTrendSchema.parse({
      dayCount: 2,
      granularity: "day",
      anchorDate: "2026-07-08",
      startTotals: {
        subscribers: 10,
        reactions: 30,
        views: 100,
        comments: 4,
        reposts: 2,
        er: 3.4,
      },
      endTotals: {
        subscribers: 11,
        reactions: 35,
        views: 120,
        comments: 5,
        reposts: 3,
        er: 3.5,
      },
      subscribersAvailable: true,
      days: [
        {
          date: "2026-07-07",
          views: 10,
          posts: 0,
          subscribers: 0,
          reactions: 2,
          comments: 0,
          reposts: 0,
          er: 3.4,
        },
        {
          date: "2026-07-08",
          views: 10,
          posts: 1,
          subscribers: 1,
          reactions: 3,
          comments: 1,
          reposts: 1,
          er: 3.5,
        },
      ],
      historySource: "channel_snapshots",
      trackingSince: "2026-07-07",
    });

    expect(parsed.endTotals.views - parsed.startTotals.views).toBe(20);
  });
});
