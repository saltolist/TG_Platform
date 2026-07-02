import { describe, expect, it } from "vitest";

import type { PostComment } from "@/shared/types";

import { isPostCommentTelegramPending } from "./isPostCommentTelegramPending";

const comment = {
  id: "1",
  author: "Вы",
  text: "hello",
  date: "2026-01-01T00:00:00Z",
} as PostComment;

describe("isPostCommentTelegramPending", () => {
  it("is pending for linked posts without telegramMessageId", () => {
    expect(isPostCommentTelegramPending(comment, true)).toBe(true);
  });

  it("is not pending after telegram sync", () => {
    expect(
      isPostCommentTelegramPending({ ...comment, telegramMessageId: "7000" }, true),
    ).toBe(false);
  });

  it("is not pending for local-only posts", () => {
    expect(isPostCommentTelegramPending(comment, false)).toBe(false);
  });
});
