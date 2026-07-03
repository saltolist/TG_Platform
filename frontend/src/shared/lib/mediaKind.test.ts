import { describe, expect, it } from "vitest";
import {
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

  it("falls back to image/video without kind", () => {
    expect(
      mediaKind({ name: "a.jpg", url: "/media/u/a.jpg", type: "image/jpeg" }),
    ).toBe("image");
    expect(
      mediaKind({ name: "b.mp4", url: "/media/u/b.mp4", type: "video/mp4" }),
    ).toBe("video");
  });
});
