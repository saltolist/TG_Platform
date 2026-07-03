"use client";

import Lottie from "lottie-react";
import { useEffect, useState } from "react";
import { resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

export function AnimatedStickerMedia({ media }: Props) {
  const [animationData, setAnimationData] = useState<object | null>(null);
  const src = resolveMediaUrl(media.url);

  useEffect(() => {
    if (!src) return;
    let cancelled = false;
    void fetch(src)
      .then((response) => {
        if (!response.ok) throw new Error("sticker fetch failed");
        return response.json() as Promise<object>;
      })
      .then((data) => {
        if (!cancelled) setAnimationData(data);
      })
      .catch(() => {
        if (!cancelled) setAnimationData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [src]);

  if (!animationData) {
    return <div className="tg-media-sticker tg-media-sticker--loading" aria-hidden />;
  }

  return (
    <Lottie
      className="tg-media-animated-sticker"
      animationData={animationData}
      loop
      autoplay
    />
  );
}
