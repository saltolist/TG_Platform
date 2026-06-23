import type { RepositoryBundle, GlobalChatPatch } from "@/shared/api/repositories";
import {
  initialAiProfileConfig,
  initialChannelProfileConfig,
  initialGlobalChats,
  initialGlobalNotes,
  initialPosts,
  initialTelegramProfileConfig,
} from "@/shared/data/seed-data";
import { appendToActiveHistory } from "@/shared/lib/chatPaths";
import { getGlobalReply, getPostReply } from "@/shared/api/assistantReplies";
import { simulateStreamedText } from "@/shared/api/sse";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";
import type { AiModelListField } from "@/shared/lib/profile/aiModelListField";

export function createSeedRepositories(): RepositoryBundle {
  let posts = [...initialPosts];
  let globalChats = [...initialGlobalChats];
  let globalNotes = [...initialGlobalNotes];
  let channelProfile: ChannelProfileConfig = structuredClone(initialChannelProfileConfig);
  let aiProfile: AiProfileConfig = structuredClone(initialAiProfileConfig);
  let telegramProfile: TelegramProfileConfig = structuredClone(initialTelegramProfileConfig);

  return {
    posts: {
      async list() {
        return posts;
      },
      async create(post) {
        posts = [post, ...posts.filter((p) => p.id !== post.id)];
        return post;
      },
      async update(id, patch) {
        const idx = posts.findIndex((p) => p.id === id);
        if (idx < 0) throw new Error(`Post ${id} not found`);
        posts[idx] = { ...posts[idx], ...patch };
        return posts[idx];
      },
      async reorder(nextPosts) {
        posts = [...nextPosts];
        return posts;
      },
      async remove(id) {
        posts = posts.filter((p) => p.id !== id);
      },
    },
    chats: {
      async listGlobal() {
        return globalChats;
      },
      async create(chat) {
        globalChats = [chat, ...globalChats.filter((c) => c.id !== chat.id)];
        return chat;
      },
      async pushMessage(chatId, text) {
        const chat = globalChats.find((c) => c.id === chatId);
        if (!chat) throw new Error(`Chat ${chatId} not found`);
        const aiText = getGlobalReply(text);
        let history = appendToActiveHistory(chat.history, { role: "user", text });
        history = appendToActiveHistory(history, {
          role: "ai",
          text: aiText,
          llmLabel: "OpenAI / gpt-4o",
          webLabel: "Perplexity / search-api",
        });
        const updated: GlobalChat = {
          ...chat,
          history,
          preview: aiText.slice(0, 80),
          date: new Date().toISOString(),
        };
        globalChats = globalChats.map((c) => (c.id === chatId ? updated : c));
        return updated;
      },
      async update(chatId, patch: GlobalChatPatch) {
        const chat = globalChats.find((c) => c.id === chatId);
        if (!chat) throw new Error(`Chat ${chatId} not found`);
        const updated = { ...chat, ...patch };
        globalChats = globalChats.map((c) => (c.id === chatId ? updated : c));
        return updated;
      },
      async rename(chatId, title) {
        const chat = globalChats.find((c) => c.id === chatId);
        if (!chat) throw new Error(`Chat ${chatId} not found`);
        const updated = { ...chat, title };
        globalChats = globalChats.map((c) => (c.id === chatId ? updated : c));
        return updated;
      },
      async remove(chatId) {
        globalChats = globalChats.filter((c) => c.id !== chatId);
      },
    },
    notes: {
      async listGlobal() {
        return globalNotes;
      },
      async upsert(note) {
        const exists = globalNotes.some((n) => n.id === note.id);
        globalNotes = exists
          ? globalNotes.map((n) => (n.id === note.id ? note : n))
          : [note, ...globalNotes];
        return note;
      },
      async remove(noteId) {
        globalNotes = globalNotes.filter((n) => n.id !== noteId);
      },
    },
    profile: {
      async getChannel() {
        return channelProfile;
      },
      async updateChannel(config) {
        channelProfile = config;
        return channelProfile;
      },
      async getAi() {
        return aiProfile;
      },
      async updateAi(config) {
        aiProfile = config;
        return aiProfile;
      },
      async revealAiModelApiKey(modelId, field) {
        const models = aiProfile[field] as Array<{ id: string; apiKey: string }>;
        const model = models.find((entry) => entry.id === modelId);
        if (!model?.apiKey) throw new Error(`API key not found for model ${modelId}`);
        return { apiKey: model.apiKey };
      },
      async getTelegram() {
        return telegramProfile;
      },
      async updateTelegram(config) {
        telegramProfile = config;
        return telegramProfile;
      },
      async revealTelegramSecret(field) {
        const value = (telegramProfile as Record<string, unknown>)[field];
        if (!value || typeof value !== "string") throw new Error(`Secret not found: ${field}`);
        return { value };
      },
    },
    assistant: {
      async streamGlobalChatReply(text, onChunk, options) {
        void options;
        return simulateStreamedText(getGlobalReply(text), onChunk);
      },
      async streamPostChatReply(text, onChunk, options) {
        void options;
        return simulateStreamedText(getPostReply(text), onChunk);
      },
      async getGlobalChatReply(text, options) {
        return this.streamGlobalChatReply(text, () => undefined, options);
      },
      async getPostChatReply(text, options) {
        return this.streamPostChatReply(text, () => undefined, options);
      },
    },
  };
}
