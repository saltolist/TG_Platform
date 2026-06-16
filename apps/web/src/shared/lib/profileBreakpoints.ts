/**
 * Пороги адаптации экрана «Профиль» (desktop / tablet).
 * Mobile (viewport ≤ 760) намеренно не затрагивается.
 */

export const PROFILE_AI_ADAPT_MIN = 761;
export const PROFILE_AI_ADAPT_OVERLAY_MIN = PROFILE_AI_ADAPT_MIN - 220;
export const PROFILE_AI_ADAPT_MAX = 1300;
export const PROFILE_AI_TIER_WIDE_MIN = 1001;
export const PROFILE_AI_TIER_MID_MIN = 1001;
export const PROFILE_AI_TIER_COMPACT_MAX = 1000;

export const PROFILE_HEADER_TABS_COMPACT_MAX = 1000;

export const PROFILE_CHANNEL_INPUT_SHRINK_MAX = 1000;

export const PROFILE_AI_REMOVE_FLUSH_MIN = 1000;
export const PROFILE_AI_REMOVE_FLUSH_MAX = PROFILE_AI_ADAPT_MAX;

export const PROFILE_HEADER_TRASH_COMPACT_MIN = 780;
export const PROFILE_HEADER_TRASH_COMPACT_MAX = 1080;

export const PROFILE_HEADER_CHART_MAX_POINTS_MAX = 1080;

export const PROFILE_HEADER_CHART_NARROW_MAX = 640;

export const PROFILE_HEADER_TOP_POSTS_COMPACT_MAX = 780;

export const PROFILE_HEADER_PLATFORM_PERIOD_MAX = 650;

export const PROFILE_HEADER_CHANNEL_SUMMARY_COMPACT_MAX = 1130;

export const PROFILE_HEADER_CHANNEL_SUMMARY_TWO_ROW_MAX = 930;

export const PROFILE_HEADER_CHANNEL_CHART_HEIGHT_COMPACT_PX = 360;

export const PROFILE_HEADER_CHART_COMPACT_MAX = PROFILE_HEADER_CHANNEL_SUMMARY_COMPACT_MAX;

export const PROFILE_HEADER_CHART_SHORT_MAX = 804;

export const PROFILE_HEADER_CHART_HEIGHT_SHORT_PX = 300;

export type ProfileAiTier = "wide" | "mid" | "compact";

export function getProfileAiTier(
  widthPx: number,
  adaptMin: number = PROFILE_AI_ADAPT_MIN,
): ProfileAiTier | null {
  if (widthPx < adaptMin || widthPx > PROFILE_AI_ADAPT_MAX) {
    return null;
  }
  if (widthPx >= PROFILE_AI_TIER_WIDE_MIN) return "wide";
  if (widthPx >= PROFILE_AI_TIER_MID_MIN) return "mid";
  return "compact";
}

export type ProfileAiAdaptSyncContext = {
  viewportPx: number;
  shellOverlay: boolean;
};

export function syncProfileAiAdaptToDocument(
  contentAdaptPx: number,
  ctx?: ProfileAiAdaptSyncContext,
): void {
  const root = document.documentElement;
  const shellOverlay = ctx?.shellOverlay ?? false;
  const viewportPx = ctx?.viewportPx ?? contentAdaptPx;
  const useOverlayTierBasis =
    shellOverlay && viewportPx >= PROFILE_AI_ADAPT_OVERLAY_MIN;
  const tierBasis = useOverlayTierBasis ? viewportPx : contentAdaptPx;
  const adaptMin = useOverlayTierBasis ? PROFILE_AI_ADAPT_OVERLAY_MIN : PROFILE_AI_ADAPT_MIN;
  const tier = getProfileAiTier(tierBasis, adaptMin);
  root.toggleAttribute("data-profile-ai-adapt", tier !== null);
  if (tier === null) {
    root.removeAttribute("data-profile-ai-tier");
  } else {
    root.setAttribute("data-profile-ai-tier", tier);
  }
  const removeFlush =
    tier === "wide" &&
    contentAdaptPx >= PROFILE_AI_REMOVE_FLUSH_MIN &&
    contentAdaptPx <= PROFILE_AI_REMOVE_FLUSH_MAX;
  root.toggleAttribute("data-profile-ai-remove-flush", removeFlush);
}

export function syncProfileHeaderTrashCompactToDocument(
  headerWidthPx: number,
  isMobile: boolean,
): void {
  const root = document.documentElement;
  const on =
    !isMobile &&
    headerWidthPx >= PROFILE_HEADER_TRASH_COMPACT_MIN &&
    headerWidthPx <= PROFILE_HEADER_TRASH_COMPACT_MAX;
  root.toggleAttribute("data-profile-header-trash-compact", on);
}

export function clearProfileAdaptFromDocument(): void {
  const root = document.documentElement;
  root.removeAttribute("data-profile-ai-adapt");
  root.removeAttribute("data-profile-ai-tier");
  root.removeAttribute("data-profile-header-trash-compact");
  root.removeAttribute("data-profile-ai-remove-flush");
}

export const profileHeaderTabsCompactMq = `(max-width: ${PROFILE_HEADER_TABS_COMPACT_MAX}px)` as const;
