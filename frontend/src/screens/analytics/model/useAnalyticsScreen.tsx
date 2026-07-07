"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, type CSSProperties } from "react";

import { useNavigationStore } from "@/app/model/store";
import {
  useChannelAnalyticsHeatmap,
  useChannelAnalyticsReactions,
  useChannelAnalyticsSummary,
  useChannelAnalyticsTopPosts,
  useChannelAnalyticsTrend,
} from "@/entities/analytics";
import { useChannelConnected } from "@/entities/channel";
import { usePosts } from "@/entities/post";
import { buildAnalyticsTopPostsFromPosts } from "@/shared/lib/analytics/buildTopPostsFromPosts";
import {
  analyticsIndexToPeriod,
  analyticsPeriodToIndex,
  ANALYTICS_PERIOD_LABELS,
} from "@/shared/lib/analyticsPeriod";
import { getChannelTopPostsTableMetrics } from "@/shared/lib/channelAnalyticsTrend";
import {
  getChannelMetricsRevision,
  loadChannelMetricsFromApi,
} from "@/shared/lib/channelMetricsDb";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
import { routes } from "@/shared/lib/routes";
import type { AnalyticsPeriod } from "@/shared/data/analytics-seed";
import { usePageHeaderLe780 } from "@/widgets/page-header";

export function useAnalyticsScreen() {
  const router = useRouter();
  const period = useNavigationStore((s) => s.analyticsPeriod);
  const setAnalyticsPeriod = useNavigationStore((s) => s.setAnalyticsPeriod);
  const isMobile = useMobile760();
  const isHeaderLe780 = usePageHeaderLe780();
  const { data: posts = [] } = usePosts();
  const { isConnected: isChannelConnected } = useChannelConnected();
  const useRealAnalytics = !shouldPersistLocally();
  const summaryQuery = useChannelAnalyticsSummary(period, isChannelConnected);
  const trendQuery = useChannelAnalyticsTrend(period, isChannelConnected);
  const heatmapQuery = useChannelAnalyticsHeatmap(period, isChannelConnected);
  const reactionsQuery = useChannelAnalyticsReactions(isChannelConnected);
  const topPostsQuery = useChannelAnalyticsTopPosts(period, isChannelConnected);

  // Загружаем данные в channelMetricsDb синхронно во время рендера, чтобы графики
  // в этом же проходе читали свежие данные (без кадра с seed/пустыми значениями).
  const metricsRevision = useMemo(() => {
    if (summaryQuery.data && trendQuery.data) {
      loadChannelMetricsFromApi({
        version: 2,
        dayCount: trendQuery.data.dayCount,
        granularity: trendQuery.data.granularity,
        subscribersAvailable: summaryQuery.data.subscribersAvailable,
        startTotals: summaryQuery.data.startTotals,
        endTotals: summaryQuery.data.endTotals,
        days: trendQuery.data.days,
      });
    }
    return getChannelMetricsRevision();
  }, [summaryQuery.data, trendQuery.data]);

  const periodIndex = analyticsPeriodToIndex(period);

  const topPostsTableMetrics = useMemo(
    () => getChannelTopPostsTableMetrics(isMobile || isHeaderLe780),
    [isMobile, isHeaderLe780],
  );

  const rankedTopPosts = useMemo(() => {
    if (useRealAnalytics && topPostsQuery.data) {
      return topPostsQuery.data;
    }
    return buildAnalyticsTopPostsFromPosts(posts);
  }, [posts, topPostsQuery.data, useRealAnalytics]);

  const channelReactions = useMemo(() => {
    if (useRealAnalytics && reactionsQuery.data?.reactions?.length) {
      return reactionsQuery.data.reactions;
    }
    return undefined;
  }, [reactionsQuery.data?.reactions, useRealAnalytics]);

  const channelHeatmap = useRealAnalytics ? heatmapQuery.data : undefined;
  const historySource = useRealAnalytics ? trendQuery.data?.historySource : undefined;
  const trackingSince = useRealAnalytics ? trendQuery.data?.trackingSince : undefined;
  const dataAgeSeconds = useRealAnalytics ? summaryQuery.data?.dataAgeSeconds : undefined;
  const isStale = useRealAnalytics ? (summaryQuery.data?.isStale ?? false) : false;

  const topPostsDesktopGridStyle = useMemo(
    () =>
      ({
        gridTemplateColumns: `minmax(11rem, 1fr) repeat(${topPostsTableMetrics.length}, auto) minmax(3.25rem, max-content)`,
      }) as CSSProperties,
    [topPostsTableMetrics.length],
  );

  const topPostsTableWrapStyle = useMemo(
    () =>
      ({
        "--top-posts-metric-cols": topPostsTableMetrics.length,
      }) as CSSProperties,
    [topPostsTableMetrics.length],
  );

  const periodSelectProps = useMemo(
    () => ({
      ariaLabel: "Период аналитики",
      value: period,
      options: ANALYTICS_PERIOD_LABELS.map((label, i) => ({
        value: analyticsIndexToPeriod(i),
        label,
      })),
      onChange: (v: string) => setAnalyticsPeriod(v as AnalyticsPeriod),
    }),
    [period, setAnalyticsPeriod],
  );

  const setPeriodIndex = useCallback(
    (index: number) => {
      setAnalyticsPeriod(analyticsIndexToPeriod(index));
    },
    [setAnalyticsPeriod],
  );

  const openPost = useCallback(
    (postId: string) => {
      router.push(routes.post(postId));
    },
    [router],
  );

  return {
    data: {
      period,
      periodIndex,
      periods: ANALYTICS_PERIOD_LABELS,
      topPostsTableMetrics,
      rankedTopPosts,
      topPostsDesktopGridStyle,
      topPostsTableWrapStyle,
      channelReactions,
      channelHeatmap,
      historySource,
      trackingSince,
      dataAgeSeconds,
      isStale,
      metricsRevision,
      isLoadingAnalytics:
        useRealAnalytics &&
        isChannelConnected &&
        (summaryQuery.isLoading || trendQuery.isLoading || topPostsQuery.isLoading),
    },
    ui: {
      isMobile,
      periodSelectProps,
    },
    actions: {
      setPeriod: setPeriodIndex,
      openPost,
    },
  };
}

export type AnalyticsScreenState = ReturnType<typeof useAnalyticsScreen>;
