import { describe, expect, it } from "vitest";
import {
  buildAnyNoteItems,
  filterAnyNotes,
  filterNotesByScope,
  noteMatchesSearch,
  notesEmptyLabel,
} from "./noteList";
import type { GlobalNote, Post } from "@/shared/types";

const globalNote: GlobalNote = {
  id: "g1",
  title: "Global",
  body: "body",
  ai: true,
  date: "today",
};

const post: Post = {
  id: "1",
  status: "draft",
  rubric: null,
  text: "post",
  notes: [{ id: "10", title: "Local note", body: "local body", ai: false, date: "d" }],
  chats: [],
};

describe("noteList", () => {
  it("builds global and local note items", () => {
    const items = buildAnyNoteItems([globalNote], [post]);
    expect(items).toHaveLength(2);
    expect(items[0]?.isGlobal).toBe(true);
    expect(items[1]?.isGlobal).toBe(false);
  });

  it("filters by scope", () => {
    const items = buildAnyNoteItems([globalNote], [post]);
    expect(filterNotesByScope(items, "global")).toHaveLength(1);
    expect(filterNotesByScope(items, "local")).toHaveLength(1);
  });

  it("filters by ai context and search", () => {
    const items = buildAnyNoteItems([globalNote], [post]);
    expect(filterAnyNotes(items, { filter: "ai" })).toHaveLength(1);
    expect(filterAnyNotes(items, { filter: "noai" })).toHaveLength(1);
    expect(filterAnyNotes(items, { filter: "all", searchQuery: "local" })).toHaveLength(1);
  });

  it("matches note search", () => {
    expect(noteMatchesSearch({ title: "A", body: "B" }, "b")).toBe(true);
    expect(noteMatchesSearch({ title: "A", body: "B" }, "zzz")).toBe(false);
  });

  it("returns empty labels by scope", () => {
    expect(notesEmptyLabel("global")).toContain("глобальных");
    expect(notesEmptyLabel("local")).toContain("локальных");
  });
});
