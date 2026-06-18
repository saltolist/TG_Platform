import { apiV1Path } from "@/shared/config/basePath";
import { apiRequest, apiStream } from "@/shared/api/httpClient";
import type { AssistantStreamOptions, RepositoryBundle } from "@/shared/api/repositories";
import {
  globalChatsListSchema,
  globalChatSchema,
  globalNotesListSchema,
  globalNoteSchema,
  postsListSchema,
  postSchema,
} from "@/shared/api/schemas";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";

function streamAiReply(
  scope: "global" | "post",
  text: string,
  onChunk: (chunk: string) => void,
  options?: AssistantStreamOptions,
) {
  const body: Record<string, string> = { text, scope };
  if (options?.llmId) body.llmId = options.llmId;
  return apiStream(apiV1Path("ai/reply"), {
    method: "POST",
    body,
    signal: options?.signal,
    onChunk,
  });
}

export function createHttpRepositories(): RepositoryBundle {
  return {
    posts: {
      list: () =>
        apiRequest<unknown>(apiV1Path("posts")).then((data) => postsListSchema.parse(data)),
      create: (post) =>
        apiRequest<unknown>(apiV1Path("posts"), { method: "POST", body: post }).then((data) =>
          postSchema.parse(data),
        ),
      update: (id, patch) =>
        apiRequest<unknown>(apiV1Path(`posts/${id}`), { method: "PATCH", body: patch }).then(
          (data) => postSchema.parse(data),
        ),
      reorder: (posts) =>
        apiRequest<unknown>(apiV1Path("posts/reorder"), {
          method: "PUT",
          body: { posts },
        }).then((data) => postsListSchema.parse(data)),
      remove: (id) => apiRequest<void>(apiV1Path(`posts/${id}`), { method: "DELETE" }),
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
      getChannel: () => apiRequest<ChannelProfileConfig>(apiV1Path("profile/channel")),
      updateChannel: (config) =>
        apiRequest<ChannelProfileConfig>(apiV1Path("profile/channel"), {
          method: "PUT",
          body: config,
        }),
      getAi: () => apiRequest<AiProfileConfig>(apiV1Path("profile/ai")),
      updateAi: (config) =>
        apiRequest<AiProfileConfig>(apiV1Path("profile/ai"), {
          method: "PUT",
          body: config,
        }),
      getTelegram: () => apiRequest<TelegramProfileConfig>(apiV1Path("profile/telegram")),
      updateTelegram: (config) =>
        apiRequest<TelegramProfileConfig>(apiV1Path("profile/telegram"), {
          method: "PUT",
          body: config,
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
  };
}

export function createMswRepositories(): RepositoryBundle {
  return createHttpRepositories();
}
