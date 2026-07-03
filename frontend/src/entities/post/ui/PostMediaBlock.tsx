"use client";

import {
  isCompactMediaKind,
  isImageMedia,
  isVideoMedia,
  mediaKind,
  resolveMediaUrl,
} from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";
import { AnimatedStickerMedia } from "./media/AnimatedStickerMedia";
import { StickerMedia } from "./media/StickerMedia";
import { VideoNoteMedia } from "./media/VideoNoteMedia";
import { VideoStickerMedia } from "./media/VideoStickerMedia";

type Props = {
  media: PostMedia[];
  onRemove?: (index: number) => void;
  /** Comment thread layout: left-aligned compact media, no feed-style centering. */
  variant?: "default" | "comment";
};

export default function PostMediaBlock({ media, onRemove, variant = "default" }: Props) {
  if (!media || media.length === 0) return null;

  const n = media.length;
  const compactSingle = n === 1 && isCompactMediaKind(media[0]);
  const layout = layoutClass(n);
  const editable = !!onRemove;

  return (
    <div
      className={`tg-media ${layout}${editable ? " tg-media-editable" : ""}${n === 1 ? " single" : ""}${compactSingle ? " tg-media--compact" : ""}${variant === "comment" ? " tg-media--comment" : ""}`}
      data-count={n}
    >
      {media.map((m, i) => (
        <div
          key={`${m.name}-${i}`}
          className={`tg-media-item${slotClass(n, i)}${isCompactMediaKind(m) ? " tg-media-item--compact" : ""}`}
        >
          <MediaInner media={m} />
          {onRemove ? (
            <button
              type="button"
              className="tg-media-remove"
              onClick={(e) => {
                e.stopPropagation();
                onRemove(i);
              }}
              aria-label="Удалить медиа"
              title="Удалить"
            >
              <svg
                className="tg-media-remove-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.25"
                strokeLinecap="round"
                aria-hidden
              >
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function MediaInner({ media }: { media: PostMedia }) {
  const kind = mediaKind(media);
  if (kind === "animated_sticker") {
    return <AnimatedStickerMedia media={media} />;
  }
  if (kind === "video_sticker") {
    return <VideoStickerMedia media={media} />;
  }
  if (kind === "sticker") {
    return <StickerMedia media={media} />;
  }
  if (kind === "video_note" || isVideoMedia(media)) {
    return <VideoNoteMedia media={media} />;
  }

  const src = resolveMediaUrl(media.url);
  if (isImageMedia(media) && src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="tg-media-img" src={src} alt={media.name} loading="lazy" />;
  }
  return (
    <div className="tg-media-doc">
      <div className="tg-media-doc-icon">📎</div>
      <div className="tg-media-doc-name">{media.name || "Файл"}</div>
    </div>
  );
}

function layoutClass(n: number): string {
  if (n <= 1) return "cols-1";
  if (n === 2) return "cols-2";
  if (n === 3) return "cols-2 rows-2 layout-3";
  if (n === 4) return "cols-2 rows-2";
  if (n <= 6) return "cols-3";
  return "cols-3";
}

function slotClass(n: number, i: number): string {
  if (n === 3 && i === 0) return " span-2";
  return "";
}
