"use client";

import { useQuery } from "@tanstack/react-query";

import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { queryKeys } from "@/shared/api/queryKeys";
import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
import type { AnalyticsPeriod } from "@/shared/data/analytics-seed";

export function useChannelAnalyticsSummary(period: AnalyticsPeriod, enabled = true) {
  const { analytics } = useRepositories();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();
  const useApi = !shouldPersistLocally();

  return useQuery({
    queryKey: queryKeys.analytics.channelSummary(accountId, period),
    queryFn: () => analytics.getChannelSummary(period),
    enabled: authEnabled && useApi && enabled,
  });
}

export function useChannelAnalyticsTrend(period: AnalyticsPeriod, enabled = true) {
  const { analytics } = useRepositories();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();
  const useApi = !shouldPersistLocally();

  return useQuery({
    queryKey: queryKeys.analytics.channelTrend(accountId, period),
    queryFn: () => analytics.getChannelTrend(period),
    enabled: authEnabled && useApi && enabled,
  });
}

export function useChannelAnalyticsHeatmap(period: AnalyticsPeriod, enabled = true) {
  const { analytics } = useRepositories();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();
  const useApi = !shouldPersistLocally();

  return useQuery({
    queryKey: queryKeys.analytics.channelHeatmap(accountId, period),
    queryFn: () => analytics.getChannelHeatmap(period),
    enabled: authEnabled && useApi && enabled,
  });
}

export function useChannelAnalyticsReactions(enabled = true) {
  const { analytics } = useRepositories();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();
  const useApi = !shouldPersistLocally();

  return useQuery({
    queryKey: queryKeys.analytics.channelReactions(accountId),
    queryFn: () => analytics.getChannelReactions(),
    enabled: authEnabled && useApi && enabled,
  });
}

export function useChannelAnalyticsTopPosts(period: AnalyticsPeriod, enabled = true) {
  const { analytics } = useRepositories();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();
  const useApi = !shouldPersistLocally();

  return useQuery({
    queryKey: queryKeys.analytics.channelTopPosts(accountId, period),
    queryFn: () => analytics.getChannelTopPosts(period),
    enabled: authEnabled && useApi && enabled,
  });
}
