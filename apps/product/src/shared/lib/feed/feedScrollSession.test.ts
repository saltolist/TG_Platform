import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("feedScrollSession", () => {
  beforeEach(() => {
    vi.resetModules();
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("persists scroll position in sessionStorage", async () => {
    const mod = await import("./feedScrollSession");
    mod.setFeedScrollTop(420);
    expect(sessionStorage.getItem("tg-platform-feed-scroll-top")).toBe("420");

    vi.resetModules();
    const reloaded = await import("./feedScrollSession");
    expect(reloaded.getFeedScrollTop()).toBe(420);
    expect(reloaded.getFeedSessionDidInitialScroll()).toBe(true);
  });

  it("clears stored scroll on reset", async () => {
    const mod = await import("./feedScrollSession");
    mod.setFeedScrollTop(120);
    mod.resetFeedScrollSession();
    expect(sessionStorage.getItem("tg-platform-feed-scroll-top")).toBeNull();
    expect(mod.getFeedScrollTop()).toBe(0);
    expect(mod.getFeedSessionDidInitialScroll()).toBe(false);
  });

  it("clamps scroll top to scrollable range", async () => {
    const { clampScrollTop } = await import("./feedScrollSession");
    expect(clampScrollTop(900, 1000, 400)).toBe(600);
    expect(clampScrollTop(50, 300, 400)).toBe(0);
  });
});
