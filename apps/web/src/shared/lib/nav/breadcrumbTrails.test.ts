import { describe, expect, it, vi } from "vitest";

import {
  buildGChatBreadcrumbTrail,
  buildNoteBreadcrumbTrail,
  buildPostBreadcrumbTrail,
} from "@/shared/lib/nav/breadcrumbTrails";
import { breadcrumbItemClassName } from "@/shared/ui/breadcrumb";
import type { ActiveNote, LocalChat, Post } from "@/shared/types";

const post: Post = {
  id: "1",
  status: "published",
  rubric: null,
  text: "Post body",
  notes: [],
  chats: [],
};

const activeChat: LocalChat = {
  id: "10",
  title: "Chat title",
  preview: "",
  date: "d",
  history: [],
  ai: true,
};

describe("breadcrumbItemClassName", () => {
  it("keeps post subpage labels fixed (not truncate)", () => {
    const items = buildPostBreadcrumbTrail({
      post,
      postMode: "notes",
      currentPostChatId: null,
      activeChat: null,
      postSubPage: "Заметки",
      postIntermediateCrumb: "Long post title",
      onNavigateFeed: vi.fn(),
      onOpenPostView: vi.fn(),
      onResetToPostChatRoot: vi.fn(),
    });
    expect(breadcrumbItemClassName(items[2]!, 2, true)).toContain("bc-crumb-fixed");
    expect(breadcrumbItemClassName(items[2]!, 2, true)).not.toContain("bc-crumb-truncate");
    expect(breadcrumbItemClassName(items[1]!, 1, false)).toContain("bc-post-title");
  });

  it("marks first segment bold via bc-crumb-first", () => {
    const items = buildPostBreadcrumbTrail({
      post,
      postMode: "chat",
      currentPostChatId: null,
      activeChat: null,
      postSubPage: null,
      postIntermediateCrumb: "Post title",
      onNavigateFeed: vi.fn(),
      onOpenPostView: vi.fn(),
      onResetToPostChatRoot: vi.fn(),
    });
    expect(breadcrumbItemClassName(items[0]!, 0, false)).toContain("bc-crumb-first");
  });
});

describe("buildNoteBreadcrumbTrail", () => {
  it("builds global note trail with truncating title", () => {
    const note: ActiveNote = {
      id: "g1",
      isGlobal: true,
      title: "My note",
      body: "",
      ai: false,
      date: "d",
      files: [],
    };
    const items = buildNoteBreadcrumbTrail({
      note,
      parentPost: null,
      onNavigateNotes: vi.fn(),
      onNavigateFeed: vi.fn(),
      onOpenPost: vi.fn(),
    });
    expect(items).toHaveLength(2);
    expect(items[0]?.label).toBe("Заметки");
    expect(items[1]?.variant).toBe("truncate");
  });
});

describe("buildPostBreadcrumbTrail", () => {
  const base = {
    post,
    postMode: "chat" as const,
    currentPostChatId: null,
    activeChat: null,
    postSubPage: null,
    postIntermediateCrumb: "Post title",
    onNavigateFeed: vi.fn(),
    onOpenPostView: vi.fn(),
    onResetToPostChatRoot: vi.fn(),
  };

  it("builds subpage trail without truncating mode label", () => {
    const items = buildPostBreadcrumbTrail({ ...base, postSubPage: "Заметки" });
    expect(items).toHaveLength(3);
    expect(items[2]?.label).toBe("Заметки");
    expect(items[2]?.variant).toBeUndefined();
  });

  it("truncates active chat title", () => {
    const items = buildPostBreadcrumbTrail({
      ...base,
      currentPostChatId: "10",
      activeChat,
    });
    expect(items).toHaveLength(3);
    expect(items[2]?.label).toBe("Chat title");
    expect(items[2]?.variant).toBe("truncate");
  });
});

describe("buildGChatBreadcrumbTrail", () => {
  it("truncates chat title only", () => {
    const items = buildGChatBreadcrumbTrail({
      chatTitle: "Strategy",
      onNavigateBackToChats: vi.fn(),
    });
    expect(items[0]?.variant).toBeUndefined();
    expect(items[1]?.variant).toBe("truncate");
  });
});
