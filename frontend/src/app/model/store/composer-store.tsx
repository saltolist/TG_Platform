"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUiStore } from "@/app/model/store/ui-store";
import { useComposerTargetStore } from "@/app/model/store/composer-target-store";
import { useComposerReplyStore } from "@/app/model/store/composer-reply-store";
import {
  buildAiReplyMessage,
  buildStreamingAiShell,
  completeAssistantReply,
  getChatSendValidationMessage,
  hasLlmForComposerScope,
  resolveLlmTarget,
  resolveWebTarget,
  resolveLlmLabel,
  resolveWebLabel,
} from "@/app/model/store/composer/helpers";
import { useEffectiveAiProfileConfig } from "@/app/model/store/useEffectiveAiProfileConfig";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { patchGlobalChatHistory } from "@/entities/chat/lib/patchGlobalChatHistory";
import { patchPostChatHistory } from "@/entities/post/lib/patchPostChatHistory";
import { isPresentationAccount } from "@/shared/lib/auth/queryAccountScope";
import { isOverlayAccount } from "@/shared/lib/overlay/isOverlayAccount";
import { useCreateGlobalChat, usePushGlobalChatMessage } from "@/entities/chat";
import { useAddLocalChat, usePushLocalChatMessage } from "@/entities/post";
import { routes } from "@/shared/lib/routes";
import { truncate } from "@/shared/lib/helpers";
import { buildMultiResponsePairs } from "@/shared/config/composer";
import { randomId } from "@/shared/lib/randomId";
import { showToast } from "@/shared/ui/toast";
import { isAbortError } from "@/shared/lib/isAbortError";
import { patchGlobalChatStreamingText, patchPostChatStreamingText } from "@/shared/lib/streaming/patchStreamingReply";
import {
  patchGlobalChatContextMeta,
  patchPostChatContextMeta,
} from "@/shared/lib/streaming/patchChatContextMeta";
import { extractChatContextMeta } from "@/shared/api/schemas/chatContextMeta";
import { updateLastVisibleAiMessage } from "@/shared/lib/chatPaths";
import { queryKeys } from "@/shared/api/queryKeys";
import type { ChatMessageCtx } from "@/entities/message";
import type { AssistantRepository } from "@/shared/api/repositories";
import type {
  AiProfileConfig,
  ChatMessage,
  ComposerScope,
  GlobalChat,
  LocalChat,
  Post,
} from "@/shared/types";

export type ComposerNavBridge = {
  goToHref: (href: string, opts?: { replace?: boolean }) => boolean;
  getCurrentGChatId: () => string | null;
  getCurrentPostId: () => string | null;
  getCurrentPostChatId: () => string | null;
  setCurrentPostChatId: (chatId: string) => void;
};

export type ComposerContextValue = {
  sendHome: (text: string) => boolean;
  sendGChat: (text: string) => boolean;
  sendPost: (text: string) => boolean;
  regenerateAfterUserEdit: (ctx: ChatMessageCtx, editedText: string) => Promise<void>;
  hasLlmForSend: (scope: ComposerScope) => boolean;
  setComposerLlm: (scope: ComposerScope, llmId: string) => void;
  setComposerWeb: (scope: ComposerScope, webId: string) => void;
  registerNavBridge: (bridge: ComposerNavBridge) => () => void;
};

const ComposerContext = createContext<ComposerContextValue | null>(null);

function readGlobalChat(
  queryClient: ReturnType<typeof useQueryClient>,
  accountId: string,
  chatId: string,
): GlobalChat | null {
  const fromDetail = queryClient.getQueryData<GlobalChat>(
    queryKeys.globalChats.detail(accountId, chatId),
  );
  if (fromDetail) return fromDetail;

  const list = queryClient.getQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId));
  return list?.find((chat) => chat.id === chatId) ?? null;
}

