export const FEED_POST_WIDTHS = [500, 390, 270] as const;
export type FeedPostWidth = (typeof FEED_POST_WIDTHS)[number];

export const FEED_POST_WIDTH_STORAGE_KEY = "tg-platform-feed-post-width";

/** @deprecated Use FeedPostWidth — alias for ui-store / legacy naming */
export type FeedCardWidth = FeedPostWidth;

export function isFeedPostWidth(value: number): value is FeedPostWidth {
  return (FEED_POST_WIDTHS as readonly number[]).includes(value);
}

export function readStoredFeedPostWidth(): FeedPostWidth {
  if (typeof window === "undefined") return 500;
  try {
    const raw = window.localStorage.getItem(FEED_POST_WIDTH_STORAGE_KEY);
    const n = raw ? Number(raw) : NaN;
    return isFeedPostWidth(n) ? n : 500;
  } catch {
    return 500;
  }
}

export function feedPostWidthPhoneFormat(width: FeedPostWidth, isMobile: boolean): boolean {
  return isMobile || width === 270;
}

export function effectiveFeedPostWidth(width: FeedPostWidth, isMobile: boolean): FeedPostWidth {
  return isMobile ? 270 : width;
}

export function feedPostWidthLabel(width: FeedPostWidth): string {
  return width === 500 ? "Компьютер" : width === 390 ? "Планшет" : "Телефон";
}

export const FEED_POST_WIDTH_SELECT_OPTIONS = FEED_POST_WIDTHS.map((w) => ({
  value: String(w),
  label: feedPostWidthLabel(w),
}));
