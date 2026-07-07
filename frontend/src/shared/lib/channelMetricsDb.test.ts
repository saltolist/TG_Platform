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
  });

  it("maps latest UTC calendar day to local today on week charts", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-07T21:30:00.000Z"));

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
          views: 0,
          comments: 0,
          reposts: 0,
          posts: 0,
          er: 0,
        },
      ],
    });

    const series = extractChannelMetricSeriesForChart("subscribers", 1, 7);
    expect(series.values[6]).toBe(4);

    vi.useRealTimers();
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
