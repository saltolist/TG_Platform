import { describe, expect, it } from "vitest";

import { applyNavigationPatch } from "./navigation-store";
import { initialNavigationState } from "./navigation/types";

describe("applyNavigationPatch", () => {
  it("clears isEditing when leaving post screen", () => {
    const state = { ...initialNavigationState, isEditing: true, currentPostId: "1" };
    const next = applyNavigationPatch(state, { screen: "feed" });
    expect(next.isEditing).toBe(false);
    expect(next).not.toHaveProperty("screen");
  });

  it("keeps isEditing when screen is post", () => {
    const state = { ...initialNavigationState, isEditing: true, currentPostId: "1" };
    const next = applyNavigationPatch(state, { screen: "post", currentPostId: "1" });
    expect(next.isEditing).toBe(true);
  });

  it("persists list filters from patch", () => {
    const next = applyNavigationPatch(initialNavigationState, {
      chatsTab: "global",
      noteScope: "local",
      feedSearch: "test",
    });
    expect(next.chatsTab).toBe("global");
    expect(next.noteScope).toBe("local");
    expect(next.feedSearch).toBe("test");
    expect(next.chatsSearch).toBe("");
  });

  it("does not store transient screen field", () => {
    const next = applyNavigationPatch(initialNavigationState, { screen: "analytics" });
    expect(next).not.toHaveProperty("screen");
  });
});
