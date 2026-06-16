import { describe, expect, it } from "vitest";
import { postStatusSchema } from "@/shared/api/schemas/post";
import { getGlobalReply, getPostReply } from "@/shared/api/assistantReplies";
import { buildDraftDisplayList } from "@/shared/lib/drafts/draftDnDUtils";
import { recordAppNavigation, resetAppNavStackForTests } from "@/shared/lib/appNavStack";
import { resolveScreenBackAction } from "@/shared/lib/hooks/useScreenBack";

function withSessionStorageMock(run: () => void) {
  const data = new Map<string, string>();
  const storage = {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  };
  Object.defineProperty(globalThis, "sessionStorage", {
    value: storage,
    configurable: true,
  });
  try {
    run();
  } finally {
    Reflect.deleteProperty(globalThis, "sessionStorage");
  }
}
import { ensureVisibleInScrollParent } from "@/shared/lib/scrollIntoParent";
import {
  parseAppPath,
  parseGChatLegacyPath,
  parsePostLegacySub,
  getParentPath,
  statePatchToHref,
  routes,
} from "@/shared/lib/routes";

describe("routes", () => {
  it("parses feed path", () => {
    expect(parseAppPath("/feed/").screen).toBe("feed");
  });

  it("parses post path", () => {
    const parsed = parseAppPath("/post/1/");
    expect(parsed.screen).toBe("post");
    expect(parsed.postId).toBe("1");
  });

  it("parses gchat path", () => {
    expect(parseAppPath("/gchat/").screen).toBe("gchat");
  });

  it("parses note global path", () => {
    const parsed = parseAppPath("/note/global/gn1/");
    expect(parsed.screen).toBe("note");
    expect(parsed.noteGlobalId).toBe("gn1");
  });

  it("builds gchat href", () => {
    expect(routes.gchat("gc1")).toBe("/gchat/?id=gc1");
  });

  it("parsePostLegacySub", () => {
    expect(parsePostLegacySub("/post/5/notes/")).toEqual({ postId: "5", mode: "notes" });
    expect(parsePostLegacySub("/post/new/notes/")).toBeNull();
  });

  it("parseGChatLegacyPath", () => {
    expect(parseGChatLegacyPath("/gchat/gc1/")).toBe("gc1");
    expect(parseGChatLegacyPath("/gchat/")).toBeNull();
  });

  it("getParentPath for post", () => {
    expect(getParentPath("/post/1/")).toBe("/feed/");
    expect(getParentPath("/post/new/")).toBe("/feed/");
  });

  it("statePatchToHref for post without id goes to feed", () => {
    expect(
      statePatchToHref(
        { screen: "post", currentPostId: null },
        { screen: "feed", currentPostId: null, postMode: "chat" },
      ),
    ).toBe("/feed/");
  });

  it("resolveScreenBackAction prefers in-app visit stack", () => {
    withSessionStorageMock(() => {
      resetAppNavStackForTests();
      recordAppNavigation("/feed/", new URLSearchParams());
      recordAppNavigation("/post/1/", new URLSearchParams());
      expect(resolveScreenBackAction("/post/1/", new URLSearchParams())).toEqual({ type: "back" });
    });
  });

  it("resolveScreenBackAction prefers in-app visit stack for profile", () => {
    withSessionStorageMock(() => {
      resetAppNavStackForTests();
      recordAppNavigation("/notes/", new URLSearchParams());
      recordAppNavigation("/profile/", new URLSearchParams());
      expect(resolveScreenBackAction("/profile/", new URLSearchParams())).toEqual({ type: "back" });
    });
  });

  it("resolveScreenBackAction falls back to parent path", () => {
    withSessionStorageMock(() => {
      resetAppNavStackForTests();
      expect(resolveScreenBackAction("/post/1/", new URLSearchParams())).toEqual({
        type: "push",
        href: "/feed/",
      });
      expect(resolveScreenBackAction("/", new URLSearchParams())).toEqual({ type: "push", href: "/" });
    });
  });

  it("statePatchToHref for gchat", () => {
    expect(
      statePatchToHref({ screen: "gchat", gchatId: "gc1" }, { screen: "chats", currentPostId: null, postMode: "chat" }),
    ).toBe("/gchat/?id=gc1");
  });
});

describe("buildDraftDisplayList", () => {
  const drafts = [
    { id: "1", status: "draft" as const, text: "a", date: "2024-01-01", rubric: null, notes: [], chats: [] },
    { id: "2", status: "draft" as const, text: "b", date: "2024-01-02", rubric: null, notes: [], chats: [] },
  ];

  it("returns cards when not dragging", () => {
    expect(buildDraftDisplayList(drafts, null, null)).toEqual([
      { kind: "card", post: drafts[0] },
      { kind: "card", post: drafts[1] },
    ]);
  });

  it("inserts gap when dragging", () => {
    const items = buildDraftDisplayList(drafts, "1", "2");
    expect(items.some((i) => i.kind === "gap")).toBe(true);
    expect(items.filter((i) => i.kind === "card").map((i) => i.post.id)).toEqual(["2"]);
  });
});

describe("ensureVisibleInScrollParent", () => {
  it("scrolls down when element extends below parent", () => {
    const scrollParent = {
      scrollTop: 0,
      getBoundingClientRect: () => ({ top: 100, bottom: 200, left: 0, right: 0, width: 0, height: 100, x: 0, y: 100, toJSON: () => ({}) }),
    } as unknown as HTMLElement;
    const element = {
      getBoundingClientRect: () => ({ top: 150, bottom: 220, left: 0, right: 0, width: 0, height: 70, x: 0, y: 150, toJSON: () => ({}) }),
    } as unknown as HTMLElement;

    ensureVisibleInScrollParent(element, scrollParent);
    expect(scrollParent.scrollTop).toBe(28);
  });
});

describe("replies", () => {
  it("returns global reply for keyword", () => {
    expect(getGlobalReply("контент-план на неделю")).toContain("контент-план");
  });

  it("returns post reply for rewrite", () => {
    expect(getPostReply("перепиши вступление")).toContain("переработанная");
  });
});

describe("postStatusSchema", () => {
  it("accepts valid status", () => {
    expect(postStatusSchema.parse("draft")).toBe("draft");
  });
});
