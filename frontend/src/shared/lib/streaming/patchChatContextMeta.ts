import type { QueryClient } from "@tanstack/react-query";
import { z } from "zod";

import {
  chatContextMetaSchema,
  type ChatContextMeta,
} from "@/shared/api/schemas/chatContextMeta";
import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { mutateOverlay } from "@/shared/lib/overlay/overlayStorage";
import { mapMessageAtPath } from "@/shared/lib/chatPaths";
import type { ChatMessage, GlobalChat, LocalChat, Post } from "@/shared/types";

const bundleContextStampSchema = z.object({
  path: z.array(z.number()),
  headGenerationId: z.string(),
  floatingGenerationId: z.string().optional(),
});

export type BundleContextStamp = z.infer<typeof bundleContextStampSchema>;

const streamMetaSchema = chatContextMetaSchema.extend({
  bundle_context_stamp: bundleContextStampSchema.optional(),
});

function applyBundleContextStamp(history: ChatMessage[], stamp: BundleContextStamp): ChatMessage[] {
  const bundleContext = {
    headGenerationId: stamp.headGenerationId,
    ...(stamp.floatingGenerationId ? { floatingGenerationId: stamp.floatingGenerationId } : {}),
  };
  return mapMessageAtPath(history, stamp.path, (message) =>
    message.role === "user" ? { ...message, bundleContext } : message,
  );
}

function splitStreamMeta(meta: Record<string, unknown>): {
  chatMeta: ChatContextMeta;
  stamp?: BundleContextStamp;
} {
  const parsed = streamMetaSchema.parse(meta);
  const { bundle_context_stamp, ...rest } = parsed;
  return {
    chatMeta: chatContextMetaSchema.parse(rest),
    stamp: bundle_context_stamp,
  };
}

function applyChatMetaPatch<T extends GlobalChat | LocalChat>(
  chat: T,
  patch: ChatContextMeta,
  stamp?: BundleContextStamp,
): T {
  const next = { ...chat, ...patch } as T;
  if (!stamp) return next;
  return { ...next, history: applyBundleContextStamp(next.history, stamp) };
}

export function patchGlobalChatContextMeta(
  queryClient: QueryClient,
  chatId: string,
  meta: ChatContextMeta | Record<string, unknown>,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const { chatMeta, stamp } = splitStreamMeta(meta as Record<string, unknown>);
  queryClient.setQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId), (prev) =>
    prev?.map((chat) =>
      chat.id === chatId ? applyChatMetaPatch(chat, chatMeta, stamp) : chat,
    ),
  );

  if (!isOverlayAccount(accountId)) return;

  mutateOverlay((overlay) => {
    const current = overlay.globalChats.upserts[chatId];
    if (!current) return;
    overlay.globalChats.upserts[chatId] = applyChatMetaPatch(current, chatMeta, stamp);
  }, accountId);
}

export function patchPostChatContextMeta(
  queryClient: QueryClient,
  postId: string,
  chatId: string,
  meta: ChatContextMeta | Record<string, unknown>,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const { chatMeta, stamp } = splitStreamMeta(meta as Record<string, unknown>);
  const applyPatch = (post: Post): Post => ({
    ...post,
    chats: post.chats.map((chat) =>
      chat.id === chatId ? applyChatMetaPatch(chat, chatMeta, stamp) : chat,
    ),
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
