import { describe, expect, it } from "vitest";

import type { GlobalChat, GlobalNote, Post, PostMode } from "@/shared/types";
import type { ActiveNote } from "@/shared/types";
import {
  isNoteRouteDataQuery,
  mergeNoteCachePatch,
  routeNeedsCachedData,
  routeSyncKey,
  syncPostModeFromRoute,
  syncRouteFromUrl,
} from "@/widgets/app-shell/lib/syncRoute";
import { queryKeys } from "@/shared/api/queryKeys";
import { EMPTY_NOTE_SNAPSHOT } from "@/shared/lib/noteDraft";

const posts: Post[] = [
  {
    id: "1",
    status: "published",
    date: "2024-01-01",
    rubric: null,
    text: "Post 1",
    notes: [{ id: "10", title: "Note 10", date: "2024-01-01", ai: false, body: "" }],
    chats: [],
  },
];

const globalNotes: GlobalNote[] = [
  { id: "gn1", title: "Global note", ai: false, date: "2024-01-01", body: "" },
];

const globalChats: GlobalChat[] = [
  { id: "gc1", title: "Chat", preview: "Hi", date: "2024-01-01", history: [] },
];

const data = { posts, globalChats, globalNotes };

describe("syncPostModeFromRoute", () => {
  it("skips setMode when route mode already matches store", () => {
    let setModeCalls = 0;
    const store = {
      getMode: () => "comments" as const,
      getCurrentPostChatId: () => null,
      setMode: () => {
        setModeCalls += 1;
      },
    };

    syncPostModeFromRoute(store, { postId: "1", mode: "comments", chatId: null });
    expect(setModeCalls).toBe(0);
  });

  it("calls setMode when route mode differs", () => {
    let last: { postId: string; mode: PostMode; chatId: string | null } | null = null;
    const store = {
      getMode: () => "chat" as const,
      getCurrentPostChatId: () => null,
      setMode: (postId: string, mode: PostMode, chatId?: string | null) => {
        last = { postId, mode, chatId: chatId ?? null };
      },
    };

    syncPostModeFromRoute(store, { postId: "1", mode: "comments", chatId: null });
    expect(last).toEqual({ postId: "1", mode: "comments", chatId: null });
  });
});

describe("syncRouteFromUrl", () => {
  it("redirects legacy gchat path", () => {
    const result = syncRouteFromUrl("/gchat/gc1/", new URLSearchParams(), data);
    expect(result).toEqual({ kind: "redirect", href: "/gchat/?id=gc1" });
  });

  it("redirects /post/new/ to feed (posts are created via composer only)", () => {
    const result = syncRouteFromUrl("/post/new/", new URLSearchParams(), data);
    expect(result).toEqual({ kind: "redirect", href: "/feed/" });
  });

  it("redirects legacy post notes subpath with mode", () => {
    const result = syncRouteFromUrl("/post/5/notes/", new URLSearchParams(), data);
    expect(result.kind).toBe("redirect");
    if (result.kind !== "redirect") return;
    expect(result.href).toBe("/post/5/");
    expect(result.postMode).toEqual({ postId: "5", mode: "notes", chatId: null });
  });

  it("preserves chat query on legacy post redirect", () => {
    const result = syncRouteFromUrl(
      "/post/5/chats/",
      new URLSearchParams("chat=2"),
      data,
    );
    expect(result.kind).toBe("redirect");
    if (result.kind !== "redirect") return;
    expect(result.href).toBe("/post/5/?chat=2");
    expect(result.postMode?.mode).toBe("chats");
    expect(result.postMode?.chatId).toBe("2");
  });

  it("syncs gchat from query param", () => {
    const result = syncRouteFromUrl("/gchat/", new URLSearchParams("id=gc1"), data);
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.screen).toBe("gchat");
    expect(result.patch).not.toHaveProperty("currentGChatId");
  });

  it("syncs post with chat query", () => {
    const result = syncRouteFromUrl("/post/1/", new URLSearchParams("chat=2"), data);
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.currentPostId).toBe("1");
    expect(result.patch).not.toHaveProperty("currentPostChatId");
    expect(result.postMode).toEqual({ postId: "1", mode: "chat", chatId: "2" });
  });

  it("uses postModeOverride when provided", () => {
    const result = syncRouteFromUrl("/post/1/", new URLSearchParams(), data, {
      postModeOverride: "notes",
      getPostMode: () => "chat",
    });
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch).not.toHaveProperty("postMode");
    expect(result.postMode?.mode).toBe("notes");
  });

  it("falls back to getPostMode", () => {
    const result = syncRouteFromUrl("/post/1/", new URLSearchParams(), data, {
      getPostMode: () => "comments",
    });
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.postMode?.mode).toBe("comments");
  });

  it("loads global note from cache", () => {
    const result = syncRouteFromUrl("/note/global/gn1/", new URLSearchParams(), data);
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.currentNote?.title).toBe("Global note");
    expect(result.patch.noteMode).toBe("view");
  });

  it("sets currentNote null when global note missing", () => {
    const result = syncRouteFromUrl("/note/global/missing/", new URLSearchParams(), data);
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.currentNote).toBeNull();
  });

  it("loads post note from cache", () => {
    const result = syncRouteFromUrl("/note/post/1/10/", new URLSearchParams(), data);
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.currentNote?.title).toBe("Note 10");
    expect(result.patch.currentPostId).toBe("1");
  });

  it("creates new note patch from query", () => {
    const result = syncRouteFromUrl(
      "/note/new/",
      new URLSearchParams("from=post&postId=1"),
      data,
    );
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.noteMode).toBe("edit");
    expect(result.patch.currentNote?.isNew).toBe(true);
    expect(result.patch.currentPostId).toBe("1");
  });

  it("does not reset list filters in patch", () => {
    const result = syncRouteFromUrl("/feed/", new URLSearchParams(), data);
    expect(result.kind).toBe("sync");
    if (result.kind !== "sync") return;
    expect(result.patch.screen).toBe("feed");
    expect(result.patch.chatsTab).toBeUndefined();
    expect(result.patch.analyticsPeriod).toBeUndefined();
  });
});

