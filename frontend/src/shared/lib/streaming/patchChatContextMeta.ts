import type { QueryClient } from "@tanstack/react-query";
import { z } from "zod";

import {
  chatContextMetaSchema,
  type ChatContextMeta,
} from "@/shared/api/schemas/chatContextMeta";
import { messageContextLabelSchema } from "@/shared/api/schemas/post";
import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { mutateOverlay } from "@/shared/lib/overlay/overlayStorage";
import { mapMessageAtPath, clampActiveBranchIndex, updateLastVisibleAiMessage } from "@/shared/lib/chatPaths";
import type { ChatMessage, GlobalChat, LocalChat, Post } from "@/shared/types";

const bundleContextStampSchema = z.object({
  path: z.array(z.number()),
  headGenerationId: z.string(),
  floatingGenerationId: z.string().optional(),
});

const globalContextLabelStampSchema = z.object({
  path: z.array(z.number()),
  head: z.number(),
  attached: z.number(),
  turn: z.string(),
});

const postContextLabelStampSchema = z.object({
  path: z.array(z.number()),
  scope: z.literal("post"),
  head_global: z.number(),
  head_local: z.number(),
  attached_global: z.number(),
  attached_local: z.number(),
  turn: z.string(),
});

const contextLabelStampSchema = z.union([
  postContextLabelStampSchema,
  globalContextLabelStampSchema,
]);

export type BundleContextStamp = z.infer<typeof bundleContextStampSchema>;
export type ContextLabelStamp = z.infer<typeof contextLabelStampSchema>;

function formatContextLabelStamp(stamp: ContextLabelStamp): string {
  if ("head" in stamp) {
    return `${stamp.head}-${stamp.attached}-${stamp.turn}`;
  }
  return `${stamp.head_global}.${stamp.head_local}-${stamp.attached_global}.${stamp.attached_local}-${stamp.turn}`;
}

function applyContextLabelStamp(history: ChatMessage[], stamp: ContextLabelStamp): ChatMessage[] {
  const contextLabel = formatContextLabelStamp(stamp);
  messageContextLabelSchema.parse(contextLabel);
  return mapMessageAtPath(history, stamp.path, (message) => {
    if (message.role !== "user") return message;
    const branches = message.userBranches;
    if (branches && branches.length > 1) {
      const bi = clampActiveBranchIndex(message);
      const existing = branches[bi]?.contextLabel ?? (bi === 0 ? message.contextLabel : undefined);
      if (existing === contextLabel) return message;
      if (existing) return message;
      const { contextLabel: _parentLabel, ...rest } = message;
      return {
        ...rest,
        userBranches: branches.map((branch, index) =>
          index === bi ? { ...branch, contextLabel } : branch,
        ),
      };
    }
    if (message.contextLabel === contextLabel) return message;
    if (message.contextLabel) return message;
    return { ...message, contextLabel };
  });
}

function applyBundleContextStamp(history: ChatMessage[], stamp: BundleContextStamp): ChatMessage[] {
  const bundleContext = {
    headGenerationId: stamp.headGenerationId,
    ...(stamp.floatingGenerationId ? { floatingGenerationId: stamp.floatingGenerationId } : {}),
  };
  return mapMessageAtPath(history, stamp.path, (message) =>
    message.role === "user" ? { ...message, bundleContext } : message,
  );
}

const streamMetaSchema = chatContextMetaSchema.extend({
  bundle_context_stamp: bundleContextStampSchema.optional(),
  context_label_stamp: contextLabelStampSchema.optional(),
  assistant_text: z.string().optional(),
});

function splitStreamMeta(meta: Record<string, unknown>): {
  chatMeta: ChatContextMeta;
  bundleStamp?: BundleContextStamp;
  labelStamp?: ContextLabelStamp;
  assistantText?: string;
} {
  const parsed = streamMetaSchema.parse(meta);
  const { bundle_context_stamp, context_label_stamp, assistant_text, ...rest } = parsed;
  return {
    chatMeta: chatContextMetaSchema.parse(rest),
    bundleStamp: bundle_context_stamp,
    labelStamp: context_label_stamp,
    assistantText: assistant_text,
  };
}

function applyAssistantTextStamp(history: ChatMessage[], text: string): ChatMessage[] {
  return updateLastVisibleAiMessage(history, (message) => {
    if (message.role !== "ai") return message;
    if (Array.isArray(message.variants) && message.variants.length > 0) {
      const idx = Math.min(
        Math.max(Number(message.selectedVariant) || 0, 0),
        message.variants.length - 1,
      );
      const variants = message.variants.map((variant, variantIdx) =>
        variantIdx === idx ? { ...variant, text } : variant,
      );
      return { ...message, variants };
    }
    return { ...message, text };
  });
}

function applyChatMetaPatch<T extends GlobalChat | LocalChat>(
  chat: T,
  patch: ChatContextMeta,
  bundleStamp?: BundleContextStamp,
  labelStamp?: ContextLabelStamp,
  assistantText?: string,
): T {
  let next = { ...chat, ...patch } as T;
  if (labelStamp) {
    next = { ...next, history: applyContextLabelStamp(next.history, labelStamp) };
  }
  if (bundleStamp) {
    next = { ...next, history: applyBundleContextStamp(next.history, bundleStamp) };
  }
  if (assistantText) {
    next = { ...next, history: applyAssistantTextStamp(next.history, assistantText) };
  }
  return next;
}

export function patchGlobalChatContextMeta(
  queryClient: QueryClient,
  chatId: string,
  meta: ChatContextMeta | Record<string, unknown>,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const { chatMeta, bundleStamp, labelStamp, assistantText } = splitStreamMeta(meta as Record<string, unknown>);
  queryClient.setQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId), (prev) =>
    prev?.map((chat) =>
      chat.id === chatId
        ? applyChatMetaPatch(chat, chatMeta, bundleStamp, labelStamp, assistantText)
        : chat,
    ),
  );

  if (!isOverlayAccount(accountId)) return;

  mutateOverlay((overlay) => {
    const current = overlay.globalChats.upserts[chatId];
    if (!current) return;
    overlay.globalChats.upserts[chatId] = applyChatMetaPatch(
      current,
      chatMeta,
      bundleStamp,
      labelStamp,
      assistantText,
    );
  }, accountId);
}

export function patchPostChatContextMeta(
  queryClient: QueryClient,
  postId: string,
  chatId: string,
  meta: ChatContextMeta | Record<string, unknown>,
  accountId = getQueryAccountIdFromAuth(),
): void {
  const { chatMeta, bundleStamp, labelStamp, assistantText } = splitStreamMeta(meta as Record<string, unknown>);
  const applyPatch = (post: Post): Post => ({
    ...post,
    chats: post.chats.map((chat) =>
      chat.id === chatId
        ? applyChatMetaPatch(chat, chatMeta, bundleStamp, labelStamp, assistantText)
        : chat,
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
