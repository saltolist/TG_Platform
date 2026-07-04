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

  it("hides optimistic flag without a confirmed discussion root", () => {
    expect(
      postSupportsComments(
        { ...publishedPost, commentsThreadAvailable: true },
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
          telegramDiscussionMessageId: "9001",
        },
        true,
      ),
    ).toBe(true);
  });

  it("hides when not linked to telegram", () => {
    expect(postSupportsComments(publishedPost, true)).toBe(false);
  });
});
