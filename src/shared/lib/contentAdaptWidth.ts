import {
  PROFILE_CHANNEL_INPUT_SHRINK_MAX,
  syncProfileAiAdaptToDocument,
} from "@/shared/lib/profileBreakpoints";

/** Ширина viewport для правил адаптации контента (не шапки). */
export const MOBILE_SHELL_MAX_WIDTH = 760;

export function readNavSidebarWidthPx(): number {
  if (typeof window === "undefined") return 220;
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--nav-sidebar-w").trim();
  const px = parseFloat(raw);
  return Number.isFinite(px) ? px : 220;
}

export function isShellOverlayMode(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia(`(max-width: ${MOBILE_SHELL_MAX_WIDTH}px)`).matches;
}

/** Эффективная ширина: при overlay-сайдбаре = 100vw + ширина «пропавшего» сайдбара. */
export function getContentAdaptWidthPx(): number {
  if (typeof window === "undefined") return 0;
  const vw = window.innerWidth;
  return vw + (isShellOverlayMode() ? readNavSidebarWidthPx() : 0);
}

export function syncContentAdaptWidthToDocument(): number {
  const viewportPx = typeof window !== "undefined" ? window.innerWidth : 0;
  const adapt = getContentAdaptWidthPx();
  const root = document.documentElement;
  root.style.setProperty("--content-adapt-w", `${adapt}px`);
  const overlay = isShellOverlayMode();
  root.toggleAttribute("data-content-adapt-ge-761", adapt >= 761);
  root.toggleAttribute("data-content-adapt-le-1000", adapt <= PROFILE_CHANNEL_INPUT_SHRINK_MAX);
  root.toggleAttribute("data-shell-overlay", overlay);
  syncProfileAiAdaptToDocument(adapt, { viewportPx, shellOverlay: overlay });
  return adapt;
}
