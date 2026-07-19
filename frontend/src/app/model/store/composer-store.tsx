"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
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
  completeStreamedAssistantReply,
  getChatSendValidationMessage,
  hasLlmForComposerScope,
  mergeVariantWebCites,
  pickWebCites,
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
import { updateLastVisibleAiMessage, updateAiMessageById, findLastVisibleAiMessage } from "@/shared/lib/chatPaths";
import { parseWebCitesFromStreamMeta } from "@/shared/lib/webCitation";
import type { WebCite } from "@/shared/api/schemas/post";
import { queryKeys } from "@/shared/api/queryKeys";
import { startAgentRun, streamAgentRun } from "@/shared/api/agentRuns";
import { messageContextManifestSchema, type MessageContextManifest } from "@/shared/api/schemas/agentRun";
import { ApiError } from "@/shared/api/httpClient";
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

async function runAgentAssistantTurn(params: {
  composerScope: ComposerScope;
  threadId: string;
  chatId: string;
  postId?: string;
  userText: string;
  signal: AbortSignal;
  onAnswer: (text: string) => void;
  onContext?: (messageId: string, manifest?: MessageContextManifest) => void;
}): Promise<string> {
  const { composerScope, threadId, chatId, postId, userText, signal, onAnswer, onContext } = params;
  const created = await startAgentRun(
    {
      threadId,
      scope: postId ? "post" : "global",
      chatId,
      postId,
      // For post scope, chatId is the id of the chat embedded in post.data.chats
      // (see readPostChat above) — that's what the backend needs as
      // post_chat_id to disambiguate which of the post's chats this run
      // belongs to (agent-runtime-sprints §2.1 memory).
      postChatId: postId ? chatId : undefined,
      userText,
    },
    signal,
  );
  useComposerReplyStore.getState().setRunId(composerScope, created.id);
  if (composerScope === "home") {
    useComposerReplyStore.getState().setRunId("gchat", created.id);
  }
  if (created.assistant_message_id) onContext?.(created.assistant_message_id);
  let answer = "";
  await streamAgentRun(
    created.id,
    (event) => {
      if (event.agent?.type === "answer") {
        answer = String(event.agent.payload.text ?? "");
        onAnswer(answer);
        const rawManifest = event.agent.payload.message_context_manifest;
        const parsedManifest = messageContextManifestSchema.safeParse(rawManifest);
        if (parsedManifest.success) onContext?.(parsedManifest.data.message_id, parsedManifest.data);
      }
      if (event.agent?.type === "run_failed") {
        throw new Error(String(event.agent.payload.error ?? "Agent run failed"));
      }
    },
    signal,
  );
  return answer;
}