function readGlobalChatHistory(
  queryClient: ReturnType<typeof useQueryClient>,
  accountId: string,
  chatId: string,
): ChatMessage[] {
  return readGlobalChat(queryClient, accountId, chatId)?.history ?? [];
}

function readPostChat(
  queryClient: ReturnType<typeof useQueryClient>,
  accountId: string,
  postId: string,
  chatId: string,
): LocalChat | null {
  const fromDetail = queryClient.getQueryData<Post>(queryKeys.posts.detail(accountId, postId));
  const post =
    fromDetail ??
    queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId))?.find((item) => item.id === postId);
  return post?.chats?.find((item) => item.id === chatId) ?? null;
}

function readPostChatHistory(
  queryClient: ReturnType<typeof useQueryClient>,
  accountId: string,
  postId: string,
  chatId: string,
): ChatMessage[] {
  return readPostChat(queryClient, accountId, postId, chatId)?.history ?? [];
}

async function streamGlobalAssistantReply(params: {
  queryClient: ReturnType<typeof useQueryClient>;
  accountId: string;
  chatId: string;
  assistant: AssistantRepository;
  userText: string;
  llmTarget: ReturnType<typeof resolveLlmTarget>;
  webTarget?: ReturnType<typeof resolveWebTarget>;
  variantKey?: string;
  signal?: AbortSignal;
}): Promise<string> {
  const { queryClient, accountId, chatId, assistant, userText, llmTarget, webTarget, variantKey, signal } =
    params;
  const chat = readGlobalChat(queryClient, accountId, chatId);
  let accumulated = "";
  try {
    return await assistant.streamGlobalChatReply(
      userText,
      (chunk) => {
        accumulated += chunk;
        patchGlobalChatStreamingText(
          queryClient,
          chatId,
          accumulated,
          accountId,
          variantKey,
        );
      },
      {
        ...llmTarget,
        ...(webTarget ?? {}),
        chatId,
        history: isOverlayAccount(accountId) ? (chat?.history ?? []) : undefined,
        chatMeta: extractChatContextMeta(chat ?? undefined),
        onMeta: (meta) => patchGlobalChatContextMeta(queryClient, chatId, meta, accountId),
        signal,
      },
    );
  } catch (error) {
    if (isAbortError(error)) return accumulated;
    throw error;
  }
}

async function streamPostAssistantReply(params: {
  queryClient: ReturnType<typeof useQueryClient>;
  accountId: string;
  postId: string;
  chatId: string;
  assistant: AssistantRepository;
  userText: string;
  llmTarget: ReturnType<typeof resolveLlmTarget>;
  webTarget?: ReturnType<typeof resolveWebTarget>;
  variantKey?: string;
  signal?: AbortSignal;
}): Promise<string> {
  const {
    queryClient,
    accountId,
    postId,
    chatId,
    assistant,
    userText,
    llmTarget,
    webTarget,
    variantKey,
    signal,
  } = params;
  const chat = readPostChat(queryClient, accountId, postId, chatId);
  let accumulated = "";
  try {
    return await assistant.streamPostChatReply(
      userText,
      (chunk) => {
        accumulated += chunk;
        patchPostChatStreamingText(
          queryClient,
          postId,
          chatId,
          accumulated,
          accountId,
          variantKey,
        );
      },
      {
        ...llmTarget,
        ...(webTarget ?? {}),
        postId,
        postChatId: chatId,
        history: isOverlayAccount(accountId) ? (chat?.history ?? []) : undefined,
        chatMeta: extractChatContextMeta(chat ?? undefined),
        onMeta: (meta) => patchPostChatContextMeta(queryClient, postId, chatId, meta, accountId),
        signal,
      },
    );
  } catch (error) {
    if (isAbortError(error)) return accumulated;
    throw error;
  }
}

const STOPPED_REPLY_TEXT = "Генерация остановлена.";

function resolveFinalAssistantReply(baseReply: string, signal: AbortSignal): string {
  if (signal.aborted && !baseReply.trim()) return STOPPED_REPLY_TEXT;
  return baseReply;
}

