"use client";

import { resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

export function StickerMedia({ media }: Props) {
  const src = resolveMediaUrl(media.url);
  if (!src) return null;
  return (
    <div className="tg-media-compact-slot">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="tg-media-sticker" src={src} alt={media.name || "Стикер"} loading="lazy" />
    </div>
  );
}
