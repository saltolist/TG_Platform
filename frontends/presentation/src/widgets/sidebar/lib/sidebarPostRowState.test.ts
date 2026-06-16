import { describe, expect, it } from "vitest";

import {
  isSidebarPostFullActive,
  isSidebarPostSubActive,
  resolveSidebarPostId,
  shouldShowFeedPostRow,
} from "@/widgets/sidebar/lib/sidebarPostRowState";

describe("sidebarPostRowState", () => {
  it("resolves post id from post and note routes", () => {
    expect(resolveSidebarPostId("post", "3", null)).toBe("3");
    expect(resolveSidebarPostId("note", null, "3")).toBe("3");
    expect(resolveSidebarPostId("feed", "3", "3")).toBeNull();
  });

  it("shows feed post row for post screen and post notes", () => {
    expect(shouldShowFeedPostRow("3", "post", null)).toBe(true);
    expect(shouldShowFeedPostRow("3", "note", "3")).toBe(true);
    expect(shouldShowFeedPostRow(null, "note", "3")).toBe(false);
  });

  it("marks full active post row without chat query", () => {
    expect(
      isSidebarPostFullActive("3", "post", { postId: "3", notePostId: null, postChatId: null }),
    ).toBe(true);
    expect(
      isSidebarPostFullActive("3", "post", { postId: "3", notePostId: null, postChatId: "12" }),
    ).toBe(false);
  });

  it("marks sub-active for post chat and post note routes", () => {
    expect(
      isSidebarPostSubActive("3", "post", { postId: "3", notePostId: null, postChatId: "12" }),
    ).toBe(true);
    expect(
      isSidebarPostSubActive("3", "note", { postId: null, notePostId: "3", postChatId: null }),
    ).toBe(true);
    expect(
      isSidebarPostSubActive("3", "post", { postId: "3", notePostId: null, postChatId: null }),
    ).toBe(false);
  });
});
