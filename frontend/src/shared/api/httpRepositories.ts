import { apiV1Path } from "@/shared/config/basePath";
import { apiRequest, apiSseSubscribe, apiStream } from "@/shared/api/httpClient";
import type { AssistantStreamOptions, RepositoryBundle, TelegramReconcileResponse } from "@/shared/api/repositories";
import {
  normalizeAiProfileConfigFromServer,
  normalizeChannelProfileConfig,
  normalizeTelegramProfileConfig,
} from "@/shared/lib/profile/normalizeProfileConfig";
import {
  globalChatsListSchema,
  globalChatSchema,
  globalNotesListSchema,
  globalNoteSchema,
  postsListSchema,
  postSchema,
} from "@/shared/api/schemas";
import type { ChatContextMeta } from "@/shared/api/schemas/chatContextMeta";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";
import {
  channelAnalyticsOverviewSchema,
  channelAnalyticsTopPostsSchema,
} from "@/shared/api/schemas/channelAnalytics";
import {
  platformModelAnalyticsSchema,
} from "@/shared/api/schemas/platformAnalytics";

function streamAiReply(
  scope: "global" | "post",
  text: string,
  onChunk: (chunk: string) => void,
  options?: AssistantStreamOptions,
) {
  const body: Record<string, unknown> = { text, scope };
  if (options?.llmId) body.llmId = options.llmId;
  if (options?.provider) body.provider = options.provider;
  if (options?.model) body.model = options.model;
  if (options?.apiKey) body.apiKey = options.apiKey;
  if (options?.webId) body.webId = options.webId;
  if (options?.webProvider) body.webProvider = options.webProvider;
  if (options?.webModel) body.webModel = options.webModel;
  if (options?.webApiKey) body.webApiKey = options.webApiKey;
  if (options?.chatId) body.chatId = options.chatId;
  if (options?.postId) body.postId = options.postId;
  if (options?.postChatId) body.postChatId = options.postChatId;
  if (Array.isArray(options?.history)) body.history = options.history;
  if (options?.chatMeta) body.chatMeta = options.chatMeta;
  return apiStream(apiV1Path("ai/reply"), {
    method: "POST",
    body,
    signal: options?.signal,
    onChunk,
    onMeta: options?.onMeta
      ? (meta) => options.onMeta?.(meta as ChatContextMeta & Record<string, unknown>)
      : undefined,
  }).then((result) => {
    const assistantText = result.meta?.assistant_text;
    if (typeof assistantText === "string") {
      return assistantText;
    }
    return result.text;
  });
}

