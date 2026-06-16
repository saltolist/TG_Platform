import { describe, expect, it } from "vitest";

import { createPresentationMswStore, PRESENTATION_POST_IDS } from "./presentation-seed";

describe("createPresentationMswStore", () => {
  const store = createPresentationMswStore();

  it("includes demo LLM and web search models for guests", () => {
    expect(store.aiProfile.llmModels.map((m) => `${m.provider}/${m.model}`)).toEqual([
      "OpenAI/gpt-4o",
      "Anthropic/claude-3-7-sonnet",
    ]);
    expect(store.aiProfile.webSearchModels.map((m) => `${m.provider}/${m.model}`)).toEqual([
      "Tavily/search-v1",
      "Exa/exa-neural",
      "OpenAI/responses-api-web-search",
    ]);
  });

  it("seeds published, scheduled and draft posts with media layout", () => {
    expect(PRESENTATION_POST_IDS).toHaveLength(9);

    const published = store.posts.filter((p) => p.status === "published");
    const scheduled = store.posts.filter((p) => p.status === "scheduled");
    const drafts = store.posts.filter((p) => p.status === "draft");

    expect(published).toHaveLength(4);
    expect(scheduled).toHaveLength(2);
    expect(drafts).toHaveLength(3);

    expect(published.map((p) => p.media?.length ?? 0)).toEqual([1, 2, 2, 2]);
    expect(scheduled.every((p) => (p.media?.length ?? 0) > 0)).toBe(true);
    expect(store.posts.every((p) => (p.media?.length ?? 0) <= 2)).toBe(true);
    expect(drafts[0].media?.length).toBe(1);
    expect(drafts[1].media?.length).toBe(2);
    expect(drafts[2].media).toBeUndefined();

    const dayKey = (raw: string) => {
      const d = new Date(raw);
      return Number.isFinite(d.getTime()) ? d.toISOString().slice(0, 10) : raw;
    };

    const publishedDays = new Set(published.map((p) => dayKey(p.date ?? "")));
    expect(publishedDays.size).toBe(3);

    const scheduledDays = new Set(scheduled.map((p) => dayKey(p.date ?? "")));
    expect(scheduledDays.size).toBe(2);
  });
});