function resolveFinalMultiAssistantReply(
  variantTexts: Record<string, string>,
  signal: AbortSignal,
): Record<string, string> {
  if (!signal.aborted) return variantTexts;
  const resolved: Record<string, string> = {};
  for (const [key, text] of Object.entries(variantTexts)) {
    resolved[key] = text.trim() ? text : STOPPED_REPLY_TEXT;
  }
  return resolved;
}

async function runMultiGlobalAssistantReplies(params: {
  queryClient: ReturnType<typeof useQueryClient>;
  accountId: string;
  chatId: string;
  assistant: AssistantRepository;
  userText: string;
  cfg: AiProfileConfig;
  signal: AbortSignal;
  onError: (message: string) => void;
}): Promise<Record<string, string>> {
  const pairs = buildMultiResponsePairs(params.cfg.llmModels, params.cfg.webSearchModels);
  const entries = await Promise.all(
    pairs.map(async (pair) => {
      const llmTarget = resolveLlmTarget(params.cfg, pair.llmId);
      const webTarget = resolveWebTarget(params.cfg, pair.webId) ?? undefined;
      const text = await completeAssistantReply(
        () =>
          streamGlobalAssistantReply({
            queryClient: params.queryClient,
            accountId: params.accountId,
            chatId: params.chatId,
            assistant: params.assistant,
            userText: params.userText,
            llmTarget,
            webTarget,
            variantKey: pair.id,
            signal: params.signal,
          }),
        params.onError,
        { allowEmpty: true },
      );
      return [pair.id, text] as const;
    }),
  );
  return Object.fromEntries(entries);
}

async function runMultiPostAssistantReplies(params: {
  queryClient: ReturnType<typeof useQueryClient>;
  accountId: string;
  postId: string;
  chatId: string;
  assistant: AssistantRepository;
  userText: string;
  cfg: AiProfileConfig;
  signal: AbortSignal;
  onError: (message: string) => void;
}): Promise<Record<string, string>> {
  const pairs = buildMultiResponsePairs(params.cfg.llmModels, params.cfg.webSearchModels);
  const entries = await Promise.all(
    pairs.map(async (pair) => {
      const llmTarget = resolveLlmTarget(params.cfg, pair.llmId);
      const webTarget = resolveWebTarget(params.cfg, pair.webId) ?? undefined;
      const text = await completeAssistantReply(
        () =>
          streamPostAssistantReply({
            queryClient: params.queryClient,
            accountId: params.accountId,
            postId: params.postId,
            chatId: params.chatId,
            assistant: params.assistant,
            userText: params.userText,
            llmTarget,
            webTarget,
            variantKey: pair.id,
            signal: params.signal,
          }),
        params.onError,
        { allowEmpty: true },
      );
      return [pair.id, text] as const;
    }),
  );
  return Object.fromEntries(entries);
}

