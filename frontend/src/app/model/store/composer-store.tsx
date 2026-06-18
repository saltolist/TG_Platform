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
  resolveLlmLabel,
  resolveWebLabel,
} from "@/app/model/store/composer/helpers";
import { useEffectiveAiProfileConfig } from "@/app/model/store/useEffectiveAiProfileConfig";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { patchGlobalChatHistory } from "@/entities/chat/lib/patchGlobalChatHistory";
import { patchPostChatHistory } from "@/entities/post/lib/patchPostChatHistory";
import { isPresentationAccount } from "@/shared/lib/auth/queryAccountScope";
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
import type { AssistantRepository } from "@/shared/api/repositories";
import type { ChatMessage, ComposerScope, GlobalChat, LocalChat, Post } from "@/shared/types";

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
  signal?: AbortSignal;
}): Promise<string> {
  const { queryClient, accountId, chatId, assistant, userText, llmTarget, signal } = params;
  const chat = readGlobalChat(queryClient, accountId, chatId);
  let accumulated = "";
  try {
    return await assistant.streamGlobalChatReply(
      userText,
      (chunk) => {
        accumulated += chunk;
        patchGlobalChatStreamingText(queryClient, chatId, accumulated, accountId);
      },
      {
        ...llmTarget,
        chatId,
        history: chat?.history ?? [],
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
  signal?: AbortSignal;
}): Promise<string> {
  const { queryClient, accountId, postId, chatId, assistant, userText, llmTarget, signal } = params;
  const chat = readPostChat(queryClient, accountId, postId, chatId);
  let accumulated = "";
  try {
    return await assistant.streamPostChatReply(
      userText,
      (chunk) => {
        accumulated += chunk;
        patchPostChatStreamingText(queryClient, postId, chatId, accumulated, accountId);
      },
      {
        ...llmTarget,
        postId,
        postChatId: chatId,
        history: chat?.history ?? [],
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
    async (chatId: string, scope: ComposerScope, baseReply: string) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return;
      const target = getTarget(scope);
      const reply = buildAiReplyMessage(cfg, baseReply, scope, target);
      await patchGlobalChatHistory(queryClient, chats, chatId, (history) =>
        updateLastVisibleAiMessage(history, () => reply),
      );
    },
    [chats, getTarget, queryClient],
  );

  const finalizePostReply = useCallback(
    async (postId: string, chatId: string, baseReply: string) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return;
      const target = getTarget("post");
      const reply = buildAiReplyMessage(cfg, baseReply, "post", target);
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
        try {
          const baseReply = await completeAssistantReply(
            () =>
              streamGlobalAssistantReply({
                queryClient,
                accountId,
                chatId: id,
                assistant,
                userText: text,
                llmTarget: resolveLlmTarget(cfg, target.llmId),
                signal,
              }),
            (message) => showToast({ message, variant: "error" }),
            { allowEmpty: true },
          );
          await finalizeGlobalReply(id, "home", resolveFinalAssistantReply(baseReply, signal));
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
        try {
          const baseReply = await completeAssistantReply(
            () =>
              streamGlobalAssistantReply({
                queryClient,
                accountId,
                chatId,
                assistant,
                userText: text,
                llmTarget: resolveLlmTarget(cfg, target.llmId),
                signal,
              }),
            (message) => showToast({ message, variant: "error" }),
            { allowEmpty: true },
          );
          await finalizeGlobalReply(chatId, "gchat", resolveFinalAssistantReply(baseReply, signal));
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
        try {
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
                signal,
              }),
            (message) => showToast({ message, variant: "error" }),
            { allowEmpty: true },
          );
          await finalizePostReply(
            postId,
            replyChatId,
            resolveFinalAssistantReply(baseReply, signal),
          );
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      });

      return true;
    },
    [accountId, addLocalChat, assertCanSend, assistant, finalizePostReply, getTarget, pushLocalChatMessage, queryClient],
  );

  const value = useMemo<ComposerContextValue>(
    () => ({
      sendHome,
      sendGChat,
      sendPost,
      hasLlmForSend,
      setComposerLlm,
      setComposerWeb,
      registerNavBridge,
    }),
    [sendHome, sendGChat, sendPost, hasLlmForSend, setComposerLlm, setComposerWeb, registerNavBridge],
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
