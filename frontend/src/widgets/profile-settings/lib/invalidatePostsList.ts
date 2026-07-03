import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";

/** Drop cached post list so the next read refetches from the API. */
export async function invalidatePostsList(queryClient: QueryClient): Promise<void> {
  const accountId = getQueryAccountIdFromAuth();
  await queryClient.invalidateQueries({ queryKey: queryKeys.posts.all(accountId) });
}
