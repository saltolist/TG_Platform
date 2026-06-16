import type { RefObject } from "react";
import { useLayoutEffect } from "react";

import {
  PROFILE_HEADER_CHANNEL_SUMMARY_COMPACT_MAX,
  PROFILE_HEADER_CHANNEL_SUMMARY_TWO_ROW_MAX,
  PROFILE_HEADER_CHART_MAX_POINTS_MAX,
  PROFILE_HEADER_CHART_NARROW_MAX,
  PROFILE_HEADER_CHART_SHORT_MAX,
  PROFILE_HEADER_PLATFORM_PERIOD_MAX,
  PROFILE_HEADER_TOP_POSTS_COMPACT_MAX,
  syncProfileHeaderTrashCompactToDocument,
} from "@/shared/lib/profileBreakpoints";

const PROFILE_HEADER_ATTRS = [
  "data-page-header-le-841",
  "data-page-header-le-780",
  "data-page-header-le-1080",
  "data-page-header-le-640",
  "data-page-header-le-1130",
  "data-page-header-le-804",
  "data-page-header-le-930",
  "data-page-header-le-650",
] as const;

export function syncProfilePageHeaderBreakpoints(widthPx: number, isMobile: boolean): void {
  const w = widthPx;
  syncProfileHeaderTrashCompactToDocument(w, isMobile);
  document.documentElement.toggleAttribute("data-page-header-le-841", !isMobile && w > 0 && w <= 841);
  document.documentElement.toggleAttribute(
    "data-page-header-le-780",
    !isMobile && w > 0 && w <= PROFILE_HEADER_TOP_POSTS_COMPACT_MAX,
  );
  document.documentElement.toggleAttribute(
    "data-page-header-le-1080",
    !isMobile && w > 0 && w <= PROFILE_HEADER_CHART_MAX_POINTS_MAX,
  );
  document.documentElement.toggleAttribute(
    "data-page-header-le-640",
    !isMobile && w > 0 && w <= PROFILE_HEADER_CHART_NARROW_MAX,
  );
  document.documentElement.toggleAttribute(
    "data-page-header-le-1130",
    !isMobile && w > 0 && w <= PROFILE_HEADER_CHANNEL_SUMMARY_COMPACT_MAX,
  );
  document.documentElement.toggleAttribute(
    "data-page-header-le-804",
    !isMobile && w > 0 && w <= PROFILE_HEADER_CHART_SHORT_MAX,
  );
  document.documentElement.toggleAttribute(
    "data-page-header-le-930",
    !isMobile && w > 0 && w <= PROFILE_HEADER_CHANNEL_SUMMARY_TWO_ROW_MAX,
  );
  document.documentElement.toggleAttribute(
    "data-page-header-le-650",
    !isMobile && w > 0 && w <= PROFILE_HEADER_PLATFORM_PERIOD_MAX,
  );
}

export function clearProfilePageHeaderBreakpoints(): void {
  document.documentElement.removeAttribute("data-profile-header-trash-compact");
  for (const attr of PROFILE_HEADER_ATTRS) {
    document.documentElement.removeAttribute(attr);
  }
}

/** Profile-only responsive breakpoints on `.page-header` width. */
export function useProfilePageHeaderSync(
  headerRef: RefObject<HTMLElement | null>,
  isMobile: boolean,
  enabled: boolean,
): void {
  useLayoutEffect(() => {
    if (!enabled) return;
    const el = headerRef.current;
    if (!el) return;

    const sync = () => {
      syncProfilePageHeaderBreakpoints(Math.round(el.getBoundingClientRect().width), isMobile);
    };

    const observer = new ResizeObserver(sync);
    observer.observe(el);
    sync();

    return () => {
      observer.disconnect();
      clearProfilePageHeaderBreakpoints();
    };
  }, [headerRef, isMobile, enabled]);
}