describe("routeSyncKey", () => {
  it("combines path and search", () => {
    expect(routeSyncKey("/feed/", new URLSearchParams("q=1"))).toBe("/feed/?q=1");
  });
});

describe("routeNeedsCachedData", () => {
  it("is true for global and post note paths", () => {
    expect(routeNeedsCachedData("/note/global/gn1/")).toBe(true);
    expect(routeNeedsCachedData("/note/post/1/10/")).toBe(true);
  });

  it("is false for list screens and new note", () => {
    expect(routeNeedsCachedData("/notes/")).toBe(false);
    expect(routeNeedsCachedData("/note/new/")).toBe(false);
    expect(routeNeedsCachedData("/feed/")).toBe(false);
  });
});

describe("isNoteRouteDataQuery", () => {
  const accountId = "demo-full";

  it("matches global note list only for global note path", () => {
    const key = queryKeys.globalNotes.list(accountId);
    expect(isNoteRouteDataQuery("/note/global/gn1/", key)).toBe(true);
    expect(isNoteRouteDataQuery("/note/post/1/10/", key)).toBe(false);
  });

  it("matches posts list only for post note path", () => {
    const key = queryKeys.posts.list(accountId);
    expect(isNoteRouteDataQuery("/note/post/1/10/", key)).toBe(true);
    expect(isNoteRouteDataQuery("/note/global/gn1/", key)).toBe(false);
  });
});

describe("mergeNoteCachePatch", () => {
  const dirtyNote: ActiveNote = {
    id: "gn1",
    title: "Edited",
    body: "changed",
    ai: false,
    date: "2024-01-01",
    isGlobal: true,
    files: [],
  };

  it("preserves new note draft on cache resync", () => {
    const incoming = syncRouteFromUrl("/note/new/", new URLSearchParams(), data);
    if (incoming.kind !== "sync") throw new Error("expected sync");
    const merged = mergeNoteCachePatch(
      {
        currentNote: { ...dirtyNote, isNew: true },
        noteMode: "edit",
        noteFrom: "notes",
        noteSavedSnapshot: EMPTY_NOTE_SNAPSHOT,
        currentPostId: null,
      },
      incoming.patch,
    );
    expect(merged.currentNote).toBeUndefined();
  });

  it("preserves dirty existing note on cache resync", () => {
    const incoming = syncRouteFromUrl("/note/global/gn1/", new URLSearchParams(), data);
    if (incoming.kind !== "sync") throw new Error("expected sync");
    const merged = mergeNoteCachePatch(
      {
        currentNote: dirtyNote,
        noteMode: "edit",
        noteFrom: "notes",
        noteSavedSnapshot: EMPTY_NOTE_SNAPSHOT,
        currentPostId: null,
      },
      incoming.patch,
    );
    expect(merged.currentNote).toBeUndefined();
  });

  it("applies cache when note is clean", () => {
    const incoming = syncRouteFromUrl("/note/global/gn1/", new URLSearchParams(), data);
    if (incoming.kind !== "sync") throw new Error("expected sync");
    const cleanNote = incoming.patch.currentNote!;
    const merged = mergeNoteCachePatch(
      {
        currentNote: cleanNote,
        noteMode: "view",
        noteFrom: "notes",
        noteSavedSnapshot: incoming.patch.noteSavedSnapshot!,
        currentPostId: null,
      },
      incoming.patch,
    );
    expect(merged.currentNote?.title).toBe("Global note");
  });
});
