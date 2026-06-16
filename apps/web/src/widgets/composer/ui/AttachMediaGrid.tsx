"use client";

import { isImageMedia, isVideoMedia } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type GridItem = { media: PostMedia; title: string; onPick: () => void };

export function AttachMediaGrid({ items }: { items: GridItem[] }) {
  if (items.length === 0) return <div className="ctx-item disabled">Нет медиа</div>;
  const n = items.length;
  const cols = n === 1 ? 1 : n === 2 ? 2 : n === 4 ? 2 : 3;
  return (
    <div
      className="attach-media-grid"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {items.map((item) => (
        <button
          key={`${item.title}-${item.media.name}`}
          type="button"
          className="attach-media-tile"
          onClick={item.onPick}
        >
          {isImageMedia(item.media) || isVideoMedia(item.media) ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={item.media.url} alt="" className="attach-media-thumb" />
          ) : (
            <span className="attach-media-fallback">{item.media.name}</span>
          )}
          <span className="attach-media-caption">{item.media.name}</span>
        </button>
      ))}
    </div>
  );
}
