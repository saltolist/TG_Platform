import {
  initialAiProfileConfig,
  initialChannelProfileConfig,
  initialGlobalChats,
  initialGlobalNotes,
  initialPosts,
  initialTelegramProfileConfig,
} from "@/shared/data/seed-data";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  GlobalChat,
  GlobalNote,
  Post,
  TelegramProfileConfig,
} from "@/shared/types";

export type MswStore = {
  posts: Post[];
  globalChats: GlobalChat[];
  globalNotes: GlobalNote[];
  channelProfile: ChannelProfileConfig;
  aiProfile: AiProfileConfig;
  telegramProfile: TelegramProfileConfig;
};

function cloneSeed<T>(value: T): T {
  return structuredClone(value);
}

/** Full demo account seed (`demo-full`): posts, notes, chats, profiles, connected @demochannel. */
export function createInitialMswStore(): MswStore {
  return {
    posts: cloneSeed(initialPosts),
    globalChats: cloneSeed(initialGlobalChats),
    globalNotes: cloneSeed(initialGlobalNotes),
    channelProfile: cloneSeed(initialChannelProfileConfig),
    aiProfile: cloneSeed(initialAiProfileConfig),
    telegramProfile: cloneSeed(initialTelegramProfileConfig),
  };
}

export const mswStore: MswStore = createInitialMswStore();

export function resetMswStore(): void {
  const fresh = createInitialMswStore();
  mswStore.posts = fresh.posts;
  mswStore.globalChats = fresh.globalChats;
  mswStore.globalNotes = fresh.globalNotes;
  mswStore.channelProfile = fresh.channelProfile;
  mswStore.aiProfile = fresh.aiProfile;
  mswStore.telegramProfile = fresh.telegramProfile;
  void import("./accountRegistry").then(({ resetAccountRegistry }) => resetAccountRegistry());
}
