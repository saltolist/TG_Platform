"use client";

import { isImageMedia, isVideoMedia } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia[];
  onRemove?: (index: number) => void;
};

export default function PostMediaBlock({ media, onRemove }: Props) {
  if (!media || media.length === 0) return null;

  const n = media.length;
  const layout = layoutClass(n);
  const editable = !!onRemove;

  return (
    <div
      className={`tg-media ${layout}${editable ? " tg-media-editable" : ""}${n === 1 ? " single" : ""}`}
      data-count={n}
    >
      {media.map((m, i) => (
        <div key={`${m.name}-${i}`} className={`tg-media-item${slotClass(n, i)}`}>
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
  if (isImageMedia(media) && media.url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="tg-media-img" src={media.url} alt={media.name} loading="lazy" />;
  }
  if (isVideoMedia(media) && media.url) {
    return (
      <video
        className="tg-media-video"
        src={media.url}
        controls
        preload="metadata"
        playsInline
      />
    );
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