async function runAgentWithLegacyFallback(
  runAgent: () => Promise<string>,
  runLegacy: () => Promise<{ text: string }>,
): Promise<string> {
  try {
    return await runAgent();
  } catch (error) {
    if (error instanceof ApiError && error.status === 501) {
      return (await runLegacy()).text;
    }
    throw error;
  }
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
}): Promise<{ text: string; webCites: WebCite[] }> {
  const { queryClient, accountId, chatId, assistant, userText, llmTarget, webTarget, variantKey, signal } =
    params;
  const chat = readGlobalChat(queryClient, accountId, chatId);
  let accumulated = "";
  let webCites: WebCite[] = [];
  try {
    const text = await assistant.streamGlobalChatReply(
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
        onMeta: (meta) => {
          const parsed = parseWebCitesFromStreamMeta(meta as Record<string, unknown>);
          if (parsed.length) webCites = parsed;
          patchGlobalChatContextMeta(queryClient, chatId, meta, accountId, variantKey);
        },
        signal,
      },
    );
    return { text, webCites };
  } catch (error) {
    if (isAbortError(error)) return { text: accumulated, webCites };
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
}): Promise<{ text: string; webCites: WebCite[] }> {
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
  let webCites: WebCite[] = [];
  try {
    const text = await assistant.streamPostChatReply(
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
        onMeta: (meta) => {
          const parsed = parseWebCitesFromStreamMeta(meta as Record<string, unknown>);
          if (parsed.length) webCites = parsed;
          patchPostChatContextMeta(queryClient, postId, chatId, meta, accountId, variantKey);
        },
        signal,
      },
    );
    return { text, webCites };
  } catch (error) {
    if (isAbortError(error)) return { text: accumulated, webCites };
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
}): Promise<{ texts: Record<string, string>; webCitesByVariant: Record<string, WebCite[]> }> {
  const pairs = buildMultiResponsePairs(params.cfg.llmModels, params.cfg.webSearchModels);
  const entries = await Promise.all(
    pairs.map(async (pair) => {
      const llmTarget = resolveLlmTarget(params.cfg, pair.llmId);
      const webTarget = resolveWebTarget(params.cfg, pair.webId) ?? undefined;
      const streamed = await streamGlobalAssistantReply({
        queryClient: params.queryClient,
        accountId: params.accountId,
        chatId: params.chatId,
        assistant: params.assistant,
        userText: params.userText,
        llmTarget,
        webTarget,
        variantKey: pair.id,
        signal: params.signal,
      });
      const text = await completeAssistantReply(
        async () => streamed.text,
        params.onError,
        { allowEmpty: true },
      );
      return [pair.id, { text, webCites: streamed.webCites }] as const;
    }),
  );
  const texts: Record<string, string> = {};
  const webCitesByVariant: Record<string, WebCite[]> = {};
  for (const [id, result] of entries) {
    texts[id] = result.text;
    if (result.webCites.length > 0) webCitesByVariant[id] = result.webCites;
  }
  return { texts, webCitesByVariant };
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
}): Promise<{ texts: Record<string, string>; webCitesByVariant: Record<string, WebCite[]> }> {
  const pairs = buildMultiResponsePairs(params.cfg.llmModels, params.cfg.webSearchModels);
  const entries = await Promise.all(
    pairs.map(async (pair) => {
      const llmTarget = resolveLlmTarget(params.cfg, pair.llmId);
      const webTarget = resolveWebTarget(params.cfg, pair.webId) ?? undefined;
      const streamed = await streamPostAssistantReply({
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
      });
      const text = await completeAssistantReply(
        async () => streamed.text,
        params.onError,
        { allowEmpty: true },
      );
      return [pair.id, { text, webCites: streamed.webCites }] as const;
    }),
  );
  const texts: Record<string, string> = {};
  const webCitesByVariant: Record<string, WebCite[]> = {};
  for (const [id, result] of entries) {
    texts[id] = result.text;
    if (result.webCites.length > 0) webCitesByVariant[id] = result.webCites;
  }
  return { texts, webCitesByVariant };
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
  useEffect(() => {
    aiProfileRef.current = aiProfile;
  }, [aiProfile]);

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

  const persistGlobalAgentContext = useCallback(
    (chatId: string, messageId: string, manifest?: MessageContextManifest) => {
      void patchGlobalChatHistory(queryClient, chats, chatId, (history) =>
        updateAiMessageById(history, messageId, (message) => ({
          ...message,
          messageId,
          ...(manifest
            ? {
                contextRefs: manifest.context_refs ?? [],
                citedEvidence: manifest.cited_evidence ?? [],
                artifacts: manifest.artifacts ?? [],
                staleRefs: manifest.stale_refs ?? [],
                contextProvenance: manifest.provenance,
              }
            : {}),
        })),
      );
    },
    [chats, queryClient],
  );

  const persistPostAgentContext = useCallback(
    (postId: string, chatId: string, messageId: string, manifest?: MessageContextManifest) => {
      void patchPostChatHistory(queryClient, posts, postId, chatId, (history) =>
        updateAiMessageById(history, messageId, (message) => ({
          ...message,
          messageId,
          ...(manifest
            ? {
                contextRefs: manifest.context_refs ?? [],
                citedEvidence: manifest.cited_evidence ?? [],
                artifacts: manifest.artifacts ?? [],
                staleRefs: manifest.stale_refs ?? [],
                contextProvenance: manifest.provenance,
              }
            : {}),
        })),
      );
    },
    [posts, queryClient],
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
      webCites?: WebCite[],
      variantWebCites?: Record<string, WebCite[]>,
    ) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return;
      const target = getTarget(scope);
      const lastAi = findLastVisibleAiMessage(readGlobalChat(queryClient, accountId, chatId)?.history ?? []);
      const mergedVariantWebCites = mergeVariantWebCites(lastAi, variantWebCites);
      const cachedCites = pickWebCites(webCites, lastAi?.webCites);
      const reply = buildAiReplyMessage(
        cfg,
        baseReply,
        scope,
        target,
        variantTexts,
        cachedCites,
        mergedVariantWebCites,
      );
      await patchGlobalChatHistory(queryClient, chats, chatId, (history) =>
        updateLastVisibleAiMessage(history, (current) => ({
          ...reply,
          // An agent run's HITL proposal can land on this same turn via a
          // separate SSE subscription (agent-run-store) racing this finalize
          // call — preserve it instead of letting an empty-text finalize
          // silently wipe the card.
          proposal: current.proposal,
          proposalDecision: current.proposalDecision,
          messageId: current.messageId,
          contextRefs: current.contextRefs,
          citedEvidence: current.citedEvidence,
          artifacts: current.artifacts,
          staleRefs: current.staleRefs,
          contextProvenance: current.contextProvenance,
        })),
      );
    },
    [accountId, chats, getTarget, queryClient],
  );

  const finalizePostReply = useCallback(
    async (
      postId: string,
      chatId: string,
      baseReply: string,
      variantTexts?: Record<string, string>,
      webCites?: WebCite[],
      variantWebCites?: Record<string, WebCite[]>,
    ) => {
      const cfg = aiProfileRef.current;
      if (!cfg) return;
      const target = getTarget("post");
      const lastAi = findLastVisibleAiMessage(readPostChatHistory(queryClient, accountId, postId, chatId));
      const mergedVariantWebCites = mergeVariantWebCites(lastAi, variantWebCites);
      const cachedCites = pickWebCites(webCites, lastAi?.webCites);
      const reply = buildAiReplyMessage(
        cfg,
        baseReply,
        "post",
        target,
        variantTexts,
        cachedCites,
        mergedVariantWebCites,
      );
      await patchPostChatHistory(queryClient, posts, postId, chatId, (history) =>
        updateLastVisibleAiMessage(history, (current) => ({
          ...reply,
          // See finalizeGlobalReply: preserve a proposal card written by the
          // agent-run-store's separate SSE subscription racing this finalize.
          proposal: current.proposal,
          proposalDecision: current.proposalDecision,
          messageId: current.messageId,
          contextRefs: current.contextRefs,
          citedEvidence: current.citedEvidence,
          artifacts: current.artifacts,
          staleRefs: current.staleRefs,
          contextProvenance: current.contextProvenance,
        })),
      );
    },
    [accountId, getTarget, posts, queryClient],
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
            const multi = await runMultiGlobalAssistantReplies({
                queryClient,
                accountId,
                chatId: id,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              });
            const variantTexts = resolveFinalMultiAssistantReply(multi.texts, signal);
            await finalizeGlobalReply(id, "home", "", variantTexts, undefined, multi.webCitesByVariant);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                runAgentWithLegacyFallback(
                  () =>
                    runAgentAssistantTurn({
                      composerScope: "home",
                      threadId: id,
                      chatId: id,
                      userText: text,
                      signal,
                      onAnswer: (answer) =>
                        patchGlobalChatStreamingText(queryClient, id, answer, accountId),
                      onContext: (messageId, manifest) =>
                        persistGlobalAgentContext(id, messageId, manifest),
                    }),
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
                ),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizeGlobalReply(
              id,
              "home",
              resolveFinalAssistantReply(baseReply, signal),
              undefined,
              undefined,
            );
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
      persistGlobalAgentContext,
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
            const multi = await runMultiGlobalAssistantReplies({
                queryClient,
                accountId,
                chatId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              });
            const variantTexts = resolveFinalMultiAssistantReply(multi.texts, signal);
            await finalizeGlobalReply(chatId, "gchat", "", variantTexts, undefined, multi.webCitesByVariant);
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                runAgentWithLegacyFallback(
                  () =>
                    runAgentAssistantTurn({
                      composerScope: "gchat",
                      threadId: chatId,
                      chatId,
                      userText: text,
                      signal,
                      onAnswer: (answer) =>
                        patchGlobalChatStreamingText(queryClient, chatId, answer, accountId),
                      onContext: (messageId, manifest) =>
                        persistGlobalAgentContext(chatId, messageId, manifest),
                    }),
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
                ),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizeGlobalReply(
              chatId,
              "gchat",
              resolveFinalAssistantReply(baseReply, signal),
              undefined,
              undefined,
            );
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      });
      return true;
    },
    [accountId, assertCanSend, assistant, finalizeGlobalReply, getTarget, pushMessage, queryClient, persistGlobalAgentContext],
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
            const multi = await runMultiPostAssistantReplies({
                queryClient,
                accountId,
                postId,
                chatId: replyChatId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              });
            const variantTexts = resolveFinalMultiAssistantReply(multi.texts, signal);
            await finalizePostReply(
              postId,
              replyChatId,
              "",
              variantTexts,
              undefined,
              multi.webCitesByVariant,
            );
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                runAgentWithLegacyFallback(
                  () =>
                    runAgentAssistantTurn({
                      composerScope: "post",
                      threadId: replyChatId,
                      postId,
                      chatId: replyChatId,
                      userText: text,
                      signal,
                      onAnswer: (answer) =>
                        patchPostChatStreamingText(
                          queryClient,
                          postId,
                          replyChatId,
                          answer,
                          accountId,
                        ),
                      onContext: (messageId, manifest) =>
                        persistPostAgentContext(postId, replyChatId, messageId, manifest),
                    }),
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
                ),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizePostReply(
              postId,
              replyChatId,
              resolveFinalAssistantReply(baseReply, signal),
              undefined,
              undefined,
            );
          }
        } finally {
          useComposerReplyStore.getState().endReply();
        }
      });

      return true;
    },
    [accountId, addLocalChat, assertCanSend, assistant, finalizePostReply, getTarget, pushLocalChatMessage, queryClient, persistPostAgentContext],
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
            const multi = await runMultiGlobalAssistantReplies({
                queryClient,
                accountId,
                chatId: ctx.entityId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              });
            const variantTexts = resolveFinalMultiAssistantReply(multi.texts, signal);
            await finalizeGlobalReply(
              ctx.entityId,
              "gchat",
              "",
              variantTexts,
              undefined,
              multi.webCitesByVariant,
            );
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                runAgentWithLegacyFallback(
                  () =>
                    runAgentAssistantTurn({
                      composerScope: "gchat",
                      threadId: ctx.entityId,
                      chatId: ctx.entityId,
                      userText: text,
                      signal,
                      onAnswer: (answer) =>
                        patchGlobalChatStreamingText(queryClient, ctx.entityId, answer, accountId),
                      onContext: (messageId, manifest) =>
                        persistGlobalAgentContext(ctx.entityId, messageId, manifest),
                    }),
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
                ),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizeGlobalReply(
              ctx.entityId,
              "gchat",
              resolveFinalAssistantReply(baseReply, signal),
              undefined,
              undefined,
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
            const multi = await runMultiPostAssistantReplies({
                queryClient,
                accountId,
                postId: ctx.postId,
                chatId: ctx.entityId,
                assistant,
                userText: text,
                cfg,
                signal,
                onError: onStreamError,
              });
            const variantTexts = resolveFinalMultiAssistantReply(multi.texts, signal);
            await finalizePostReply(
              ctx.postId,
              ctx.entityId,
              "",
              variantTexts,
              undefined,
              multi.webCitesByVariant,
            );
          } else {
            const baseReply = await completeAssistantReply(
              () =>
                runAgentWithLegacyFallback(
                  () =>
                    runAgentAssistantTurn({
                      composerScope: "post",
                      threadId: ctx.entityId,
                      postId: ctx.postId,
                      chatId: ctx.entityId,
                      userText: text,
                      signal,
                      onAnswer: (answer) =>
                        patchPostChatStreamingText(
                          queryClient,
                          ctx.postId,
                          ctx.entityId,
                          answer,
                          accountId,
                        ),
                      onContext: (messageId, manifest) =>
                        persistPostAgentContext(ctx.postId, ctx.entityId, messageId, manifest),
                    }),
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
                ),
              onStreamError,
              { allowEmpty: true },
            );
            await finalizePostReply(
              ctx.postId,
              ctx.entityId,
              resolveFinalAssistantReply(baseReply, signal),
              undefined,
              undefined,
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
      persistGlobalAgentContext,
      persistPostAgentContext,
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
