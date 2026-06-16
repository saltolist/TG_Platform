import { describe, expect, it } from "vitest";

import { globalChatSchema } from "./chat";
import { globalNoteSchema } from "./note";
import { postSchema } from "./post";

const validPost = {
  id: "1",
  status: "published" as const,
  rubric: null,
  text: "Hello",
  notes: [],
  chats: [],
};

const validGlobalChat = {
  id: "gc1",
  title: "Test chat",
  preview: "Preview",
  date: "2026-05-01T00:00:00.000Z",
  history: [{ role: "user" as const, text: "Hi" }],
};

const validGlobalNote = {
  id: "gn1",
  title: "Note",
  ai: true,
  date: "2026-05-01T00:00:00.000Z",
  body: "Body",
};

describe("postSchema", () => {
  it("accepts minimal valid post", () => {
    expect(postSchema.parse(validPost)).toMatchObject({ id: "1", status: "published" });
  });

  it("rejects invalid status", () => {
    expect(() => postSchema.parse({ ...validPost, status: "archived" })).toThrow();
  });

  it("rejects missing text", () => {
    const { text: _, ...rest } = validPost;
    expect(() => postSchema.parse(rest)).toThrow();
  });
});

describe("globalChatSchema", () => {
  it("accepts valid global chat", () => {
    expect(globalChatSchema.parse(validGlobalChat).id).toBe("gc1");
  });

  it("rejects invalid history role", () => {
    expect(() =>
      globalChatSchema.parse({
        ...validGlobalChat,
        history: [{ role: "bot", text: "Hi" }],
      }),
    ).toThrow();
  });
});

describe("globalNoteSchema", () => {
  it("accepts valid global note", () => {
    expect(globalNoteSchema.parse(validGlobalNote).title).toBe("Note");
  });

  it("rejects non-boolean ai flag", () => {
    expect(() => globalNoteSchema.parse({ ...validGlobalNote, ai: "yes" })).toThrow();
  });
});
