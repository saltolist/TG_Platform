import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";

export async function refreshPostsAfterChannelImport(queryClient: QueryClient): Promise<void> {
  const accountId = getQueryAccountIdFromAuth();
  await queryClient.invalidateQueries({ queryKey: queryKeys.posts.all(accountId) });
}
