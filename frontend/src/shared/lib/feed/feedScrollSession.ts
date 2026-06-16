const STORAGE_KEY = "tg-platform-feed-scroll-top";

function readStoredScrollTop(): number {
  if (typeof sessionStorage === "undefined") return 0;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw == null) return 0;
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 ? value : 0;
  } catch {
    return 0;
  }
}

function writeStoredScrollTop(value: number): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, String(Math.max(0, Math.round(value))));
  } catch {
    /* private mode / quota */
  }
}

let feedScrollTopMemory = readStoredScrollTop();
let feedSessionDidInitialScroll = feedScrollTopMemory > 0;

export function getFeedScrollTop(): number {
  return feedScrollTopMemory;
}

export function setFeedScrollTop(value: number): void {
  feedScrollTopMemory = value;
  writeStoredScrollTop(value);
}

export function getFeedSessionDidInitialScroll(): boolean {
  return feedSessionDidInitialScroll;
}

export function markFeedSessionInitialScrollDone(): void {
  feedSessionDidInitialScroll = true;
}

export function resetFeedScrollSession(): void {
  feedScrollTopMemory = 0;
  feedSessionDidInitialScroll = false;
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function clampScrollTop(scrollTop: number, scrollHeight: number, clientHeight: number): number {
  const max = Math.max(0, scrollHeight - clientHeight);
  return Math.min(scrollTop, max);
}