export function createHttpRepositories(): RepositoryBundle {
  return {
    posts: {
      list: () =>
        apiRequest<unknown>(apiV1Path("posts")).then((data) => postsListSchema.parse(data)),
      get: (id) =>
        apiRequest<unknown>(apiV1Path(`posts/${id}`)).then((data) => postSchema.parse(data)),
      create: (post) =>
        apiRequest<unknown>(apiV1Path("posts"), { method: "POST", body: post }).then((data) =>
          postSchema.parse(data),
        ),
      update: (id, patch) =>
        apiRequest<unknown>(apiV1Path(`posts/${id}`), {
          method: "PATCH",
          body: patch,
          signal: AbortSignal.timeout(120_000),
        }).then((data) => postSchema.parse(data)),
      reorder: (posts) =>
        apiRequest<unknown>(apiV1Path("posts/reorder"), {
          method: "PUT",
          body: { posts },
        }).then((data) => postsListSchema.parse(data)),
      remove: (id, options) =>
        apiRequest<void>(
          `${apiV1Path(`posts/${id}`)}${options?.permanent ? "?permanent=true" : ""}`,
          {
            method: "DELETE",
            signal: AbortSignal.timeout(120_000),
          },
        ),
      publish: (id) =>
        apiRequest<unknown>(apiV1Path(`posts/${id}/publish`), { method: "POST" }).then((data) =>
          postSchema.parse(data),
        ),
      schedule: (id, scheduledAt) =>
        apiRequest<unknown>(apiV1Path(`posts/${id}/schedule`), {
          method: "POST",
          body: { scheduledAt },
        }).then((data) => postSchema.parse(data)),
      syncComments: (id) =>
        apiRequest<unknown>(apiV1Path(`posts/${id}/sync-comments`), {
          method: "POST",
          signal: AbortSignal.timeout(120_000),
        }).then((data) => postSchema.parse(data)),
    },
    chats: {
      listGlobal: () =>
        apiRequest<unknown>(apiV1Path("global-chats")).then((data) =>
          globalChatsListSchema.parse(data),
        ),
      create: (chat) =>
        apiRequest<unknown>(apiV1Path("global-chats"), { method: "POST", body: chat }).then(
          (data) => globalChatSchema.parse(data),
        ),
      pushMessage: (chatId, text) =>
        apiRequest<unknown>(apiV1Path(`global-chats/${chatId}/messages`), {
          method: "POST",
          body: { text },
        }).then((data) => globalChatSchema.parse(data)),
      update: (chatId, patch) =>
        apiRequest<unknown>(apiV1Path(`global-chats/${chatId}`), {
          method: "PATCH",
          body: patch,
        }).then((data) => globalChatSchema.parse(data)),
      rename: (chatId, title) =>
        apiRequest<unknown>(apiV1Path(`global-chats/${chatId}`), {
          method: "PATCH",
          body: { title },
        }).then((data) => globalChatSchema.parse(data)),
      remove: (chatId) =>
        apiRequest<void>(apiV1Path(`global-chats/${chatId}`), { method: "DELETE" }),
    },
    notes: {
      listGlobal: () =>
        apiRequest<unknown>(apiV1Path("global-notes")).then((data) =>
          globalNotesListSchema.parse(data),
        ),
      upsert: (note) =>
        apiRequest<unknown>(apiV1Path(`global-notes/${note.id}`), {
          method: "PUT",
          body: note,
        }).then((data) => globalNoteSchema.parse(data)),
      remove: (noteId) =>
        apiRequest<void>(apiV1Path(`global-notes/${noteId}`), { method: "DELETE" }),
    },
    profile: {
      getChannel: () =>
        apiRequest<ChannelProfileConfig>(apiV1Path("profile/channel")).then(
          normalizeChannelProfileConfig,
        ),
      updateChannel: (config) =>
        apiRequest<ChannelProfileConfig>(apiV1Path("profile/channel"), {
          method: "PUT",
          body: config,
        }).then(normalizeChannelProfileConfig),
      getAi: () =>
        apiRequest<AiProfileConfig>(apiV1Path("profile/ai")).then(normalizeAiProfileConfigFromServer),
      updateAi: (config) =>
        apiRequest<AiProfileConfig>(apiV1Path("profile/ai"), {
          method: "PUT",
          body: config,
        }).then(normalizeAiProfileConfigFromServer),
      revealAiModelApiKey: (modelId, field) =>
        apiRequest<{ apiKey: string }>(apiV1Path("profile/ai/reveal-key"), {
          method: "POST",
          body: { modelId, field },
        }),
      getTelegram: () =>
        apiRequest<TelegramProfileConfig>(apiV1Path("profile/telegram")).then(
          normalizeTelegramProfileConfig,
        ),
      streamTelegramSync: (onMeta, signal) =>
        apiSseSubscribe(apiV1Path("profile/telegram/sync-events"), { onMeta, signal }),
      updateTelegram: (config) =>
        apiRequest<TelegramProfileConfig>(apiV1Path("profile/telegram"), {
          method: "PUT",
          body: config,
        }).then(normalizeTelegramProfileConfig),
      revealTelegramSecret: (field) =>
        apiRequest<{ value: string }>(apiV1Path("profile/telegram/reveal-secret"), {
          method: "POST",
          body: { field },
        }),
      sendTelegramCode: (phone) =>
        apiRequest<TelegramProfileConfig>(apiV1Path("telegram/auth/send-code"), {
          method: "POST",
          body: { phone },
        }).then(normalizeTelegramProfileConfig),
      verifyTelegramCode: (code) =>
        apiRequest<TelegramProfileConfig>(apiV1Path("telegram/auth/verify"), {
          method: "POST",
          body: { code },
        }).then(normalizeTelegramProfileConfig),
      verifyTelegram2fa: (password) =>
        apiRequest<TelegramProfileConfig>(apiV1Path("telegram/auth/verify-2fa"), {
          method: "POST",
          body: { password },
        }).then(normalizeTelegramProfileConfig),
      resetTelegramAuth: () =>
        apiRequest<TelegramProfileConfig>(apiV1Path("telegram/auth/reset"), {
          method: "POST",
        }).then(normalizeTelegramProfileConfig),
      connectTelegramChannel: (channel) =>
        apiRequest<TelegramProfileConfig>(apiV1Path("telegram/channel/connect"), {
          method: "POST",
          body: { channel },
        }).then(normalizeTelegramProfileConfig),
      reconcileTelegramChannel: () =>
        apiRequest<TelegramReconcileResponse>(apiV1Path("telegram/channel/reconcile"), {
          method: "POST",
        }),
    },
    assistant: {
      streamGlobalChatReply: (text, onChunk, options) =>
        streamAiReply("global", text, onChunk, options),
      streamPostChatReply: (text, onChunk, options) =>
        streamAiReply("post", text, onChunk, options),
      getGlobalChatReply: (text, options) =>
        streamAiReply("global", text, () => undefined, options),
      getPostChatReply: (text, options) =>
        streamAiReply("post", text, () => undefined, options),
    },
    analytics: {
      getPlatformModels: (period, points) =>
        apiRequest<unknown>(
          `${apiV1Path("analytics/platform-models")}?period=${period}&points=${points}`,
        ).then((data) => platformModelAnalyticsSchema.parse(data)),
      getChannelOverview: (period) =>
        apiRequest<unknown>(`${apiV1Path("analytics/overview")}?period=${period}`).then((data) =>
          channelAnalyticsOverviewSchema.parse(data),
        ),
      getChannelTopPosts: (period) =>
        apiRequest<unknown>(`${apiV1Path("analytics/top-posts")}?period=${period}`).then((data) =>
          channelAnalyticsTopPostsSchema.parse(data).posts,
        ),
    },
  };
}

export function createMswRepositories(): RepositoryBundle {
  return createHttpRepositories();
}
