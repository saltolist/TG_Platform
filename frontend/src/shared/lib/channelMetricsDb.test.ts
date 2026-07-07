import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildChannelChartLabels,
  extractChannelMetricSeriesForChart,
  formatChannelTrendPointPeriod,
  getChannelEndTotals,
  isChannel30mGranularity,
  isChannelSubscribersAvailable,
  loadChannelMetricsFromApi,
} from "@/shared/lib/channelMetricsDb";
import type { ChannelDayMetrics, ChannelMetricsDataset } from "@/shared/data/analytics-seed";

type TestDataset = Omit<Partial<ChannelMetricsDataset>, "days" | "startTotals" | "endTotals"> & {
  days: ChannelDayMetrics[];
  startTotals?: Partial<ChannelMetricsDataset["startTotals"]>;
  endTotals?: Partial<ChannelMetricsDataset["endTotals"]>;
  granularity?: "day" | "30m";
  subscribersAvailable?: boolean;
};

function loadDataset(partial: TestDataset) {
  loadChannelMetricsFromApi({
    version: 2,
    dayCount: partial.days.length,
    startTotals: {
      subscribers: 0,
      reactions: 0,
      views: 0,
      comments: 0,
      reposts: 0,
      er: 0,
      ...partial.startTotals,
    },
    endTotals: {
      subscribers: 0,
      reactions: 0,
      views: 0,
      comments: 0,
      reposts: 0,
      er: 0,
      ...partial.endTotals,
    },
    days: partial.days,
    granularity: partial.granularity,
    subscribersAvailable: partial.subscribersAvailable,
  });
}

afterEach(() => {
  loadDataset({
    days: [
      {
        date: "2026-07-01",
        subscribers: 0,
        reactions: 0,
        views: 0,
        comments: 0,
        reposts: 0,
        posts: 0,
        er: 0,
      },
    ],
  });
});

describe("channelMetricsDb", () => {
  it("uses a fixed 7-day axis for the week chart", () => {
    loadDataset({
      days: [
        {
          date: "2026-06-01",
          subscribers: 1,
          reactions: 2,
          views: 10,
          comments: 0,
          reposts: 0,
          posts: 1,
          er: 1,
        },
        {
          date: "2026-06-02",
          subscribers: 1,
          reactions: 3,
          views: 20,
          comments: 0,
          reposts: 0,
          posts: 1,
          er: 1.2,
        },
      ],
    });

    expect(buildChannelChartLabels(1)).toHaveLength(7);
    expect(buildChannelChartLabels(2)).toHaveLength(30);
  });

  it("aggregates 30-minute snapshots into 24 hourly bars for 24h charts", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-04T15:00:00.000Z"));

    loadDataset({
      granularity: "30m",
      startTotals: { views: 90, subscribers: 48 },
      endTotals: { views: 150, subscribers: 52 },
      days: [
        {
          date: "2026-07-04T10:00:00+00:00",
          subscribers: 2,
          reactions: 1,
          views: 10,
          comments: 0,
          reposts: 0,
          posts: 0,
          er: 2.1,
        },
        {
          date: "2026-07-04T10:30:00+00:00",
          subscribers: 1,
          reactions: 2,
          views: 30,
          comments: 1,
          reposts: 0,
          posts: 1,
          er: 2.3,
        },
        {
          date: "2026-07-04T11:00:00+00:00",
          subscribers: 1,
          reactions: 3,
          views: 20,
          comments: 0,
          reposts: 1,
          posts: 0,
          er: 2.5,
        },
      ],
    });

    expect(isChannel30mGranularity()).toBe(true);
    expect(buildChannelChartLabels(0)).toHaveLength(24);
    const viewsSeries = extractChannelMetricSeriesForChart("views", 0, 24);
    expect(viewsSeries.values).toHaveLength(24);
    expect(viewsSeries.values.reduce((sum, value) => sum + value, 0)).toBe(60);
    expect(viewsSeries.priorCumulative).toBe(90);
    expect(formatChannelTrendPointPeriod(0, 1, 24)).toMatch(/—/);

    vi.useRealTimers();
  });

  it("anchors the newest snapshot to the rightmost column and spaces earlier rows by real date", () => {
    loadDataset({
      days: [
        {
          date: "2026-07-01",
          subscribers: 1,
          reactions: 0,
          views: 0,
          comments: 0,
          reposts: 0,
          posts: 0,
          er: 0,
        },
        {
          date: "2026-07-07",
          subscribers: 4,
          reactions: 0,
          views: 35,
          comments: 0,
          reposts: 0,
          posts: 0,
          er: 0,
        },
      ],
    });

    const subscribers = extractChannelMetricSeriesForChart("subscribers", 1, 7);
    const views = extractChannelMetricSeriesForChart("views", 1, 7);
    // Newest row (07-07) is 0 days from newest → rightmost column (index 6).
    expect(subscribers.values[6]).toBe(4);
    expect(views.values[6]).toBe(35);
    // 07-01 is 6 days before 07-07 → column index 0.
    expect(subscribers.values[0]).toBe(1);
    // Every other column is empty (no snapshot on that day).
    expect(views.values[0]).toBe(0);
    expect(subscribers.values[3]).toBe(0);
  });

  it("does not dump day-level subscriber deltas into the last 24h hour", () => {
    loadDataset({
      days: [
        {
          date: "2026-07-05",
          subscribers: 1,
          reactions: 0,
          views: 0,
          comments: 0,
          reposts: 0,
          posts: 0,
          er: 0,
        },
      ],
    });

    const subscribers = extractChannelMetricSeriesForChart("subscribers", 0, 24);
    expect(subscribers.values.every((value) => value === 0)).toBe(true);
  });

  it("zeros 24h subscriber bars when period growth from totals is zero", () => {
    loadDataset({
      granularity: "30m",
      startTotals: { subscribers: 51, views: 0, reactions: 0, comments: 0, reposts: 0, er: 0 },
      endTotals: { subscribers: 51, views: 100, reactions: 0, comments: 0, reposts: 0, er: 0 },
      days: [
        {
          date: "2026-07-08T01:00:00+00:00",
          subscribers: 1,
          reactions: 0,
          views: 10,
          comments: 0,
          reposts: 0,
          posts: 0,
          er: 0,
        },
      ],
    });

    const subscribers = extractChannelMetricSeriesForChart("subscribers", 0, 24);
    expect(subscribers.values.every((value) => value === 0)).toBe(true);
  });

  it("tracks hidden subscriber counts from API metadata", () => {
    loadDataset({
      subscribersAvailable: false,
      endTotals: { subscribers: 0, views: 100 },
      days: [
        {
          date: "2026-07-04",
          subscribers: 0,
          reactions: 0,
          views: 100,
          comments: 0,
          reposts: 0,
          posts: 1,
          er: 0,
        },
      ],
    });

    expect(isChannelSubscribersAvailable()).toBe(false);
    expect(getChannelEndTotals().subscribers).toBe(0);
  });
});
