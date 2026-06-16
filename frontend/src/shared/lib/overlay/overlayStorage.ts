import { createEmptyOverlay, type AccountOverlay } from "@/shared/lib/overlay/overlayTypes";
import { getOverlayAccountKey } from "@/shared/lib/overlay/isOverlayAccount";

const OVERLAY_KEY_PREFIX = "tg-overlay:";

function storageKey(accountId: string): string {
  return `${OVERLAY_KEY_PREFIX}${accountId}`;
}

export function readOverlay(accountId = getOverlayAccountKey()): AccountOverlay {
  if (typeof window === "undefined") return createEmptyOverlay();
  try {
    const raw = window.localStorage.getItem(storageKey(accountId));
    if (!raw) return createEmptyOverlay();
    const parsed = JSON.parse(raw) as AccountOverlay;
    return {
      ...createEmptyOverlay(),
      ...parsed,
      posts: { ...createEmptyOverlay().posts, ...parsed.posts },
      globalChats: { ...createEmptyOverlay().globalChats, ...parsed.globalChats },
      globalNotes: { ...createEmptyOverlay().globalNotes, ...parsed.globalNotes },
    };
  } catch {
    return createEmptyOverlay();
  }
}

export function writeOverlay(overlay: AccountOverlay, accountId = getOverlayAccountKey()): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(accountId), JSON.stringify(overlay));
}

export function clearOverlay(accountId = getOverlayAccountKey()): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(storageKey(accountId));
}

export function mutateOverlay(
  mutator: (overlay: AccountOverlay) => void,
  accountId = getOverlayAccountKey(),
): AccountOverlay {
  const overlay = readOverlay(accountId);
  mutator(overlay);
  writeOverlay(overlay, accountId);
  return overlay;
}
