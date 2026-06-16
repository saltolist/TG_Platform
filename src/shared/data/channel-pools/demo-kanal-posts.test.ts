import { describe, expect, it } from "vitest";

import { initialPosts } from "@/shared/data/seed-data";
import { demoKanalPosts } from "@/shared/data/channel-pools/demo-kanal-posts";

describe("demoKanalPosts", () => {
  it("is a channel-only feed without workspace data", () => {
    expect(demoKanalPosts.length).toBeGreaterThanOrEqual(3);
    expect(demoKanalPosts.every((p) => p.notes.length === 0)).toBe(true);
    expect(demoKanalPosts.every((p) => p.chats.length === 0)).toBe(true);
    expect(demoKanalPosts.some((p) => (p.comments?.length ?? 0) > 0)).toBe(true);
  });

  it("is independent from demo-full seed workspace overlays", () => {
    const demoFullPost1 = initialPosts.find((p) => p.id === "1");
    const channelPost1 = demoKanalPosts.find((p) => p.id === "1");

    expect(demoFullPost1?.notes.length).toBeGreaterThan(0);
    expect(demoFullPost1?.chats.length).toBeGreaterThan(0);
    expect(channelPost1?.text).toBe(demoFullPost1?.text);
    expect(channelPost1?.notes).toEqual([]);
    expect(channelPost1?.chats).toEqual([]);
  });
});
