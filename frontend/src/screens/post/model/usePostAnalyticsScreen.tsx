"use client";

import { useMemo, useState } from "react";

import { usePostAnalyticsTrend } from "@/entities/analytics";
import {
  analyticsIndexToPeriod,
  analyticsPeriodToIndex,
  ANALYTICS_PERIOD_LABELS,
} from "@/shared/lib/analyticsPeriod";
import { buildPostTrendSeries } from "@/shared/lib/postAnalyticsTrend";
import {
  getChannelMetricsRevision,
  loadChannelMetricsFromApi,
} from "@/shared/lib/channelMetricsDb";
import type { AnalyticsPeriod } from "@/shared/data/analytics-seed";

export function usePostAnalyticsScreen(postId: string, enabled: boolean) {
  const [period, setPeriod] = useState<AnalyticsPeriod>("30d");
  const trendQuery = usePostAnalyticsTrend(postId, period, enabled);

  const metricsRevision = useMemo(() => {
    if (trendQuery.data) {
      loadChannelMetricsFromApi({
        version: 2,
        dayCount: trendQuery.data.dayCount,
        granularity: trendQuery.data.granularity,
        subscribersAvailable: false,
        startTotals: {
          ...trendQuery.data.startTotals,
          subscribers: 0,
        },
        endTotals: {
          ...trendQuery.data.endTotals,
          subscribers: 0,
        },
        days: trendQuery.data.days,
      });
    }
    return getChannelMetricsRevision();
  }, [trendQuery.data]);

  const periodIndex = analyticsPeriodToIndex(period);
  const { labels, series } = useMemo(
    () => buildPostTrendSeries(periodIndex),
    [periodIndex, metricsRevision],
  );

  const setPeriodIndex = (next: number) => {
    setPeriod(analyticsIndexToPeriod(next));
  };

  return {
    periodIndex,
    periods: ANALYTICS_PERIOD_LABELS,
    onPeriodChange: setPeriodIndex,
    labels,
    series,
    historySource: trendQuery.data?.historySource,
    trackingSince: trendQuery.data?.trackingSince,
    isStale: trendQuery.data?.isStale,
    dataAgeSeconds: trendQuery.data?.dataAgeSeconds,
    isLoading: trendQuery.isLoading,
    isError: trendQuery.isError,
  };
}
