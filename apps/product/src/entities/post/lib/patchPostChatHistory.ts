import type { QueryClient } from "@tanstack/react-query";

import { setCachedPost } from "@/entities/post/lib/getCachedPost";
import { queryKeys } from "@/shared/api/queryKeys";
import type { PostsRepository } from "@/shared/api/repositories";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { lastUserPreviewFromVisibleHistory, normalizeBranchedHistory } from "@/shared/lib/chatPaths";
import type { ChatMessage, LocalChat, Post } from "@/shared/types";

function chatPreviewFromHistory(history: ChatMessage[]): string {
  return lastUserPreviewFromVisibleHistory(history).slice(0, 80);
}

function patchLocalChatInList(
  chats: LocalChat[],
  chatId: string,
  updater: (history: ChatMessage[]) => ChatMessage[],
): LocalChat[] {
  return chats.map((chat) => {
    if (chat.id !== chatId) return chat;
    const history = updater(normalizeBranchedHistory(chat.history));
    return {
      ...chat,
      history,
      preview: chatPreviewFromHistory(history),
      date: new Date().toISOString(),
    };
  });
}

/** Актуальный пост с бэкенда. */
export async function fetchPost(
  queryClient: QueryClient,
  posts: PostsRepository,
  postId: string,
): Promise<Post> {
  const accountId = getQueryAccountIdFromAuth();
  return queryClient.fetchQuery({
    queryKey: queryKeys.posts.detail(accountId, postId),
    queryFn: async () => {
      const list = await posts.list();
      const post = list.find((p) => p.id === postId);
      if (!post) throw new Error(`Post ${postId} not found`);
      return post;
    },
  });
}

export type PatchPostChatHistoryOptions = {
  preview?: string;
};

/** Read-modify-write для `chats[].history` локального чата поста. */
export async function patchPostChatHistory(
  queryClient: QueryClient,
  posts: PostsRepository,
  postId: string,
  chatId: string,
  updater: (history: ChatMessage[]) => ChatMessage[],
  options?: PatchPostChatHistoryOptions,
): Promise<Post> {
  const post = await fetchPost(queryClient, posts, postId);
  let chats = patchLocalChatInList(post.chats, chatId, updater);
  if (options?.preview) {
    chats = chats.map((c) =>
      c.id === chatId ? { ...c, preview: options.preview!.slice(0, 80) } : c,
    );
  }
  const updated = await posts.update(postId, { chats });
  setCachedPost(queryClient, updated);
  return updated;
}
