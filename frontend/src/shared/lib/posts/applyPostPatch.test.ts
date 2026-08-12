import { describe, expect, it } from "vitest";

import { applyPostPatch } from "./applyPostPatch";
import type { Post } from "@/shared/types";

const basePost = (): Post => ({
  id: "1",
  status: "draft",
  rubric: null,
  text: "hello",
  textHtml: "<strong>hello</strong>",
  notes: [],
  chats: [],
});

describe("applyPostPatch", () => {
  it("clears textHtml when patch sends null", () => {
    const next = applyPostPatch(basePost(), { textHtml: null });
    expect(next.textHtml).toBeUndefined();
  });

  it("replaces textHtml when patch sends formatted html", () => {
    const next = applyPostPatch(basePost(), {
      textHtml: "<em>hello</em>",
    });
    expect(next.textHtml).toBe("<em>hello</em>");
  });

  it("clears media when patch sends an empty array", () => {
    const next = applyPostPatch(
      {
        ...basePost(),
        media: [{ name: "a.jpg", url: "/a.jpg", type: "image/jpeg" }],
      },
      { media: [] },
    );
    expect(next.media).toEqual([]);
  });
});
