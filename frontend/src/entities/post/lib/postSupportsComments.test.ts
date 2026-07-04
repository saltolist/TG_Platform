import { describe, expect, it } from "vitest";

import type { Post } from "@/shared/types";

import { postSupportsComments } from "./postSupportsComments";

const publishedPost = {
  id: "1",
  status: "published",
  text: "x",
  rubric: null,
  notes: [],
  chats: [],
  telegramMessageId: "501",
  date: new Date().toISOString(),
} as Post;

describe("postSupportsComments", () => {
  it("hides when channel discussions are disabled", () => {
    expect(
      postSupportsComments(
        { ...publishedPost, commentsThreadAvailable: true, telegramDiscussionMessageId: "9001" },
        false,
      ),
    ).toBe(false);
  });

  it("hides when post thread was probed as unavailable", () => {
    expect(
      postSupportsComments(
        { ...publishedPost, commentsThreadAvailable: false },
        true,
      ),
    ).toBe(false);
  });

  it("shows live optimistic flag for a fresh live-synced post", () => {
    expect(
      postSupportsComments(
        {
          ...publishedPost,
          commentsThreadAvailable: true,
          commentsThreadLiveOptimistic: true,
        },
        true,
      ),
    ).toBe(true);
  });

  it("shows a recent telegram post before per-post flags are persisted", () => {
    expect(
      postSupportsComments(
        { ...publishedPost },
        true,
      ),
    ).toBe(true);
  });

  it("hides stale optimistic flag on an old post", () => {
    expect(
      postSupportsComments(
        {
          ...publishedPost,
          date: "2020-01-01T00:00:00.000Z",
          commentsThreadAvailable: true,
        },
        true,
      ),
    ).toBe(false);
  });

  it("hides unprobed historical posts without a thread flag", () => {
    expect(
      postSupportsComments(
        { ...publishedPost, date: "2020-01-01T00:00:00.000Z" },
        true,
      ),
    ).toBe(false);
  });

  it("hides when discussion root equals the channel post id", () => {
    expect(
      postSupportsComments(
        {
          ...publishedPost,
          commentsThreadAvailable: true,
          commentsThreadLiveOptimistic: true,
          telegramDiscussionMessageId: "501",
        },
        true,
      ),
    ).toBe(false);
  });

  it("shows when a real discussion root id is cached", () => {
    expect(
      postSupportsComments(
        {
          ...publishedPost,
          date: "2020-01-01T00:00:00.000Z",
          telegramDiscussionMessageId: "9001",
        },
        true,
      ),
    ).toBe(true);
  });
});
