import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import type { Post } from "@/shared/types";

/** Post screen uses `posts.detail`; other screens may only have `posts.list`. */
export function getCachedPost(queryClient: QueryClient, postId: string): Post | undefined {
  const accountId = getQueryAccountIdFromAuth();
  const fromList = queryClient
    .getQueryData<Post[]>(queryKeys.posts.list(accountId))
    ?.find((p) => p.id === postId);
  if (fromList) return fromList;
  return queryClient.getQueryData<Post>(queryKeys.posts.detail(accountId, postId));
}

export function setCachedPost(queryClient: QueryClient, post: Post): void {
  const accountId = getQueryAccountIdFromAuth();
  queryClient.setQueryData(queryKeys.posts.detail(accountId, post.id), post);
  const list = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId));
  if (!list) return;
  queryClient.setQueryData(
    queryKeys.posts.list(accountId),
    list.map((p) => (p.id === post.id ? post : p)),
  );
}
