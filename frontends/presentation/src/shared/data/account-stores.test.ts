import { describe, expect, it } from "vitest";

import { DEMO_CHANNEL_HANDLE, DEMO_CHANNEL_TITLE } from "@/shared/lib/auth/constants";
import { demoKanalPosts } from "@/shared/data/channel-pools/demo-kanal-posts";
import { importDemoKanalContent } from "@/shared/data/channel-pools/demo-kanal-content";
import { createEmptyAccountStore } from "@/shared/data/empty-account-state";
import {
  initialAiProfileConfig,
  initialChannelProfileConfig,
  initialGlobalChats,
  initialGlobalNotes,
  initialPosts,
  initialTelegramProfileConfig,
} from "@/shared/data/seed-data";
import { createInitialMswStore } from "@/shared/api/msw/store";

describe("createInitialMswStore (demo-full)", () => {
  const store = createInitialMswStore();

  it("includes full feed and knowledge base", () => {
    expect(store.posts.length).toBe(initialPosts.length);
    expect(store.globalChats.length).toBe(initialGlobalChats.length);
    expect(store.globalNotes.length).toBe(initialGlobalNotes.length);
    expect(store.posts.some((p) => p.notes.length > 0)).toBe(true);
  });

  it("includes filled profiles and connected @demochannel", () => {
    expect(store.channelProfile.core.topic.length).toBeGreaterThan(0);
    expect(store.aiProfile.llmModels.length).toBeGreaterThan(0);
    expect(store.telegramProfile.phone).toBe("+7 999 123-45-67");
    expect(store.telegramProfile.apiId).toBe("20483651");
    expect(store.telegramProfile.apiHash.length).toBeGreaterThan(0);
    expect(store.telegramProfile.channel).toBe(DEMO_CHANNEL_HANDLE);
    expect(store.telegramProfile.channelTitle).toBe(DEMO_CHANNEL_TITLE);
    expect(store.telegramProfile.channelStatus).toBe("connected");
    expect(store.telegramProfile.authStatus).toBe("connected");
  });
});

describe("createEmptyAccountStore (fresh)", () => {
  const store = createEmptyAccountStore();

  it("starts empty except prefilled channel handle", () => {
    expect(store.posts).toEqual([]);
    expect(store.globalChats).toEqual([]);
    expect(store.globalNotes).toEqual([]);
    expect(store.channelProfile.core.topic).toBe("");
    expect(store.aiProfile.llmModels).toEqual([]);
    expect(store.telegramProfile.channel).toBe(DEMO_CHANNEL_HANDLE);
    expect(store.telegramProfile.channelTitle).toBe("");
    expect(store.telegramProfile.channelStatus).toBe("idle");
    expect(store.telegramProfile.authStatus).toBe("idle");
    expect(store.telegramProfile.authStep).toBe("credentials");
  });
});

describe("importDemoKanalContent", () => {
  it("imports channel posts and leaves knowledge base untouched", () => {
    const store = createEmptyAccountStore();
    store.globalNotes.push({
      id: "user-note",
      title: "My note",
      ai: false,
      date: "today",
      body: "stay",
    });
    store.channelProfile = { ...initialChannelProfileConfig };

    const count = importDemoKanalContent(store);

    expect(count).toBe(demoKanalPosts.length);
    expect(store.posts).toEqual(structuredClone(demoKanalPosts));
    expect(store.posts.some((p) => (p.comments?.length ?? 0) > 0)).toBe(true);
    expect(store.globalNotes).toHaveLength(1);
    expect(store.globalChats).toHaveLength(0);
    expect(store.channelProfile.core.topic).toBe(initialChannelProfileConfig.core.topic);
    expect(store.aiProfile).toEqual(createEmptyAccountStore().aiProfile);
  });
});
