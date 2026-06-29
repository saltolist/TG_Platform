import type { QueryClient } from "@tanstack/react-query";

import { getCachedPost } from "@/entities/post/lib/getCachedPost";
import type { Post } from "@/shared/types";

/** Return chatId only if it still exists in the post's local chats. */
export function resolvePostChatId(
  queryClient: QueryClient,
  postId: string,
  chatId: string | null | undefined,
): string | null {
  if (!chatId) return null;
  const post = getCachedPost(queryClient, postId);
  // If the post isn't cached yet (or cached under another scope), we can't reliably validate.
  // In that case keep the id from URL so composer can still target the intended chat.
  if (!post) return chatId;
  if (!post.chats.some((chat) => chat.id === chatId)) return null;
  return chatId;
}

/** Active chat for post workspace UI — only when ``?chat=`` points at an existing local chat. */
export function activePostChatIdFromPost(
  chatFromUrl: string | null,
  post: Post | null | undefined,
): string | null {
  if (!chatFromUrl || !post) return null;
  return post.chats.some((chat) => chat.id === chatFromUrl) ? chatFromUrl : null;
}

/** Hide active chat while user is on post root / «новый чат» intent. */
export function displayPostChatId(params: {
  chatFromUrl: string | null;
  post: Post | null | undefined;
  pendingNew: boolean;
}): string | null {
  if (params.pendingNew) return null;
  return activePostChatIdFromPost(params.chatFromUrl, params.post);
}

/**
 * Target chat for composer on post screen.
 * Post root without ``?chat=`` always means "new chat on send", not the last store id.
 */
export function composerPostChatId(params: {
  postId: string | null;
  chatFromUrl: string | null;
  pendingNew: boolean;
  queryClient: QueryClient;
}): string | null {
  const { postId, chatFromUrl, pendingNew, queryClient } = params;
  if (!postId || pendingNew || !chatFromUrl) return null;
  return resolvePostChatId(queryClient, postId, chatFromUrl);
}
