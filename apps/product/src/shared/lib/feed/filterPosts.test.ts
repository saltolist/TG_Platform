import { describe, expect, it } from "vitest";

import {
  buildFeedPostSections,
  canSubmitFeedDraft,
  createDraftPost,
  postMatchesSearch,
} from "./filterPosts";
import type { Post } from "@/shared/types";

const basePost = (overrides: Partial<Post> = {}): Post => ({
  id: "1",
  status: "published",
  created: "2024-01-01",
  rubric: null,
  text: "Hello world",
  notes: [],
  chats: [],
  ...overrides,
});

describe("postMatchesSearch", () => {
  it("matches title and text case-insensitively", () => {
    expect(postMatchesSearch(basePost({ text: "Finance tips" }), "finance")).toBe(true);
    expect(postMatchesSearch(basePost({ text: "x" }), "missing")).toBe(false);
  });

  it("matches empty query", () => {
    expect(postMatchesSearch(basePost(), "")).toBe(true);
  });
});

describe("buildFeedPostSections", () => {
  it("splits posts by status and search", () => {
    const posts = [
      basePost({ id: "1", status: "published", text: "alpha" }),
      basePost({ id: "2", status: "draft", text: "beta draft" }),
      basePost({ id: "3", status: "scheduled", text: "gamma" }),
    ];
    const sections = buildFeedPostSections(posts, "beta");
    expect(sections.published).toHaveLength(0);
    expect(sections.drafts).toHaveLength(1);
    expect(sections.scheduled).toHaveLength(0);
  });
});

describe("createDraftPost", () => {
  it("creates draft with trimmed text", () => {
    const post = createDraftPost({ text: "  hello  ", id: "42" });
    expect(post.status).toBe("draft");
    expect(post.text).toBe("hello");
    expect(post.id).toBe("42");
  });
});

describe("canSubmitFeedDraft", () => {
  it("requires text or media", () => {
    expect(canSubmitFeedDraft("", 0)).toBe(false);
    expect(canSubmitFeedDraft("x", 0)).toBe(true);
    expect(canSubmitFeedDraft("", 1)).toBe(true);
  });
});
