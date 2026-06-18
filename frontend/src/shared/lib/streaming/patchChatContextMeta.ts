import type { QueryClient } from "@tanstack/react-query";

import { chatContextMetaSchema, type ChatContextMeta } from "@/shared/api/schemas/chatContextMeta";
import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { mutateOverlay } from "@/shared/lib/overlay/overlayStorage";
import type { GlobalChat, Post } from "@/shared/types";

function normalizeMeta(meta: ChatContextMeta): ChatContextMeta {
  return chatContextMetaSchema.parse(meta);
}

export function patchGlobalChatContextMeta(
  queryClient: QueryClient,
  chatId: string,
  meta: ChatContextMeta,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const patch = normalizeMeta(meta);
  queryClient.setQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId), (prev) =>
    prev?.map((chat) => (chat.id === chatId ? { ...chat, ...patch } : chat)),
  );

  if (!isOverlayAccount(accountId)) return;

  mutateOverlay((overlay) => {
    const current = overlay.globalChats.upserts[chatId];
    if (!current) return;
    overlay.globalChats.upserts[chatId] = { ...current, ...patch };
  }, accountId);
}

export function patchPostChatContextMeta(
  queryClient: QueryClient,
  postId: string,
  chatId: string,
  meta: ChatContextMeta,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const patch = normalizeMeta(meta);
  const applyPatch = (post: Post): Post => ({
    ...post,
    chats: post.chats.map((chat) => (chat.id === chatId ? { ...chat, ...patch } : chat)),
  });

  queryClient.setQueryData<Post>(queryKeys.posts.detail(accountId, postId), (prev) =>
    prev ? applyPatch(prev) : prev,
  );

  const list = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId));
  if (list) {
    queryClient.setQueryData(
      queryKeys.posts.list(accountId),
      list.map((post) => (post.id === postId ? applyPatch(post) : post)),
    );
  }

  if (!isOverlayAccount(accountId)) return;

  mutateOverlay((overlay) => {
    const current = overlay.posts.upserts[postId];
    if (!current) return;
    overlay.posts.upserts[postId] = applyPatch(current);
  }, accountId);
}
