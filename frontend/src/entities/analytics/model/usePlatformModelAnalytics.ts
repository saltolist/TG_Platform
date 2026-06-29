"use client";

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";

export function usePlatformModelAnalytics(period: number, points: number) {
  const { analytics } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.analytics.platformModels(accountId, period, points),
    queryFn: () => analytics.getPlatformModels(period, points),
    enabled,
    placeholderData: (previous) => previous,
  });
}
