import type { QueryClient } from "@tanstack/react-query";
import { z } from "zod";

import {
  chatContextMetaSchema,
  type ChatContextMeta,
} from "@/shared/api/schemas/chatContextMeta";
import { contextStampSchema, messageContextLabelSchema } from "@/shared/api/schemas/post";
import { queryKeys } from "@/shared/api/queryKeys";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { mutateOverlay } from "@/shared/lib/overlay/overlayStorage";
import { mapMessageAtPath, clampActiveBranchIndex, updateLastVisibleAiMessage } from "@/shared/lib/chatPaths";
import { parseWebCitesFromStreamMeta } from "@/shared/lib/webCitation";
import type { ChatMessage, GlobalChat, LocalChat, Post } from "@/shared/types";
import type { WebCite } from "@/shared/api/schemas/post";

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

const contextStampPayloadSchema = z.object({
  path: z.array(z.number()),
  stamp: contextStampSchema,
});

export type ContextStampPayload = z.infer<typeof contextStampPayloadSchema>;

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

function formatContextStampLabel(stamp: z.infer<typeof contextStampSchema>): string {
  const { head, attach } = stamp.summary;
  const { msg, branch } = stamp.address;
  const turn = msg <= 0 ? "0" : `${branch}.${msg}`;
  if (stamp.scope === "post") {
    const lh = Math.max(1, head.post);
    let ga = attach.channel;
    let la = attach.post;
    if (ga <= 0 && la <= 0) {
      ga = 0;
      la = 0;
    }
    return `${head.channel}.${lh}-${ga}.${la}-${turn}`;
  }
  const ga = attach.channel > 0 ? attach.channel : 0;
  if (ga <= 0) {
    return `${head.channel}-0-${turn}`;
  }
  return `${head.channel}-${ga}-${turn}`;
}

function applyContextStamp(history: ChatMessage[], payload: ContextStampPayload): ChatMessage[] {
  const { path, stamp } = payload;
  const contextLabel = formatContextStampLabel(stamp);
  messageContextLabelSchema.parse(contextLabel);
  return mapMessageAtPath(history, path, (message) => {
    if (message.role !== "user") return message;
    const branches = message.userBranches;
    if (branches && branches.length > 1) {
      const bi = clampActiveBranchIndex(message);
      const existingStamp = branches[bi]?.contextStamp ?? (bi === 0 ? message.contextStamp : undefined);
      const existingLabel = branches[bi]?.contextLabel ?? (bi === 0 ? message.contextLabel : undefined);
      if (existingStamp || existingLabel) return message;
      const { contextLabel: _parentLabel, contextStamp: _parentStamp, ...rest } = message;
      return {
        ...rest,
        userBranches: branches.map((branch, index) =>
          index === bi ? { ...branch, contextLabel, contextStamp: stamp } : branch,
        ),
      };
    }
    if (message.contextStamp || message.contextLabel) return message;
    return { ...message, contextLabel, contextStamp: stamp };
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
  context_stamp: contextStampPayloadSchema.optional(),
  assistant_text: z.string().optional(),
});

function splitStreamMeta(meta: Record<string, unknown>): {
  chatMeta: ChatContextMeta;
  bundleStamp?: BundleContextStamp;
  labelStamp?: ContextLabelStamp;
  stampPayload?: ContextStampPayload;
  assistantText?: string;
  webCites?: WebCite[];
} {
  const webCites = parseWebCitesFromStreamMeta(meta);
  try {
    const parsed = streamMetaSchema.parse(meta);
    const { bundle_context_stamp, context_label_stamp, context_stamp, assistant_text, ...rest } =
      parsed;
    return {
      chatMeta: chatContextMetaSchema.parse(rest),
      bundleStamp: bundle_context_stamp,
      labelStamp: context_label_stamp,
      stampPayload: context_stamp,
      assistantText: assistant_text,
      webCites: webCites.length > 0 ? webCites : undefined,
    };
  } catch {
    return {
      chatMeta: {},
      webCites: webCites.length > 0 ? webCites : undefined,
      assistantText: typeof meta.assistant_text === "string" ? meta.assistant_text : undefined,
    };
  }
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

function applyWebCitesStamp(
  history: ChatMessage[],
  webCites: WebCite[],
  variantKey?: string,
): ChatMessage[] {
  return updateLastVisibleAiMessage(history, (message) => {
    if (message.role !== "ai") return message;
    if (variantKey && message.variants?.length) {
      return {
        ...message,
        variants: message.variants.map((variant) =>
          variant.key === variantKey ? { ...variant, webCites } : variant,
        ),
      };
    }
    return { ...message, webCites };
  });
}

function applyChatMetaPatch<T extends GlobalChat | LocalChat>(
  chat: T,
  patch: ChatContextMeta,
  bundleStamp?: BundleContextStamp,
  labelStamp?: ContextLabelStamp,
  stampPayload?: ContextStampPayload,
  assistantText?: string,
  webCites?: WebCite[],
  variantKey?: string,
): T {
  let next = { ...chat, ...patch } as T;
  if (stampPayload) {
    next = { ...next, history: applyContextStamp(next.history, stampPayload) };
  } else if (labelStamp) {
    next = { ...next, history: applyContextLabelStamp(next.history, labelStamp) };
  }
  if (bundleStamp) {
    next = { ...next, history: applyBundleContextStamp(next.history, bundleStamp) };
  }
  if (assistantText) {
    next = { ...next, history: applyAssistantTextStamp(next.history, assistantText) };
  }
  if (webCites && webCites.length > 0) {
    next = { ...next, history: applyWebCitesStamp(next.history, webCites, variantKey) };
  }
  return next;
}

export function patchGlobalChatContextMeta(
  queryClient: QueryClient,
  chatId: string,
  meta: ChatContextMeta | Record<string, unknown>,
  accountId = getQueryAccountIdFromAuth(),
  variantKey?: string,
): void {
  const { chatMeta, bundleStamp, labelStamp, stampPayload, assistantText, webCites } = splitStreamMeta(
    meta as Record<string, unknown>,
  );
  queryClient.setQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId), (prev) =>
    prev?.map((chat) =>
      chat.id === chatId
        ? applyChatMetaPatch(
            chat,
            chatMeta,
            bundleStamp,
            labelStamp,
            stampPayload,
            assistantText,
            webCites,
            variantKey,
          )
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
      stampPayload,
      assistantText,
      webCites,
      variantKey,
    );
  }, accountId);
}

export function patchPostChatContextMeta(
  queryClient: QueryClient,
  postId: string,
  chatId: string,
  meta: ChatContextMeta | Record<string, unknown>,
  accountId = getQueryAccountIdFromAuth(),
  variantKey?: string,
): void {
  const { chatMeta, bundleStamp, labelStamp, stampPayload, assistantText, webCites } = splitStreamMeta(
    meta as Record<string, unknown>,
  );
  const applyPatch = (post: Post): Post => ({
    ...post,
    chats: post.chats.map((chat) =>
      chat.id === chatId
        ? applyChatMetaPatch(
            chat,
            chatMeta,
            bundleStamp,
            labelStamp,
            stampPayload,
            assistantText,
            webCites,
            variantKey,
          )
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
