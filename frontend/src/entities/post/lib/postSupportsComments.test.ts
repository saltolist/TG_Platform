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
} as Post;

describe("postSupportsComments", () => {
  it("hides when channel discussions are disabled", () => {
    expect(
      postSupportsComments(
        { ...publishedPost, commentsThreadAvailable: true },
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

  it("shows when thread is available", () => {
    expect(
      postSupportsComments(
        { ...publishedPost, commentsThreadAvailable: true },
        true,
      ),
    ).toBe(true);
  });

  it("shows when discussion root id is cached", () => {
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

  it("hides when not probed yet", () => {
    expect(postSupportsComments(publishedPost, true)).toBe(false);
  });
});
