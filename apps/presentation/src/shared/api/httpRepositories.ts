import { apiV1Path } from "@/shared/config/basePath";
import { apiRequest } from "@/shared/api/httpClient";
import type { RepositoryBundle } from "@/shared/api/repositories";
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
      getGlobalChatReply: (text) =>
        apiRequest<{ text: string }>(apiV1Path("ai/reply"), {
          method: "POST",
          body: { text, scope: "global" },
        }).then((r) => r.text),
      getPostChatReply: (text) =>
        apiRequest<{ text: string }>(apiV1Path("ai/reply"), {
          method: "POST",
          body: { text, scope: "post" },
        }).then((r) => r.text),
    },
  };
}

export function createMswRepositories(): RepositoryBundle {
  return createHttpRepositories();
}
