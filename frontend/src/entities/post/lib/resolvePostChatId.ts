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
  // If the post isn't cached yet (or cached under another scope), we can't reliably validate.
  // In that case keep the id from URL/store so composer can still target the intended chat.
  if (!post) return chatId;
  if (!post.chats.some((chat) => chat.id === chatId)) return null;
  return chatId;
}
