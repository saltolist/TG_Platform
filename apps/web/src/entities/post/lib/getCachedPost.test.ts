import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/shared/api/queryKeys";
import type { Post } from "@/shared/types";

import { getCachedPost, setCachedPost } from "./getCachedPost";

const TEST_ACCOUNT_ID = "test-account";

vi.mock("@/shared/lib/auth/queryAccountScope", () => ({
  getQueryAccountIdFromAuth: () => TEST_ACCOUNT_ID,
}));

const post: Post = {
  id: "1",
  text: "Hello",
  status: "draft",
  date: "сегодня",
  rubric: null,
  media: [],
  chats: [],
  notes: [],
};

describe("getCachedPost", () => {
  it("reads from list cache", () => {
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.posts.list(TEST_ACCOUNT_ID), [post]);
    expect(getCachedPost(qc, "1")).toEqual(post);
  });

  it("falls back to detail cache when list is empty", () => {
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.posts.detail(TEST_ACCOUNT_ID, "1"), post);
    expect(getCachedPost(qc, "1")).toEqual(post);
  });

  it("returns undefined when post is missing", () => {
    const qc = new QueryClient();
    expect(getCachedPost(qc, "1")).toBeUndefined();
  });
});

describe("setCachedPost", () => {
  it("updates detail and list caches", () => {
    const qc = new QueryClient();
    const updated = { ...post, text: "Updated" };
    qc.setQueryData(queryKeys.posts.list(TEST_ACCOUNT_ID), [post]);
    qc.setQueryData(queryKeys.posts.detail(TEST_ACCOUNT_ID, "1"), post);

    setCachedPost(qc, updated);

    expect(qc.getQueryData(queryKeys.posts.detail(TEST_ACCOUNT_ID, "1"))).toEqual(updated);
    expect(qc.getQueryData<Post[]>(queryKeys.posts.list(TEST_ACCOUNT_ID))?.[0]).toEqual(updated);
  });
});
