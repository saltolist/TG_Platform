import { describe, expect, it } from "vitest";
import {
  inferPostMediaKind,
  isCompactMediaKind,
  isImageMedia,
  isVideoMedia,
  mediaKind,
} from "./helpers";
import type { PostMedia } from "@/shared/types";

describe("mediaKind helpers", () => {
  it("uses explicit kind when present", () => {
    const media: PostMedia = {
      name: "note.mp4",
      url: "/media/u/1.mp4",
      type: "video/mp4",
      kind: "video_note",
    };
    expect(mediaKind(media)).toBe("video_note");
    expect(isCompactMediaKind(media)).toBe(true);
    expect(isVideoMedia(media)).toBe(false);
  });

  it("infers animated sticker from tgsticker mime", () => {
    const media: PostMedia = {
      name: "party.tgs",
      url: "/media/u/2.tgs",
      type: "application/x-tgsticker",
    };
    expect(mediaKind(media)).toBe("animated_sticker");
    expect(isImageMedia(media)).toBe(false);
  });

  it("infers static sticker from imported webp path when kind is missing", () => {
    const media: PostMedia = {
      name: "42.webp",
      url: "/media/user-id/42.webp",
      type: "image/webp",
    };
    expect(inferPostMediaKind(media)).toBe("sticker");
    expect(mediaKind(media)).toBe("sticker");
    expect(isImageMedia(media)).toBe(false);
    expect(isCompactMediaKind(media)).toBe(true);
  });

  it("infers animated sticker from imported lottie json path", () => {
    const media: PostMedia = {
      name: "42.json",
      url: "/media/user-id/42.json",
      type: "application/json",
    };
    expect(mediaKind(media)).toBe("animated_sticker");
  });

  it("falls back to image/video without kind", () => {
    expect(
      mediaKind({ name: "a.jpg", url: "/media/u/a.jpg", type: "image/jpeg" }),
    ).toBe("image");
    expect(
      mediaKind({ name: "b.mp4", url: "/media/u/b.mp4", type: "video/mp4" }),
    ).toBe("video");
  });

  it("treats legacy mp4 without kind as compact (round video note slot)", () => {
    const media: PostMedia = {
      name: "42.mp4",
      url: "/media/user-id/42.mp4",
      type: "video/mp4",
    };
    expect(isCompactMediaKind(media)).toBe(true);
  });

  it("does not treat explicit widescreen video as compact", () => {
    const media: PostMedia = {
      name: "clip.mp4",
      url: "/media/u/clip.mp4",
      type: "video/mp4",
      kind: "video",
    };
    expect(isCompactMediaKind(media)).toBe(false);
  });
});
