"use client";

import { createMediaQueryHook } from "@/shared/lib/hooks/createMediaQueryHook";

import { profileHeaderTabsCompactMq } from "@/shared/lib/profileBreakpoints";

/** Viewport ≤ 1000px — вкладки в шапке поста уходят в overflow. */
export function useCompactHeader1000(): boolean {
  return useCompactHeader1000Hook();
}

const useCompactHeader1000Hook = createMediaQueryHook(profileHeaderTabsCompactMq);