export function ComposerProvider({ children }: { children: ReactNode }) {
  const { assistant, chats, posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const aiProfile = useEffectiveAiProfileConfig();
  const createChat = useCreateGlobalChat();
  const pushMessage = usePushGlobalChatMessage();
  const addLocalChat = useAddLocalChat();
  const pushLocalChatMessage = usePushLocalChatMessage();
  const setMobileSidebarOpen = useUiStore((s) => s.setMobileSidebarOpen);
  const setLlmId = useComposerTargetStore((s) => s.setLlmId);
  const setWebId = useComposerTargetStore((s) => s.setWebId);
  const getTarget = useComposerTargetStore((s) => s.getTarget);

  const navBridgeRef = useRef<ComposerNavBridge | null>(null);
  const aiProfileRef = useRef(aiProfile);
  aiProfileRef.current = aiProfile;

  const registerNavBridge = useCallback((bridge: ComposerNavBridge) => {
    navBridgeRef.current = bridge;
    return () => {
      if (navBridgeRef.current === bridge) navBridgeRef.current = null;
    };
  }, []);

  const assertCanSend = useCallback(
    (scope: ComposerScope) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return false;
      const message = getChatSendValidationMessage(cfg, scope, getTarget(scope).llmId, {
        requireOrchestrator: !isPresentationAccount(),
      });
      if (!message) return true;
      showToast({ message, variant: "error" });
      return false;
    },
    [getTarget],
  );

  const setComposerLlm = useCallback(
    (scope: ComposerScope, llmId: string) => setLlmId(scope, llmId),
    [setLlmId],
  );

  const setComposerWeb = useCallback(
    (scope: ComposerScope, webId: string) => setWebId(scope, webId),
    [setWebId],
  );

  const hasLlmForSend = useCallback(
    (scope: ComposerScope) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return false;
      return hasLlmForComposerScope(cfg, scope, getTarget(scope).llmId);
    },
    [getTarget],
  );

  const finalizeGlobalReply = useCallback(
    async (
      chatId: string,
      scope: ComposerScope,
      baseReply: string,
      variantTexts?: Record<string, string>,
    ) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return;
      const target = getTarget(scope);
      const reply = buildAiReplyMessage(cfg, baseReply, scope, target, variantTexts);
      await patchGlobalChatHistory(queryClient, chats, chatId, (history) =>
        updateLastVisibleAiMessage(history, () => reply),
      );
    },
    [chats, getTarget, queryClient],
  );

  const finalizePostReply = useCallback(
    async (
      postId: string,
      chatId: string,
      baseReply: string,
      variantTexts?: Record<string, string>,
    ) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return;
      const target = getTarget("post");
      const reply = buildAiReplyMessage(cfg, baseReply, "post", target, variantTexts);
      await patchPostChatHistory(queryClient, posts, postId, chatId, (history) =>
        updateLastVisibleAiMessage(history, () => reply),
      );
    },
    [getTarget, posts, queryClient],
  );

  const sendHome = useCallback(
    (text: string) => {
      const bridge = navBridgeRef.current;
      const cfg = aiProfileRef.current;
      if (!text.trim() || !bridge || !cfg) return false;
      if (!assertCanSend("home")) return false;
      setMobileSidebarOpen(false);

      const id = randomId();
      const newChat: GlobalChat = {
        id,
        title: truncate(text, 40),
        preview: text,
        date: new Date().toISOString(),
        history: [{ role: "user", text }],
      };

      void createChat.mutateAsync(newChat).then(async () => {
        bridge.goToHref(routes.gchat(id));
        const target = getTarget("home");
        await pushMessage.mutateAsync({
          chatId: id,
          message: buildStreamingAiShell(cfg, target),
        });
        const signal = useComposerReplyStore.getState().beginReply("home");
        const onStreamError = (message: string) => showToast({ message, variant: "error" });
        try {
          if (cfg.multiResponseEnabled) {
            const variantTexts = resolveFinalMultiAssistantReply(
              await runMultiGlobalAssistantReplies({
                queryClient,
                accountId,
                chatId: id,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              }),
              signal,
            );
            await finalizeGlobalReply(id, "home", "", variantTexts);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                streamGlobalAssistantReply({
                  queryClient,
                  accountId,
                  chatId: id,
                  assistant,
                  userText: text,
                  llmTarget: resolveLlmTarget(cfg, target.llmId),
                  webTarget: resolveWebTarget(cfg, target.webId) ?? undefined,
                  signal,
                }),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizeGlobalReply(id, "home", resolveFinalAssistantReply(baseReply, signal));
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      });

      return true;
    },
    [
      accountId,
      assertCanSend,
      assistant,
      createChat,
      finalizeGlobalReply,
      getTarget,
      pushMessage,
      queryClient,
      setMobileSidebarOpen,
    ],
  );

  const sendGChat = useCallback(
    (text: string) => {
      const bridge = navBridgeRef.current;
      const cfg = aiProfileRef.current;
      const chatId = bridge?.getCurrentGChatId();
      if (!text.trim() || !chatId || !cfg) return false;
      if (!assertCanSend("gchat")) return false;
      void pushMessage.mutateAsync({ chatId, message: { role: "user", text } }).then(async () => {
        const target = getTarget("gchat");
        await pushMessage.mutateAsync({
          chatId,
          message: buildStreamingAiShell(cfg, target),
        });
        const signal = useComposerReplyStore.getState().beginReply("gchat");
        const onStreamError = (message: string) => showToast({ message, variant: "error" });
        try {
          if (cfg.multiResponseEnabled) {
            const variantTexts = resolveFinalMultiAssistantReply(
              await runMultiGlobalAssistantReplies({
                queryClient,
                accountId,
                chatId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              }),
              signal,
            );
            await finalizeGlobalReply(chatId, "gchat", "", variantTexts);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                streamGlobalAssistantReply({
                  queryClient,
                  accountId,
                  chatId,
                  assistant,
                  userText: text,
                  llmTarget: resolveLlmTarget(cfg, target.llmId),
                  webTarget: resolveWebTarget(cfg, target.webId) ?? undefined,
                  signal,
                }),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizeGlobalReply(chatId, "gchat", resolveFinalAssistantReply(baseReply, signal));
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      });
      return true;
    },
    [accountId, assertCanSend, assistant, finalizeGlobalReply, getTarget, pushMessage, queryClient],
  );

  const sendPost = useCallback(
    (text: string) => {
      const bridge = navBridgeRef.current;
      const cfg = aiProfileRef.current;
      if (!bridge || !cfg) return false;
      const postId = bridge.getCurrentPostId();
      if (!text.trim() || postId == null) return false;
      if (!assertCanSend("post")) return false;

      let chatId = bridge.getCurrentPostChatId();
      const ensureChat = chatId
        ? Promise.resolve(chatId)
        : (() => {
            const newChatId = randomId();
            const newChat: LocalChat = {
              id: newChatId,
              title: truncate(text, 40),
              preview: text,
              date: new Date().toISOString(),
              ai: true,
              history: [{ role: "user", text }],
            };
            return addLocalChat(postId, newChat).then(() => {
              bridge.setCurrentPostChatId(newChatId);
              bridge.goToHref(routes.post(postId, newChatId), { replace: true });
              return newChatId;
            });
          })();

      void ensureChat.then(async (replyChatId) => {
        const isNewChat = chatId == null;
        if (!isNewChat) {
          await pushLocalChatMessage(postId, replyChatId, { role: "user", text });
        }
        const target = getTarget("post");
        await pushLocalChatMessage(postId, replyChatId, buildStreamingAiShell(cfg, target));
        const signal = useComposerReplyStore.getState().beginReply("post");
        const onStreamError = (message: string) => showToast({ message, variant: "error" });
        try {
          if (cfg.multiResponseEnabled) {
            const variantTexts = resolveFinalMultiAssistantReply(
              await runMultiPostAssistantReplies({
                queryClient,
                accountId,
                postId,
                chatId: replyChatId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              }),
              signal,
            );
            await finalizePostReply(postId, replyChatId, "", variantTexts);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                streamPostAssistantReply({
                  queryClient,
                  accountId,
                  postId,
                  chatId: replyChatId,
                  assistant,
                  userText: text,
                  llmTarget: resolveLlmTarget(cfg, target.llmId),
                  webTarget: resolveWebTarget(cfg, target.webId) ?? undefined,
                  signal,
                }),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizePostReply(
              postId,
              replyChatId,
              resolveFinalAssistantReply(baseReply, signal),
            );
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      });

      return true;
    },
    [accountId, addLocalChat, assertCanSend, assistant, finalizePostReply, getTarget, pushLocalChatMessage, queryClient],
  );

  const regenerateAfterUserEdit = useCallback(
    async (ctx: ChatMessageCtx, editedText: string) => {
      const cfg = aiProfileRef.current;
      const text = editedText.trim();
      if (!cfg || !text) return;

      const onStreamError = (message: string) => showToast({ message, variant: "error" });

      if (ctx.scope === "gchat") {
        if (!assertCanSend("gchat")) return;
        const target = getTarget("gchat");
        await pushMessage.mutateAsync({
          chatId: ctx.entityId,
          message: buildStreamingAiShell(cfg, target),
        });
        const signal = useComposerReplyStore.getState().beginReply("gchat");
        try {
          if (cfg.multiResponseEnabled) {
            const variantTexts = resolveFinalMultiAssistantReply(
              await runMultiGlobalAssistantReplies({
                queryClient,
                accountId,
                chatId: ctx.entityId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              }),
              signal,
            );
            await finalizeGlobalReply(ctx.entityId, "gchat", "", variantTexts);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                streamGlobalAssistantReply({
                  queryClient,
                  accountId,
                  chatId: ctx.entityId,
                  assistant,
                  userText: text,
                  llmTarget: resolveLlmTarget(cfg, target.llmId),
                  webTarget: resolveWebTarget(cfg, target.webId) ?? undefined,
                  signal,
                }),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizeGlobalReply(
              ctx.entityId,
              "gchat",
              resolveFinalAssistantReply(baseReply, signal),
            );
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
        return;
      }

      if (ctx.scope === "post") {
        if (!assertCanSend("post")) return;
        const target = getTarget("post");
        await pushLocalChatMessage(
          ctx.postId,
          ctx.entityId,
          buildStreamingAiShell(cfg, target),
        );
        const signal = useComposerReplyStore.getState().beginReply("post");
        try {
          if (cfg.multiResponseEnabled) {
            const variantTexts = resolveFinalMultiAssistantReply(
              await runMultiPostAssistantReplies({
                queryClient,
                accountId,
                postId: ctx.postId,
                chatId: ctx.entityId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              }),
              signal,
            );
            await finalizePostReply(ctx.postId, ctx.entityId, "", variantTexts);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                streamPostAssistantReply({
                  queryClient,
                  accountId,
                  postId: ctx.postId,
                  chatId: ctx.entityId,
                  assistant,
                  userText: text,
                  llmTarget: resolveLlmTarget(cfg, target.llmId),
                  webTarget: resolveWebTarget(cfg, target.webId) ?? undefined,
                  signal,
                }),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizePostReply(
              ctx.postId,
              ctx.entityId,
              resolveFinalAssistantReply(baseReply, signal),
            );
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      }
    },
    [
      accountId,
      assertCanSend,
      assistant,
      finalizeGlobalReply,
      finalizePostReply,
      getTarget,
      pushLocalChatMessage,
      pushMessage,
      queryClient,
    ],
  );

  const value = useMemo<ComposerContextValue>(
    () => ({
      sendHome,
      sendGChat,
      sendPost,
      regenerateAfterUserEdit,
      hasLlmForSend,
      setComposerLlm,
      setComposerWeb,
      registerNavBridge,
    }),
    [sendHome, sendGChat, sendPost, regenerateAfterUserEdit, hasLlmForSend, setComposerLlm, setComposerWeb, registerNavBridge],
  );

  return <ComposerContext.Provider value={value}>{children}</ComposerContext.Provider>;
}

export function useComposer(): ComposerContextValue {
  const ctx = useContext(ComposerContext);
  if (!ctx) throw new Error("useComposer must be used inside <ComposerProvider>");
  return ctx;
}

export function useComposerLabels() {
  const cfg = useEffectiveAiProfileConfig();
  return useMemo(
    () => ({
      llmLabel: (id: string) => resolveLlmLabel(cfg, id),
      webLabel: (id: string) => resolveWebLabel(cfg, id),
      multiResponsePairs: () => buildMultiResponsePairs(cfg.llmModels, cfg.webSearchModels),
    }),
    [cfg],
  );
}
