import { describe, expect, it } from "vitest";

import type { Post } from "@/shared/types";

import {
  isStandaloneCompactTelegramPost,
  postSupportsPlatformEdit,
} from "./isStandaloneCompactTelegramPost";

const basePost = {
  id: "1",
  status: "published",
  text: "",
  rubric: null,
  notes: [],
  chats: [],
  telegramMessageId: "501",
} as Post;

describe("isStandaloneCompactTelegramPost", () => {
  it("detects sticker-only telegram post", () => {
    const post: Post = {
      ...basePost,
      media: [{ name: "s.webp", url: "/media/u/1.webp", type: "image/webp", kind: "sticker" }],
    };
    expect(isStandaloneCompactTelegramPost(post)).toBe(true);
    expect(postSupportsPlatformEdit(post)).toBe(false);
  });

  it("detects video-note-only telegram post", () => {
    const post: Post = {
      ...basePost,
      media: [{ name: "n.mp4", url: "/media/u/1.mp4", type: "video/mp4", kind: "video_note" }],
    };
    expect(isStandaloneCompactTelegramPost(post)).toBe(true);
  });

  it("allows sticker post with caption", () => {
    const post: Post = {
      ...basePost,
      text: "caption",
      media: [{ name: "s.webp", url: "/media/u/1.webp", type: "image/webp", kind: "sticker" }],
    };
    expect(isStandaloneCompactTelegramPost(post)).toBe(false);
    expect(postSupportsPlatformEdit(post)).toBe(true);
  });

  it("allows voice-only telegram post", () => {
    const post: Post = {
      ...basePost,
      media: [{ name: "v.ogg", url: "/media/u/1.ogg", type: "audio/ogg", kind: "voice" }],
    };
    expect(isStandaloneCompactTelegramPost(post)).toBe(false);
    expect(postSupportsPlatformEdit(post)).toBe(true);
  });

  it("allows platform draft without telegram link", () => {
    const post: Post = {
      ...basePost,
      status: "draft",
      telegramMessageId: undefined,
      media: [{ name: "s.webp", url: "/x.webp", type: "image/webp", kind: "sticker" }],
    };
    expect(isStandaloneCompactTelegramPost(post)).toBe(false);
    expect(postSupportsPlatformEdit(post)).toBe(true);
  });

  it("allows editing deleted sticker-only telegram post", () => {
    const post: Post = {
      ...basePost,
      status: "deleted",
      media: [{ name: "s.webp", url: "/media/u/1.webp", type: "image/webp", kind: "sticker" }],
    };
    expect(isStandaloneCompactTelegramPost(post)).toBe(true);
    expect(postSupportsPlatformEdit(post)).toBe(true);
  });
});
