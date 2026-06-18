import type { QueryClient } from "@tanstack/react-query";

import { getCachedPost } from "@/entities/post/lib/getCachedPost";

/** Return chatId only if it still exists in the post's local chats. */
export function resolvePostChatId(
  queryClient: QueryClient,
  postId: string,
  chatId: string | null | undefined,
): string | null {
  if (!chatId) return null;
  const post = getCachedPost(queryClient, postId);
  if (!post?.chats.some((chat) => chat.id === chatId)) return null;
  return chatId;
}
