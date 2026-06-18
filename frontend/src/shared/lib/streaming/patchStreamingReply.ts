import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { mutateOverlay } from "@/shared/lib/overlay/overlayStorage";
import { updateLastVisibleAiMessage } from "@/shared/lib/chatPaths";
import type { ChatMessage, GlobalChat, Post } from "@/shared/types";

function applyStreamingAiText(message: ChatMessage, text: string): ChatMessage {
  if (message.mode === "multi" && message.variants?.length) {
    return {
      ...message,
      variants: message.variants.map((variant) => ({ ...variant, text })),
    };
  }
  return { ...message, text };
}

function applyAccumulatedAiText(history: ChatMessage[], accumulated: string): ChatMessage[] {
  return updateLastVisibleAiMessage(history, (message) =>
    applyStreamingAiText(message, accumulated),
  );
}

export function patchGlobalChatStreamingText(
  queryClient: QueryClient,
  chatId: string,
  accumulated: string,
  accountId = getQueryAccountIdFromAuth(),
): void {
  queryClient.setQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId), (prev) =>
    prev?.map((chat) =>
      chat.id === chatId
        ? { ...chat, history: applyAccumulatedAiText(chat.history, accumulated) }
        : chat,
    ),
  );

  if (!isOverlayAccount(accountId)) return;

  mutateOverlay((overlay) => {
    const current = overlay.globalChats.upserts[chatId];
    if (!current) return;
    overlay.globalChats.upserts[chatId] = {
      ...current,
      history: applyAccumulatedAiText(current.history, accumulated),
    };
  }, accountId);
}

export function patchPostChatStreamingText(
  queryClient: QueryClient,
  postId: string,
  chatId: string,
  accumulated: string,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const patchPost = (post: Post): Post => ({
    ...post,
    chats: post.chats.map((chat) =>
      chat.id === chatId
        ? { ...chat, history: applyAccumulatedAiText(chat.history, accumulated) }
        : chat,
    ),
  });

  queryClient.setQueryData<Post>(queryKeys.posts.detail(accountId, postId), (prev) =>
    prev ? patchPost(prev) : prev,
  );

  const list = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId));
  if (list) {
    queryClient.setQueryData(
      queryKeys.posts.list(accountId),
      list.map((post) => (post.id === postId ? patchPost(post) : post)),
    );
  }

  if (!isOverlayAccount(accountId)) return;

  mutateOverlay((overlay) => {
    const current = overlay.posts.upserts[postId];
    if (!current) return;
    overlay.posts.upserts[postId] = patchPost(current);
  }, accountId);
}
