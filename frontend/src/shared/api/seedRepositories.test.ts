import { describe, expect, it } from "vitest";
import { createSeedRepositories } from "@/shared/api/seedRepositories";
import { initialPosts } from "@/shared/data/seed-data";

describe("seedRepositories", () => {
  it("lists posts from seed", async () => {
    const repos = createSeedRepositories();
    const posts = await repos.posts.list();
    expect(posts.length).toBeGreaterThan(0);
    expect(posts[0].id).toBe(initialPosts[0].id);
  });

  it("creates a post", async () => {
    const repos = createSeedRepositories();
    const created = await repos.posts.create({
      ...initialPosts[0],
      id: "9999",
      text: "test",
      status: "draft",
      rubric: null,
      notes: [],
      chats: [],
    });
    expect(created.id).toBe("9999");
    const list = await repos.posts.list();
    expect(list.some((p) => p.id === "9999")).toBe(true);
  });
});
