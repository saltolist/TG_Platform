import { describe, expect, it } from "vitest";
import {
  buildLocalChatRows,
  filterGlobalChats,
  filterLocalChatRows,
  globalChatMatchesSearch,
} from "./chatList";
import type { GlobalChat, Post } from "@/shared/types";

const chat: GlobalChat = {
  id: "c1",
  title: "Strategy",
  preview: "plan content",
  date: "today",
  history: [{ role: "user", text: "content plan" }],
};

const post: Post = {
  id: "1",
  status: "draft",
  rubric: null,
  text: "My post",
  notes: [],
  chats: [
    {
      id: "5",
      title: "Chat A",
      preview: "hello",
      date: "d",
      history: [{ role: "user", text: "hello" }],
      ai: true,
    },
  ],
};

describe("chatList", () => {
  it("matches global chat search", () => {
    expect(globalChatMatchesSearch(chat, "plan")).toBe(true);
    expect(globalChatMatchesSearch(chat, "missing")).toBe(false);
  });

  it("filters global chats", () => {
    expect(filterGlobalChats([chat], "plan")).toHaveLength(1);
    expect(filterGlobalChats([chat], "zzz")).toHaveLength(0);
  });

  it("builds and filters local chat rows", () => {
    const rows = buildLocalChatRows([post]);
    expect(rows).toHaveLength(1);
    expect(filterLocalChatRows(rows, "my post")).toHaveLength(1);
    expect(filterLocalChatRows(rows, "nope")).toHaveLength(0);
  });
});
