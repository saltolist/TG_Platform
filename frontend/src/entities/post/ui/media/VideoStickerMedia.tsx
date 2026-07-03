"use client";

import { resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

export function VideoStickerMedia({ media }: Props) {
  const src = resolveMediaUrl(media.url);
  if (!src) return null;
  return (
    <video
      className="tg-media-video-sticker"
      src={src}
      autoPlay
      loop
      muted
      playsInline
      preload="metadata"
    />
  );
}
