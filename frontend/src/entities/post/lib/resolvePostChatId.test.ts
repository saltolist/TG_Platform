import { describe, expect, it } from "vitest";
import type { QueryClient } from "@tanstack/react-query";

import {
  activePostChatIdFromPost,
  composerPostChatId,
  displayPostChatId,
  resolvePostChatId,
} from "./resolvePostChatId";
import type { Post } from "@/shared/types";

const post: Post = {
  id: "p1",
  status: "draft",
  rubric: null,
  text: "Post",
  notes: [],
  chats: [
    {
      id: "c-old",
      title: "Old",
      preview: "Hi",
      date: "2026-01-01T00:00:00.000Z",
      ai: true,
      history: [],
    },
  ],
};

const queryClient = {
  getQueryData: () => [post],
} as unknown as QueryClient;

describe("composerPostChatId", () => {
  it("returns null on post root without chat query", () => {
    expect(
      composerPostChatId({
        postId: "p1",
        chatFromUrl: null,
        pendingNew: false,
        queryClient,
      }),
    ).toBeNull();
  });

  it("returns null when pending new chat", () => {
    expect(
      composerPostChatId({
        postId: "p1",
        chatFromUrl: "c-old",
        pendingNew: true,
        queryClient,
      }),
    ).toBeNull();
  });

  it("returns chat id from URL when present", () => {
    expect(
      composerPostChatId({
        postId: "p1",
        chatFromUrl: "c-old",
        pendingNew: false,
        queryClient,
      }),
    ).toBe("c-old");
  });
});

describe("displayPostChatId", () => {
  it("hides chat while pending new chat even with URL param", () => {
    expect(
      displayPostChatId({
        chatFromUrl: "c-old",
        post,
        pendingNew: true,
      }),
    ).toBeNull();
  });
});

describe("activePostChatIdFromPost", () => {
  it("hides stale store chat when URL has no chat param", () => {
    expect(activePostChatIdFromPost(null, post)).toBeNull();
    expect(activePostChatIdFromPost("c-old", post)).toBe("c-old");
    expect(activePostChatIdFromPost("missing", post)).toBeNull();
  });
});

describe("resolvePostChatId", () => {
  it("drops unknown chat ids when post is cached", () => {
    expect(resolvePostChatId(queryClient, "p1", "missing")).toBeNull();
  });
});
