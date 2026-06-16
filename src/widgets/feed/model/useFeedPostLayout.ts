"use client";

import type { CSSProperties } from "react";

import { useUiStore } from "@/app/model/store";
import {
  effectiveFeedPostWidth,
  feedPostWidthPhoneFormat,
  type FeedPostWidth,
} from "@/shared/lib/feedPostWidth";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";

export function useFeedPostLayout() {
  const feedPostWidth = useUiStore((s) => s.feedCardWidth);
  const isMobile = useMobile760();
  const effectiveWidth = effectiveFeedPostWidth(feedPostWidth, isMobile);
  const phoneFormat = feedPostWidthPhoneFormat(feedPostWidth, isMobile);

  return {
    feedPostWidth,
    effectiveWidth,
    phoneFormat,
    layoutClassName: phoneFormat ? " post-format-phone" : "",
    layoutStyle: { "--feed-post-w": `${effectiveWidth}px` } as CSSProperties,
  };
}

export type { FeedPostWidth };
