"use client";

import { useQuery } from "@tanstack/react-query";

import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { queryKeys } from "@/shared/api/queryKeys";
import type { AnalyticsPeriod } from "@/shared/data/analytics-seed";

export function usePostAnalyticsTrend(postId: string, period: AnalyticsPeriod, enabled = true) {
  const { analytics } = useRepositories();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();

  return useQuery({
    queryKey: queryKeys.analytics.postTrend(accountId, postId, period),
    queryFn: () => analytics.getPostTrend(postId, period),
    enabled: authEnabled && enabled && Boolean(postId),
  });
}
